# pylint: disable=redefined-outer-name
from unittest.mock import AsyncMock, MagicMock, patch

import homeassistant.helpers.config_validation as cv
import pytest
import voluptuous_serialize
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.robovac_mqtt.const import (
    CONF_LOCAL_DEVICES,
    CONF_LOCAL_HOST,
    CONF_LOCAL_VERSION,
    CONF_MAP_MAX_PX,
    CONF_NOTIFY_MOBILE_SERVICE,
    CONF_ROOM_NAMES,
    DOMAIN,
)


@pytest.fixture
def mock_login_fixture():
    with patch("custom_components.robovac_mqtt.config_flow.EufyLogin") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.init = AsyncMock()
        mock_instance.mqtt_devices = [{"deviceName": "Test Vac", "deviceId": "test123"}]
        yield mock_cls


async def test_duplicate_entry(hass: HomeAssistant, mock_login_fixture):
    """Test that duplicate entries are rejected."""

    with patch("custom_components.robovac_mqtt.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "test@example.com", CONF_PASSWORD: "password"},
        )
        assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

        result3 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result4 = await hass.config_entries.flow.async_configure(
            result3["flow_id"],
            {CONF_USERNAME: "test@example.com", CONF_PASSWORD: "password"},
        )

    assert result4["type"] == data_entry_flow.FlowResultType.ABORT
    assert result4["reason"] == "already_configured"


async def test_config_flow_entry_data_contains_vacs(
    hass: HomeAssistant, mock_login_fixture
):
    """Test that created config entry data includes VACS key."""
    with patch("custom_components.robovac_mqtt.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "newuser@example.com", CONF_PASSWORD: "pass123"},
        )
        assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

    entry_data = result2["result"].data
    assert CONF_USERNAME in entry_data
    assert CONF_PASSWORD in entry_data
    assert "vacs" in entry_data


async def test_options_flow_blank_mobile_service(hass: HomeAssistant):
    """Options can be saved when the mobile notify service is left blank.

    An unselected SelectSelector dropdown submits ``None``; this must not
    raise "expected str" validation errors when only the map size changes.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Vac",
        data={CONF_USERNAME: "u@example.com", CONF_PASSWORD: "p", "vacs": {}},
        options={},
        unique_id="u@example.com",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.FORM

    # The HTTP layer serializes the form schema for the frontend; a function
    # (e.g. a coercion lambda) in the schema makes that raise -> 500 on load.
    voluptuous_serialize.convert(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_MAP_MAX_PX: "1024", CONF_NOTIFY_MOBILE_SERVICE: None},
    )
    assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_NOTIFY_MOBILE_SERVICE] == ""
    assert result2["data"][CONF_MAP_MAX_PX] == "1024"


def _fake_coordinator(device_id: str, *, local_key: str | None = None):
    """Build a minimal coordinator stand-in for the options flow."""
    coord = MagicMock()
    coord.device_id = device_id
    coord.device_name = f"Vac {device_id}"
    coord.device_model = "T1234"
    coord._local_key = local_key
    return coord


def _register_coordinators(hass, entry, coordinators):
    """Wire coordinators into hass.data the way __init__ does at setup."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinators": coordinators
    }


async def test_options_flow_preserves_override_for_unloaded_device(
    hass: HomeAssistant,
):
    """B2: a stored override for a device that failed to load (not in the
    running coordinators) must survive a save instead of being dropped."""
    stored = {
        # This device is currently loaded and editable.
        "loaded_dev": {
            CONF_LOCAL_HOST: "192.168.1.50",
            CONF_LOCAL_VERSION: 3.3,
            CONF_ROOM_NAMES: {1: "Lounge"},
        },
        # This device was offline at load time -> no coordinator. Its
        # override must NOT be wiped when the user saves the form.
        "offline_dev": {
            CONF_LOCAL_HOST: "192.168.1.99",
            CONF_LOCAL_VERSION: 3.4,
            CONF_ROOM_NAMES: {2: "Kitchen"},
        },
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Vac",
        data={CONF_USERNAME: "u@example.com", CONF_PASSWORD: "p", "vacs": {}},
        options={CONF_LOCAL_DEVICES: stored},
        unique_id="u@example.com",
    )
    entry.add_to_hass(hass)
    # Only the loaded device has a running coordinator.
    _register_coordinators(
        hass, entry, [_fake_coordinator("loaded_dev", local_key="abc")]
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.FORM

    # Resubmit the loaded device's host unchanged; touch nothing else.
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NOTIFY_MOBILE_SERVICE: None,
            "loaded_dev__host": "192.168.1.50",
            "loaded_dev__version": 3.3,
            "loaded_dev__rooms": "1: Lounge",
        },
    )
    assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    saved = result2["data"][CONF_LOCAL_DEVICES]
    # The offline device's override is untouched.
    assert saved["offline_dev"] == stored["offline_dev"]
    # The loaded device kept its host/rooms.
    assert saved["loaded_dev"][CONF_LOCAL_HOST] == "192.168.1.50"
    assert saved["loaded_dev"][CONF_ROOM_NAMES] == {1: "Lounge"}


async def test_options_flow_invalid_host_shows_error_and_does_not_save(
    hass: HomeAssistant,
):
    """N5: a malformed host (scheme/port) must surface an ``invalid_host``
    error on its field and must not persist."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Vac",
        data={CONF_USERNAME: "u@example.com", CONF_PASSWORD: "p", "vacs": {}},
        options={},
        unique_id="u@example.com",
    )
    entry.add_to_hass(hass)
    _register_coordinators(
        hass, entry, [_fake_coordinator("loaded_dev", local_key="abc")]
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.FORM

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NOTIFY_MOBILE_SERVICE: None,
            "loaded_dev__host": "1.2.3.4:6668",
            "loaded_dev__version": 3.3,
            "loaded_dev__rooms": "",
        },
    )
    # Form re-shown with the field-scoped error; nothing saved.
    assert result2["type"] == data_entry_flow.FlowResultType.FORM
    assert result2["errors"]["loaded_dev__host"] == "invalid_host"
    assert entry.options.get(CONF_LOCAL_DEVICES, {}) == {}


# ── Reauth flow ───────────────────────────────────────────────────


async def test_reauth_shows_password_form(hass: HomeAssistant):
    """Reauth step should show a password-only form."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "old_pass"},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"


async def test_reauth_success_updates_entry(hass: HomeAssistant, mock_login_fixture):
    """Successful reauth should update the entry password and abort."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "old_pass",
            "vacs": {},
        },
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    with patch("custom_components.robovac_mqtt.async_setup_entry", return_value=True):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new_pass"},
        )
        await hass.async_block_till_done()

    assert result2["type"] == data_entry_flow.FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new_pass"


async def test_reauth_invalid_credentials_shows_error(hass: HomeAssistant):
    """Failed reauth should re-show the form with an error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "old_pass"},
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)

    with patch(
        "custom_components.robovac_mqtt.api.http.EufyHTTPClient.login",
        return_value={},
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "wrong_pass"},
        )

    assert result2["type"] == data_entry_flow.FlowResultType.FORM
    assert result2["errors"]["base"] == "invalid_auth"


# ── Reconfigure flow ──────────────────────────────────────────────


async def test_reconfigure_shows_form(hass: HomeAssistant):
    """Reconfigure should show form with current username."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "pass",
            "vacs": {},
        },
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "reconfigure"


async def test_reconfigure_success(hass: HomeAssistant, mock_login_fixture):
    """Successful reconfigure updates the password."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "old_pass",
            "vacs": {},
        },
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)

    with patch("custom_components.robovac_mqtt.async_setup_entry", return_value=True):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "new_pass"},
        )
        await hass.async_block_till_done()

    assert result2["type"] == data_entry_flow.FlowResultType.ABORT
    assert entry.data[CONF_PASSWORD] == "new_pass"


async def test_reconfigure_username_mismatch(hass: HomeAssistant):
    """Changing username in reconfigure should show error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "pass",
            "vacs": {},
        },
        unique_id="user@example.com",
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "different@example.com", CONF_PASSWORD: "pass"},
    )

    assert result2["type"] == data_entry_flow.FlowResultType.FORM
    assert result2["errors"][CONF_USERNAME] == "username_mismatch"
