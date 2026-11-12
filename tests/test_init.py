"""Test component setup."""

import hashlib
import json
import logging
import re
import unittest
from pathlib import Path
from ssl import SSLEOFError, SSLError
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import homeassistant
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from packaging.requirements import Requirement
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.robovac_mqtt as robovac_init
from custom_components.robovac_mqtt import (
    _FRONTEND_DIR,
    _int_keyed,
    async_remove_config_entry_device,
)
from custom_components.robovac_mqtt.api import cloud as cloud_mod
from custom_components.robovac_mqtt.api.cloud import (
    EufyLogin,
    EufyLoginError,
    EufyLoginTransientError,
)
from custom_components.robovac_mqtt.auth_store import AuthCache, AuthStore
from custom_components.robovac_mqtt.const import (
    CONF_LOCAL_DEVICES,
    CONF_LOCAL_HOST,
    CONF_MAP_ID,
    CONF_MAP_IDS,
    DOMAIN,
)

_COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "robovac_mqtt"


async def test_load_unload_entry(hass: HomeAssistant):
    """Test loading and unloading the integration."""
    # Create a mock config entry
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_password",
        },
        entry_id="test_entry_id",
    )
    config_entry.add_to_hass(hass)

    # Mock EufyLogin and EufyCleanCoordinator
    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator"
    ) as mock_coord_cls:

        # Setup Login mock
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock()
        mock_login.mqtt_devices = [
            {
                "deviceId": "test_device_id",
                "deviceModel": "T2118",
                "deviceName": "Test Vac",
                "dps": {},
            }
        ]
        mock_login.cloud_devices = []

        # Setup Coordinator mock
        mock_coord = mock_coord_cls.return_value
        mock_coord.initialize = AsyncMock()
        # Unloading the entry awaits the coordinator's teardown.
        mock_coord.async_teardown = AsyncMock()
        mock_coord.device_id = "test_device_id"
        mock_coord.device_name = "Test Vac"
        mock_coord.device_model = "T2118"
        mock_coord.data = MagicMock()  # Mock the VacuumState data

        # Mock client and disconnect method
        mock_coord.client = MagicMock()
        mock_coord.client.disconnect = AsyncMock()
        mock_coord.async_stop_p2p = AsyncMock()

        # Setup the config entry
        result = await hass.config_entries.async_setup(config_entry.entry_id)
        assert result is True, f"Async setup failed, result: {result}"

        await hass.async_block_till_done()

        # Check if the entry state is LOADED
        assert (
            config_entry.state == ConfigEntryState.LOADED
        ), f"Entry state is {config_entry.state}, expected {ConfigEntryState.LOADED}"

        # No update listener: OptionsFlowWithReload raises if one exists, and
        # HA deprecates one next to async_update_reload_and_abort (#168).
        assert not config_entry.update_listeners

        # Verify calls
        mock_login_cls.assert_called_with(
            "test_user",
            "test_password",
            unittest.mock.ANY,
            websession=unittest.mock.ANY,
            auth_cache=unittest.mock.ANY,
        )
        mock_login.init.assert_called_once()
        mock_coord_cls.assert_called_once()
        mock_coord.initialize.assert_called_once()

        # Unload the config entry
        unload_result = await hass.config_entries.async_unload(config_entry.entry_id)
        assert unload_result is True, f"Unload failed, result: {unload_result}"

        await hass.async_block_till_done()

        # Check if the entry state is NOT_LOADED
        assert (
            config_entry.state == ConfigEntryState.NOT_LOADED
        ), f"Entry state {config_entry.state}, expected {ConfigEntryState.NOT_LOADED}"


async def test_bundled_eufy_clean_card_registered(hass: HomeAssistant):
    """The bundled card registers once `frontend` is set up (load-order safe)."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_password",
        },
        entry_id="card_entry_id",
    )
    config_entry.add_to_hass(hass)

    when_setup_calls: list = []

    def fake_when_setup(_hass, component, callback):
        when_setup_calls.append((component, callback))

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator"
    ) as mock_coord_cls, patch(
        "custom_components.robovac_mqtt.add_extra_js_url"
    ) as mock_add_js, patch(
        "custom_components.robovac_mqtt.async_when_setup", side_effect=fake_when_setup
    ):
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock()
        # Card registration is independent of devices, but setup requires at
        # least one initialized coordinator (ConfigEntryNotReady otherwise).
        mock_login.mqtt_devices = [
            {
                "deviceId": "card_device_id",
                "deviceModel": "T2118",
                "deviceName": "Card Vac",
                "dps": {},
            }
        ]
        mock_login.cloud_devices = []

        mock_coord = mock_coord_cls.return_value
        mock_coord.initialize = AsyncMock()
        # Unloading the entry awaits the coordinator's teardown.
        mock_coord.async_teardown = AsyncMock()
        mock_coord.device_id = "card_device_id"
        mock_coord.device_name = "Card Vac"
        mock_coord.device_model = "T2118"
        mock_coord.data = MagicMock()
        mock_coord.client = MagicMock()
        mock_coord.client.disconnect = AsyncMock()
        mock_coord.async_stop_p2p = AsyncMock()

        result = await hass.config_entries.async_setup(config_entry.entry_id)
        assert result is True, f"Async setup failed, result: {result}"
        await hass.async_block_till_done()

        # Registration is DEFERRED to the frontend component, not done inline — this
        # is what prevents the load-order race (entry set up before frontend) that
        # left the card unregistered on some installs (#140).
        assert len(when_setup_calls) == 1
        component, register_cb = when_setup_calls[0]
        assert component == "frontend"
        mock_add_js.assert_not_called()  # nothing registered until frontend is up

        # Frontend becomes ready -> the card registers once, with a cache-bust URL.
        with patch.object(
            hass.http, "async_register_static_paths", AsyncMock()
        ) as mock_static, patch(
            "custom_components.robovac_mqtt._card_cache_key",
            wraps=robovac_init._card_cache_key,
        ) as mock_key:
            await register_cb(hass, "frontend")
        assert hass.data[DOMAIN]["card_registered"] is True
        # The renderer the card imports is served from the card's URL directory,
        # and an edit to it changes the card's cache key.
        assert {cfg.url_path for cfg in mock_static.call_args.args[0]} == {
            "/robovac_mqtt/eufy-clean-card.js",
            "/robovac_mqtt/eufy-map-renderer.js",
        }
        assert {path.name for path in mock_key.call_args.args[0]} == {
            "eufy-clean-card.js",
            "eufy-map-renderer.js",
        }
        mock_add_js.assert_called_once()
        registered_url = mock_add_js.call_args.args[1]
        # A content hash, not the bare version a missing frontend file falls back to.
        assert re.fullmatch(
            r"/robovac_mqtt/eufy-clean-card\.js\?v=.+-[0-9a-f]{12}", registered_url
        ), registered_url
        # The hash covers the card and the renderer it imports.
        digest = hashlib.sha256()
        for name in ("eufy-clean-card.js", "eufy-map-renderer.js"):
            digest.update((_FRONTEND_DIR / name).read_bytes())
            digest.update(b"\0")
        assert registered_url.endswith(digest.hexdigest()[:12])

        # Idempotent: a second frontend-ready callback does nothing.
        await register_cb(hass, "frontend")
        mock_add_js.assert_called_once()


async def test_mixed_mqtt_and_cloud_device_setup(hass: HomeAssistant):
    """Test setup with both MQTT (novel) and cloud (legacy) devices."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_password",
        },
        entry_id="test_mixed_entry",
    )
    config_entry.add_to_hass(hass)

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator"
    ) as mock_coord_cls:

        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock()
        mock_login.mqtt_devices = [
            {
                "deviceId": "mqtt_dev_1",
                "deviceModel": "T2261",
                "deviceName": "X8 Pro",
                "dps": {"153": "something"},
                "apiType": "novel",
                "mqtt": True,
            }
        ]
        mock_login.cloud_devices = [
            {
                "deviceId": "cloud_dev_1",
                "deviceModel": "T2210",
                "deviceName": "G30",
                "dps": {"15": "Running"},
                "apiType": "legacy",
                "mqtt": False,
            }
        ]

        # Track coordinator creation calls
        coordinators = []

        def make_coordinator(*args, **kwargs):
            coord = MagicMock()
            coord.initialize = AsyncMock()
            coord.async_teardown = AsyncMock()
            device_info = args[2] if len(args) > 2 else kwargs.get("device_info", {})
            coord.device_id = device_info["deviceId"]
            coord.device_name = device_info["deviceName"]
            coord.device_model = device_info["deviceModel"]
            coord.data = MagicMock()
            coord.client = MagicMock()
            coord.client.disconnect = AsyncMock()
            coordinators.append((coord, device_info))
            return coord

        mock_coord_cls.side_effect = make_coordinator

        result = await hass.config_entries.async_setup(config_entry.entry_id)
        assert result is True
        await hass.async_block_till_done()

        # Should have created 2 coordinators
        assert len(coordinators) == 2

        device_ids = {info["deviceId"] for _, info in coordinators}
        assert "mqtt_dev_1" in device_ids
        assert "cloud_dev_1" in device_ids

        # Both should have initialize() called
        for coord, _ in coordinators:
            coord.initialize.assert_called_once()


async def test_setup_auth_failure_raises_config_entry_auth_failed(hass: HomeAssistant):
    """Login failure with EufyLoginError should result in SETUP_ERROR (auth failed)."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "bad_user", CONF_PASSWORD: "bad_pass"},
        entry_id="test_auth_fail",
    )
    config_entry.add_to_hass(hass)

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls:
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock(side_effect=EufyLoginError("Invalid credentials"))

        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_ERROR


async def test_setup_network_failure_raises_config_entry_not_ready(hass: HomeAssistant):
    """Network errors should result in SETUP_RETRY (not ready)."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        entry_id="test_network_fail",
    )
    config_entry.add_to_hass(hass)

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls:
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock(
            side_effect=aiohttp.ClientError("Connection refused")
        )

        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_setup_passes_map_id_overrides_to_coordinator(hass: HomeAssistant):
    """Stored map id overrides reach the coordinator's device_info, with the
    per-map keys (stringified by JSON storage) back as ints."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "test_user", CONF_PASSWORD: "test_password"},
        options={
            CONF_LOCAL_DEVICES: {
                "test_device_id": {CONF_MAP_ID: 1, CONF_MAP_IDS: {"2154": 2}}
            }
        },
        entry_id="test_map_id_entry",
    )
    config_entry.add_to_hass(hass)

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator"
    ) as mock_coord_cls:
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock()
        mock_login.mqtt_devices = [
            {
                "deviceId": "test_device_id",
                "deviceModel": "T2118",
                "deviceName": "Test Vac",
                "dps": {},
            }
        ]
        mock_login.cloud_devices = []

        mock_coord = mock_coord_cls.return_value
        mock_coord.initialize = AsyncMock()
        mock_coord.async_teardown = AsyncMock()
        mock_coord.device_id = "test_device_id"
        mock_coord.device_name = "Test Vac"
        mock_coord.device_model = "T2118"
        mock_coord.data = MagicMock()
        mock_coord.client = MagicMock()
        mock_coord.client.disconnect = AsyncMock()

        result = await hass.config_entries.async_setup(config_entry.entry_id)
        assert result is True
        await hass.async_block_till_done()

    device_info = mock_coord_cls.call_args.args[2]
    assert device_info["map_id_override"] == 1
    assert device_info["map_id_overrides"] == {2154: 2}


async def test_setup_logs_carry_no_local_host(hass: HomeAssistant, caplog):
    """A local-Tuya override's LAN address stays out of the setup log."""
    caplog.set_level(logging.DEBUG, logger="custom_components.robovac_mqtt")
    host = "192.168.1.50"
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "test_user", CONF_PASSWORD: "test_password"},
        options={CONF_LOCAL_DEVICES: {"tuya_dev": {CONF_LOCAL_HOST: host}}},
        entry_id="local_host_entry",
    )
    config_entry.add_to_hass(hass)

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator",
        return_value=_mock_coordinator("tuya_dev"),
    ) as mock_coord_cls:
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock()
        mock_login.mqtt_devices = []
        mock_login.cloud_devices = [
            {"deviceId": "tuya_dev", "deviceName": "Vac", "local_key": "k" * 16}
        ]
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_coord_cls.call_args.args[2]["local_host"] == host
    assert host not in caplog.text


def test_int_keyed_restores_int_keys_and_drops_bad_entries(caplog):
    """Stored override dicts come back from JSON with string keys: they are
    coerced back to int, and an entry that doesn't convert is logged and
    dropped instead of failing setup."""
    raw = {"2154": "1", "3001": 2, "kitchen": 3, "4": "x"}
    assert _int_keyed(raw, int, "dev1", "map id") == {2154: 1, 3001: 2}
    assert "ignoring non-integer map id 'kitchen'" in caplog.text
    assert "ignoring non-integer map id '4'" in caplog.text


def _mock_login(mock_login_cls, *device_ids: str) -> MagicMock:
    mock_login = mock_login_cls.return_value
    mock_login.init = AsyncMock()
    mock_login.mqtt_devices = [
        {"deviceId": d, "deviceModel": "T2118", "deviceName": f"Vac {d}", "dps": {}}
        for d in device_ids
    ]
    mock_login.cloud_devices = []
    return mock_login


def _mock_coordinator(device_id: str, init_error: Exception | None = None) -> MagicMock:
    coord = MagicMock()
    coord.initialize = AsyncMock(side_effect=init_error)
    coord.async_teardown = AsyncMock()
    coord.device_id = device_id
    coord.device_name = f"Vac {device_id}"
    coord.device_model = "T2118"
    coord.last_seen_segments = None
    coord.data = MagicMock()
    return coord


async def test_failed_coordinator_init_is_torn_down(hass: HomeAssistant):
    """A coordinator whose initialize() raises is torn down, not just dropped.

    initialize() writes the MQTT cert/key files and may start a transport before
    it fails; every ConfigEntryNotReady retry would otherwise leak another set.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="init_fail_entry",
    )
    entry.add_to_hass(hass)
    failed = _mock_coordinator("dev_fail", init_error=OSError("broker refused"))

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator", return_value=failed
    ):
        _mock_login(mock_login_cls, "dev_fail")
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    failed.async_teardown.assert_awaited_once()


@pytest.mark.parametrize(
    ("mqtt_robot", "mqtt_up", "has_user_center", "hold_off", "reloads"),
    [
        (True, False, True, 600.0, True),
        (False, False, True, 600.0, False),
        (True, True, True, 600.0, False),
        (True, False, False, 600.0, False),
        (True, False, True, None, False),
    ],
    ids=["left-out", "no-mqtt-robot", "mqtt-robot-up", "fallback-session", "no-hold-off"],
)
async def test_mqtt_robots_left_out_during_the_login_hold_off_reload_when_it_ends(
    hass: HomeAssistant, caplog, mqtt_robot, mqtt_up, has_user_center, hold_off, reloads
):
    """No login may run at setup: the Tuya robot comes up, the MQTT robot
    does not, and the entry reloads once when one may."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="held_off_entry",
    )
    entry.add_to_hass(hass)

    def coordinator(*args, **kwargs):
        device_id = args[2]["deviceId"]
        refused = device_id == "mqtt_dev" and not mqtt_up
        return _mock_coordinator(
            device_id, init_error=OSError("no MQTT credentials") if refused else None
        )

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator", side_effect=coordinator
    ), patch("custom_components.robovac_mqtt.async_call_later") as call_later:
        login = _mock_login(mock_login_cls, *(["mqtt_dev"] if mqtt_robot else []))
        login.cloud_devices = [{"deviceId": "tuya_dev", "deviceName": "Tuya"}]
        login.has_user_center = has_user_center
        login.replacement_login_wait = MagicMock(return_value=hold_off)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert call_later.called is reloads
    assert ("left out while no Eufy login may run" in caplog.text) is reloads
    if not reloads:
        return
    _hass, delay, action = call_later.call_args.args
    assert hold_off < delay <= hold_off + 2
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        action(None)
    reload.assert_called_once_with(entry.entry_id)


async def test_a_reload_armed_while_setup_runs_is_not_armed_twice(
    hass: HomeAssistant, caplog
):
    """A robot armed the reload during setup; setup leaves it as it is."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="armed_in_setup_entry",
    )
    entry.add_to_hass(hass)

    def coordinator(*args, **kwargs):
        robot = _mock_coordinator(args[2]["deviceId"])
        if robot.device_id == "mqtt_dev":

            async def _init():
                kwargs["reload_when_logins_resume"](600.0)
                raise OSError("refused")

            robot.initialize = AsyncMock(side_effect=_init)
        return robot

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator", side_effect=coordinator
    ), patch("custom_components.robovac_mqtt.async_call_later") as call_later:
        login = _mock_login(mock_login_cls, "mqtt_dev")
        login.cloud_devices = [{"deviceId": "tuya_dev", "deviceName": "Tuya"}]
        login.has_user_center = True
        login.replacement_login_wait = MagicMock(return_value=600.0)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert call_later.call_count == 1
    assert "left out while no Eufy login may run" not in caplog.text


async def test_robots_share_one_reload_for_the_end_of_the_login_hold_off(
    hass: HomeAssistant,
):
    """A robot whose new credentials are rejected too asks for the reload:
    one timer at a time per entry, armed again after it fired, cancelled on
    unload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="runtime_hold_off_entry",
    )
    entry.add_to_hass(hass)
    created: list = []

    def coordinator(*args, **kwargs):
        created.append(kwargs)
        return _mock_coordinator(args[2]["deviceId"])

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator", side_effect=coordinator
    ), patch("custom_components.robovac_mqtt.async_call_later") as call_later, patch.object(
        hass.config_entries, "async_schedule_reload"
    ) as reload:
        _mock_login(mock_login_cls, "dev1", "dev2")
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        first, second = (c["reload_when_logins_resume"] for c in created)
        call_later.assert_not_called()

        assert first(600.0) is True
        assert second(300.0) is False
        assert call_later.call_count == 1
        _hass, delay, action = call_later.call_args.args
        assert 600.0 < delay <= 602.0
        action(None)
        reload.assert_called_once_with(entry.entry_id)
        assert second(900.0) is True
        assert call_later.call_count == 2

        assert await hass.config_entries.async_unload(entry.entry_id)
    call_later.return_value.assert_called_once()


@pytest.mark.parametrize(
    ("down", "left_out", "reloads"),
    [
        ((False, False), False, False),
        ((False, True), False, True),
        ((False, False), True, True),
    ],
    ids=["every-robot-back", "one-robot-down", "one-robot-left-out"],
)
async def test_the_hold_off_reload_fires_only_while_a_robot_is_still_out(
    hass: HomeAssistant, caplog, down, left_out, reloads
):
    """A robot armed the reload; when it fires, every MQTT robot connected
    again and none was left out of setup: no reload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="recovered_entry",
    )
    entry.add_to_hass(hass)
    created: list = []
    states = dict(zip(("dev1", "dev2"), down))

    def coordinator(*args, **kwargs):
        created.append(kwargs)
        device_id = args[2]["deviceId"]
        if device_id not in states:
            return _mock_coordinator(device_id, init_error=OSError("refused"))
        robot = _mock_coordinator(device_id)
        robot.mqtt_session_down = states[device_id]
        return robot

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator", side_effect=coordinator
    ), patch("custom_components.robovac_mqtt.async_call_later") as call_later, patch.object(
        hass.config_entries, "async_schedule_reload"
    ) as reload:
        login = _mock_login(mock_login_cls, "dev1", "dev2", *(["dev3"] if left_out else []))
        login.replacement_login_wait = MagicMock(return_value=None)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        caplog.set_level(logging.DEBUG, logger="custom_components.robovac_mqtt")
        assert created[0]["reload_when_logins_resume"](600.0) is True
        call_later.call_args.args[2](None)

        assert reload.called is reloads
        assert ("every MQTT robot is connected" in caplog.text) is not reloads
        assert await hass.config_entries.async_unload(entry.entry_id)


_CACHED_MQTT = {
    "user_id": "uid",
    "app_name": "app",
    "thing_name": "thing",
    "certificate_pem": "cached",
    "private_key": "key",
    "endpoint_addr": "broker.example.com",
}


def _account(login_result):
    """The real EufyLogin over a mocked HTTP client: discovery finds two MQTT
    robots and the cached certificate; a login answers ``login_result``."""

    def build(*args, **kwargs):
        login = EufyLogin(*args, **kwargs)
        login.eufyApi = MagicMock(
            session={"access_token": "t"}, user_info={"user_center_id": "c"},
            login_label=None,
        )
        login.eufyApi.login = AsyncMock(side_effect=[login_result])

        async def _init():
            login.mqtt_credentials = login.auth_cache.mqtt_credentials = _CACHED_MQTT
            login.mqtt_devices = [
                {"deviceId": d, "deviceModel": "T2118", "deviceName": d, "dps": {}}
                for d in ("first", "second")
            ]

        login.init = AsyncMock(side_effect=_init)
        return login

    return build


def _brokers(*outcomes):
    """MQTT clients in creation order: connect() raises the outcome, or
    reports the accepted connection (None)."""
    pending = iter(outcomes)

    def client(**_kwargs):
        outcome = next(pending)
        mock = MagicMock(disconnect=AsyncMock(), is_connected=outcome is None)

        async def _connect():
            if outcome is not None:
                raise outcome
            mock.set_connection_listener.call_args.args[0](True, None)

        mock.connect = AsyncMock(side_effect=_connect)
        return mock

    return client


_EOF = SSLEOFError(8, "EOF occurred in violation of protocol")


def _revoked() -> SSLError:
    err = SSLError(1, "[SSL: SSLV3_ALERT_CERTIFICATE_REVOKED] alert")
    err.reason = "SSLV3_ALERT_CERTIFICATE_REVOKED"
    return err


@pytest.mark.parametrize(
    ("login_result", "outcomes", "wait"),
    [
        (
            {"mqtt": {**_CACHED_MQTT, "certificate_pem": "new"}},
            [_revoked(), None, _EOF, _EOF],
            cloud_mod._MQTT_RELOGIN_MIN_INTERVAL,
        ),
        (
            EufyLoginTransientError("HTTP 503"),
            [None, _revoked()],
            cloud_mod._MQTT_RELOGIN_RETRY_DELAY,
        ),
    ],
    ids=["closed-after-a-replacement", "replacement-login-failed"],
)
async def test_a_robot_left_out_while_no_replacement_login_may_run_reloads_then(
    hass: HomeAssistant, caplog, login_result, outcomes, wait
):
    """The second robot's handshake is closed after the first got new
    credentials, or its replacement login failed: the entry reloads when
    the next replacement login may run."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="left_out_entry",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.robovac_mqtt.EufyLogin", side_effect=_account(login_result)
    ), patch(
        "custom_components.robovac_mqtt.coordinator.EufyCleanClient",
        side_effect=_brokers(*outcomes),
    ), patch(
        "custom_components.robovac_mqtt.coordinator._SETUP_HANDSHAKE_RETRY_DELAY", 0.0
    ), patch("custom_components.robovac_mqtt.async_call_later") as call_later:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        started = {c.device_id for c in hass.data[DOMAIN][entry.entry_id]["coordinators"]}
        assert "second" not in started
        call_later.assert_called_once()
        _hass, delay, _action = call_later.call_args.args
        assert wait - 5 < delay <= wait + 2
        assert "left out while no Eufy login may run" in caplog.text
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "error", [EufyLoginTransientError("HTTP 503"), aiohttp.ClientError("reset")]
)
async def test_transient_login_failure_retries_and_keeps_tokens(
    hass: HomeAssistant, error: Exception
):
    """A 5xx/network failure retries setup and persists the cache with its tokens."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="transient_entry",
    )
    entry.add_to_hass(hass)
    cache = AuthCache(openudid="stable", session={"access_token": "t"})

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch.object(
        AuthStore, "async_load", AsyncMock(return_value=cache)
    ), patch.object(AuthStore, "async_save", AsyncMock()) as mock_save:
        mock_login_cls.return_value.init = AsyncMock(side_effect=error)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    mock_save.assert_awaited_once_with(cache)
    assert cache.session == {"access_token": "t"}


def _rate_limited_websession(retry_after: str) -> tuple[MagicMock, list[str]]:
    """A websession answering every login with HTTP 429; records each openudid sent."""
    sent: list[str] = []
    response = MagicMock(status=429, headers={"Retry-After": retry_after})
    response.json = AsyncMock(return_value=None)

    def post(_url, **kwargs):
        sent.append(kwargs["headers"]["openudid"])
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=response)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    websession = MagicMock()
    websession.post.side_effect = post
    websession.get.side_effect = AssertionError("no authenticated call expected")
    return websession, sent


async def test_rate_limited_first_start_holds_off_and_keeps_the_openudid(
    hass: HomeAssistant,
):
    """HTTP 429 at login starts a persisted hold-off from Retry-After; the retry
    inside it sends nothing, and the openudid is the one already sent."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="rate_limited_entry",
    )
    entry.add_to_hass(hass)
    websession, sent = _rate_limited_websession("120")

    with patch(
        "custom_components.robovac_mqtt.async_get_clientsession", return_value=websession
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_RETRY
        assert len(sent) == 1

        stored = await AuthStore(hass, entry.entry_id).async_load()
        assert stored.openudid == sent[0]
        left = stored.login_hold_off_left()
        assert left is not None and 110 < left <= 120

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert len(sent) == 1
    assert (await AuthStore(hass, entry.entry_id).async_load()).openudid == sent[0]


async def test_global_registration_runs_once_for_several_entries(hass: HomeAssistant):
    """The frontend hook and websocket commands register in async_setup, once."""
    with patch(
        "custom_components.robovac_mqtt.async_when_setup"
    ) as mock_when_setup, patch(
        "custom_components.robovac_mqtt.async_setup_websocket_api"
    ) as mock_ws, patch(
        "custom_components.robovac_mqtt.EufyLogin"
    ) as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator",
        side_effect=lambda *a, **k: _mock_coordinator(a[2]["deviceId"]),
    ):
        _mock_login(mock_login_cls, "dev_a")
        for n in range(2):
            MockConfigEntry(
                domain=DOMAIN,
                data={CONF_USERNAME: f"user{n}@example.com", CONF_PASSWORD: "pw"},
                entry_id=f"entry_{n}",
            ).add_to_hass(hass)
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
        await hass.config_entries.async_reload("entry_0")
        await hass.async_block_till_done()

    assert mock_when_setup.call_count == 1
    assert mock_ws.call_count == 1


async def test_remove_device_refused_while_the_api_still_returns_it(
    hass: HomeAssistant,
):
    """Only a device the Eufy API no longer returns can be removed by the user."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="rm_entry")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinators": [_mock_coordinator("dev_live")]
    }
    registry = dr.async_get(hass)
    live = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "dev_live")}
    )
    gone = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "dev_gone")}
    )

    assert await async_remove_config_entry_device(hass, entry, live) is False
    assert await async_remove_config_entry_device(hass, entry, gone) is True


def test_manifest_declares_every_runtime_import_within_ha_constraints():
    """paho-mqtt and protobuf are imported at runtime, so the manifest declares them.

    HA installs them only for its own mqtt integration; a Core venv without it
    fails to import the component. The ranges must admit HA's pinned versions.
    """
    manifest = json.loads((_COMPONENT_DIR / "manifest.json").read_text())
    reqs = {
        (r := Requirement(line)).name.lower(): r for line in manifest["requirements"]
    }
    assert {"paho-mqtt", "protobuf"} <= set(reqs)

    constraints = (
        Path(homeassistant.__file__).parent / "package_constraints.txt"
    ).read_text()
    pins = {
        name.lower(): version
        for name, _, version in (
            line.partition("==") for line in constraints.splitlines() if "==" in line
        )
    }
    for name in ("paho-mqtt", "protobuf"):
        assert reqs[name].specifier.contains(pins[name]), (name, pins[name])
