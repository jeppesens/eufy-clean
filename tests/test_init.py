"""Test component setup."""

import json
import logging
import re
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import homeassistant
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from packaging.requirements import Requirement
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.robovac_mqtt as robovac_init
from custom_components.robovac_mqtt import (
    _int_keyed,
    async_remove_config_entry_device,
)
from custom_components.robovac_mqtt.api.cloud import (
    EufyLogin,
    EufyLoginChallengeError,
    EufyLoginError,
    EufyLoginRateLimitedError,
    EufyLoginTransientError,
    EufySessionReplacedError,
)
from custom_components.robovac_mqtt.api.throttle import (
    KIND_LOGIN,
    LOGIN_BUDGET,
    LOGIN_BUDGET_WINDOW,
    REQUEST_HOLD_OFF,
    CloudThrottle,
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


@pytest.mark.parametrize(
    ("error", "keeps_tokens"),
    [
        (EufyLoginError("Invalid credentials"), False),
        (EufyLoginChallengeError("captcha", code=100032), True),
    ],
    ids=["rejected", "challenge"],
)
async def test_setup_auth_failure_raises_config_entry_auth_failed(
    hass: HomeAssistant, error, keeps_tokens
):
    """A refused login asks for reauth. Rejected credentials drop the stored
    tokens; a verification code or captcha says nothing about them."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "bad_user", CONF_PASSWORD: "bad_pass"},
        entry_id="test_auth_fail",
    )
    config_entry.add_to_hass(hass)
    await AuthStore(hass, config_entry.entry_id).async_save(
        AuthCache(openudid="0123456789abcdef", session={"access_token": "old"})
    )

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls:
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock(side_effect=error)

        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )
    stored = await AuthStore(hass, config_entry.entry_id).async_load()
    assert (stored.session is not None) is keeps_tokens
    assert stored.openudid == "0123456789abcdef"


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


async def test_credentials_a_coordinator_fetched_are_saved(hass: HomeAssistant):
    """A coordinator's login for MQTT credentials (checkLogin) runs after the
    login's own save; setup saves the cache again."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="check_login_entry",
    )
    entry.add_to_hass(hass)
    caches = []

    def _factory(*args, **kwargs):
        caches.append(kwargs["auth_cache"])
        return _mock_login(MagicMock(), "dev_a")

    def _coordinator(*args, **kwargs):
        coordinator = _mock_coordinator(args[2]["deviceId"])

        async def _initialize():
            caches[0].mqtt_credentials = {"certificate_pem": "fetched"}

        coordinator.initialize = AsyncMock(side_effect=_initialize)
        return coordinator

    with patch("custom_components.robovac_mqtt.EufyLogin", side_effect=_factory), patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator", side_effect=_coordinator
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    stored = await AuthStore(hass, entry.entry_id).async_load()
    assert stored.mqtt_credentials == {"certificate_pem": "fetched"}


@pytest.mark.parametrize(
    "error",
    [
        EufyLoginTransientError("HTTP 503"),
        EufyLoginRateLimitedError("100028", retry_after=7200, code=100028),
        aiohttp.ClientError("reset"),
        TimeoutError(),
        RuntimeError("bug"),
    ],
    ids=["transient", "rate-limited", "network", "timeout", "unexpected"],
)
async def test_retried_setup_failure_keeps_tokens_and_persists_the_throttle(
    hass: HomeAssistant, error: Exception
):
    """Every retried failure persists the cache: its tokens and the login budget
    and hold-offs the failed run recorded."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="transient_entry",
    )
    entry.add_to_hass(hass)
    await AuthStore(hass, entry.entry_id).async_save(
        AuthCache(openudid="0123456789abcdef", session={"access_token": "kept"})
    )

    def _factory(*args, **kwargs):
        cache = kwargs["auth_cache"]
        instance = MagicMock()

        async def _init():
            cache.throttle["hold_off"] = {"login": 9e12}
            raise error

        instance.init = AsyncMock(side_effect=_init)
        return instance

    with patch("custom_components.robovac_mqtt.EufyLogin", side_effect=_factory):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    saved = await AuthStore(hass, entry.entry_id).async_load()
    assert saved.session == {"access_token": "kept"}
    assert saved.throttle["hold_off"] == {"login": 9e12}


def _ctx(response: object) -> MagicMock:
    ctx = MagicMock()
    if isinstance(response, BaseException):
        ctx.__aenter__ = AsyncMock(side_effect=response)
    else:
        ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _response(status: int, body: object = None, headers: dict | None = None) -> MagicMock:
    response = MagicMock(status=status, headers=headers or {})
    response.json = AsyncMock(return_value=body)
    return response


def _rate_limited_websession(retry_after: str) -> tuple[MagicMock, list[str]]:
    """A websession answering every login with HTTP 429; records each openudid sent."""
    sent: list[str] = []
    response = _response(429, headers={"Retry-After": retry_after})

    def post(_url, **kwargs):
        sent.append(kwargs["headers"]["openudid"])
        return _ctx(response)

    websession = MagicMock()
    websession.post.side_effect = post
    websession.get.side_effect = AssertionError("no authenticated call expected")
    return websession, sent


async def test_rate_limited_first_start_holds_off_and_keeps_the_openudid(
    hass: HomeAssistant,
):
    """HTTP 429 at login starts a persisted hold-off of at least an hour; the
    retry inside it sends nothing, and the openudid is the one already sent."""
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
        left = CloudThrottle(stored.throttle).held_off("requests")
        assert left == pytest.approx(REQUEST_HOLD_OFF, abs=10)

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert len(sent) == 1
    assert (await AuthStore(hass, entry.entry_id).async_load()).openudid == sent[0]


async def test_a_timeout_after_a_login_keeps_the_attempt_counted(hass: HomeAssistant):
    """A raw TimeoutError after the login was sent (here on the MQTT
    credentials) still persists the login against the budget."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="timeout_entry",
    )
    entry.add_to_hass(hass)
    websession = MagicMock()
    websession.post.side_effect = [
        _ctx(_response(200, {"access_token": "tok", "user_id": "u1"})),
        _ctx(TimeoutError()),
    ]
    websession.get.side_effect = [
        _ctx(_response(200, {"user_center_id": "uc", "user_center_token": "t"}))
    ]

    with patch(
        "custom_components.robovac_mqtt.async_get_clientsession", return_value=websession
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert websession.post.call_count == 2
    stored = await AuthStore(hass, entry.entry_id).async_load()
    assert len(CloudThrottle(stored.throttle).recent_logins()) == 1


async def test_a_rejected_cached_session_refused_a_login_is_not_retried(
    hass: HomeAssistant,
):
    """A 401 on the cached run with the login budget spent: the rejected tokens
    are dropped from the store, so the retry stops at the local refusal
    without sending anything."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="rejected_entry",
    )
    entry.add_to_hass(hass)
    now = time.time()
    await AuthStore(hass, entry.entry_id).async_save(
        AuthCache(
            openudid="0123456789abcdef",
            session={"access_token": "rejected", "user_id": "u1"},
            throttle={"logins": [now - 60] * LOGIN_BUDGET},
        )
    )
    websession = MagicMock()
    websession.get.side_effect = lambda *a, **k: _ctx(_response(401))

    with patch(
        "custom_components.robovac_mqtt.async_get_clientsession", return_value=websession
    ), patch.object(EufyLogin, "tuya_login", AsyncMock()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_RETRY
        stored = await AuthStore(hass, entry.entry_id).async_load()
        assert stored.session is None
        assert len(stored.throttle["logins"]) == LOGIN_BUDGET
        cached_calls = websession.get.call_count
        assert cached_calls > 0

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert websession.get.call_count == cached_calls
    websession.post.assert_not_called()


@pytest.mark.parametrize(
    ("mqtt_robot", "mqtt_up", "has_user_center", "credentials", "refusal", "reloads"),
    [
        (True, False, True, None, "hold-off", True),
        (True, False, True, None, "budget", True),
        (True, False, True, {"certificate_pem": "spent"}, "hold-off", True),
        (False, False, True, None, "hold-off", False),
        (True, True, True, None, "hold-off", False),
        (True, False, False, None, "hold-off", False),
        (True, False, True, None, None, False),
    ],
    ids=[
        "left-out",
        "budget-spent",
        "has-credentials",
        "no-mqtt-robot",
        "mqtt-robot-up",
        "fallback-session",
        "login-allowed",
    ],
)
async def test_mqtt_robots_left_out_while_logins_are_refused_reload_once_one_is_allowed(
    hass: HomeAssistant,
    mqtt_robot,
    mqtt_up,
    has_user_center,
    credentials,
    refusal,
    reloads,
):
    """Logins refused at setup: the Tuya robot comes up, the MQTT robot does
    not, and the entry reloads once when a login is allowed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="refused_entry",
    )
    entry.add_to_hass(hass)
    now = time.time()
    state, wait = {
        "hold-off": ({"hold_off": {KIND_LOGIN: now + 600}}, 600),
        "budget": ({"logins": [now - 3600] * LOGIN_BUDGET}, LOGIN_BUDGET_WINDOW - 3600),
        None: ({}, None),
    }[refusal]

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
        login.mqtt_credentials = credentials
        login.has_user_center = has_user_center
        login.throttle = CloudThrottle(state)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert call_later.called is reloads
    if not reloads:
        return
    _hass, delay, action = call_later.call_args.args
    assert wait < delay <= wait + 2
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        action(None)
    reload.assert_called_once_with(entry.entry_id)
    assert await hass.config_entries.async_unload(entry.entry_id)
    call_later.return_value.assert_called_once()


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


async def test_session_replaced_raises_reauth_and_a_repair_issue(hass: HomeAssistant):
    """Another client's logins: reauth (the user's decision), plus a repair
    issue naming the account, not the entry title (device names)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pw"},
        entry_id="replaced_entry",
        title="RoboVac X10 Pro Omni",
    )
    entry.add_to_hass(hass)

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls:
        mock_login_cls.return_value.init = AsyncMock(
            side_effect=EufySessionReplacedError("kicked out")
        )
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "session_replaced_replaced_entry")
    assert issue is not None
    assert issue.translation_placeholders == {"account": "user@example.com"}
    assert any(
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )


async def _set_up_kicked_out(hass: HomeAssistant, entry_id: str) -> MockConfigEntry:
    """An entry whose setup raised the session-replaced repair issue."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: f"{entry_id}@example.com", CONF_PASSWORD: "pw"},
        entry_id=entry_id,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls:
        mock_login_cls.return_value.init = AsyncMock(
            side_effect=EufySessionReplacedError("kicked out")
        )
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_a_successful_setup_clears_the_session_replaced_issue(
    hass: HomeAssistant,
):
    """After a reauth the entry sets up again, and the repair issue goes."""
    entry = await _set_up_kicked_out(hass, "reauthed_entry")
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, "session_replaced_reauthed_entry")

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator",
        side_effect=lambda *a, **k: _mock_coordinator(a[2]["deviceId"]),
    ):
        _mock_login(mock_login_cls, "dev_a")
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert issues.async_get_issue(DOMAIN, "session_replaced_reauthed_entry") is None


async def test_removing_an_entry_deletes_its_repair_issues(hass: HomeAssistant):
    """The session-replaced issue and its devices' segment issues go with the
    entry; another entry's stay."""
    removed = await _set_up_kicked_out(hass, "removed_entry")
    kept = await _set_up_kicked_out(hass, "kept_entry")
    devices = dr.async_get(hass)
    issues = ir.async_get(hass)
    for entry, identifiers in (
        # another integration's identifier on our device names no issue of ours
        (removed, {(DOMAIN, "dev_removed"), ("other_domain", "dev_kept")}),
        (kept, {(DOMAIN, "dev_kept")}),
    ):
        devices.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers=identifiers
        )
        device_id = next(i for d, i in identifiers if d == DOMAIN)
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"segments_changed_{device_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="segments_changed",
        )
    assert issues.async_get_issue(DOMAIN, "session_replaced_removed_entry")

    await hass.config_entries.async_remove(removed.entry_id)
    await hass.async_block_till_done()

    assert issues.async_get_issue(DOMAIN, "session_replaced_removed_entry") is None
    assert issues.async_get_issue(DOMAIN, "segments_changed_dev_removed") is None
    assert issues.async_get_issue(DOMAIN, "session_replaced_kept_entry")
    assert issues.async_get_issue(DOMAIN, "segments_changed_dev_kept")
