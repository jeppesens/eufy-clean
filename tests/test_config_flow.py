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
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.robovac_mqtt.const import (
        CONF_MAP_MAX_PX,
        CONF_NOTIFY_MOBILE_SERVICE,
    )

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
    import voluptuous_serialize
    import homeassistant.helpers.config_validation as cv

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
