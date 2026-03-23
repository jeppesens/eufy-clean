# pylint: disable=redefined-outer-name
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.robovac_mqtt.const import DOMAIN


@pytest.fixture
def mock_login_fixture():
    with patch("custom_components.robovac_mqtt.api.http.EufyHTTPClient.login") as mock:
        mock.return_value = {"session": "dummy"}
        yield mock


async def test_duplicate_entry(hass: HomeAssistant, mock_login_fixture):
    """Test that duplicate entries are rejected."""

    # 1. Create the first entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "test@example.com", CONF_PASSWORD: "password"},
    )
    assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY

    # Mock that the first entry is set up
    with patch("custom_components.robovac_mqtt.async_setup_entry", return_value=True):
        await hass.async_block_till_done()

    # 2. Try to create the same entry again
    result3 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result4 = await hass.config_entries.flow.async_configure(
        result3["flow_id"],
        {CONF_USERNAME: "test@example.com", CONF_PASSWORD: "password"},
    )

    # Expectation: ABORT (already configured)
    assert result4["type"] == data_entry_flow.FlowResultType.ABORT
    assert result4["reason"] == "already_configured"


async def test_config_flow_entry_data_contains_vacs(
    hass: HomeAssistant, mock_login_fixture
):
    """Test that created config entry data includes VACS key."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "newuser@example.com", CONF_PASSWORD: "pass123"},
    )
    assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY

    # Verify the entry data includes the VACS key
    entry_data = result2["result"].data
    assert CONF_USERNAME in entry_data
    assert CONF_PASSWORD in entry_data
    assert "vacs" in entry_data


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
