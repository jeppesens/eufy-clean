# pylint: disable=redefined-outer-name
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from custom_components.robovac_mqtt.const import DOMAIN


@pytest.fixture
def mock_login_fixture():
    with patch("custom_components.robovac_mqtt.config_flow.EufyLogin") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.init = AsyncMock()
        mock_instance.mqtt_devices = [{"deviceName": "Test Vac", "deviceId": "test123"}]
        yield mock_cls


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
