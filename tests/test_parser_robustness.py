"""Regression tests: unknown firmware enum values and private data in parser logs."""

import logging
from typing import cast

from custom_components.robovac_mqtt.api import parser
from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.const import DPS_MAP
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.app_device_info_pb2 import DeviceInfo
from custom_components.robovac_mqtt.proto.cloud.clean_param_pb2 import (
    CleanParam,
    CleanParamResponse,
)
from custom_components.robovac_mqtt.proto.cloud.work_status_pb2 import WorkStatus
from custom_components.robovac_mqtt.utils import encode_message


def _work_status(trigger_source: int) -> str:
    ws = WorkStatus(state=WorkStatus.CLEANING)
    # An out-of-table source is the point: the stub types it as the enum.
    ws.trigger.source = cast(WorkStatus.Trigger.Source, trigger_source)
    ws.mode.value = WorkStatus.Mode.SELECT_ROOM
    return encode_message(ws)


def test_unknown_trigger_source_keeps_parsing_work_status(caplog):
    """A trigger source newer than the table must not drop the rest of DPS 153."""
    parser._UNKNOWN_ENUM_VALUES.clear()
    with caplog.at_level(logging.DEBUG, logger=parser.__name__):
        state, _ = update_state(VacuumState(), {DPS_MAP["WORK_STATUS"]: _work_status(250)})
        update_state(state, {DPS_MAP["WORK_STATUS"]: _work_status(250)})

    # The mode-based fallback after the trigger ran, so parsing carried on.
    assert state.trigger_source == "app"
    assert state.work_mode != VacuumState().work_mode
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert sum("Unknown Trigger.Source value 250" in r.message for r in caplog.records) == 1


def test_unknown_clean_type_and_mop_level_keep_other_params(caplog):
    """Unknown CleanType / MopMode.level values fall back; fan speed still parses."""
    parser._UNKNOWN_ENUM_VALUES.clear()
    param = CleanParam()
    param.clean_type.value = 77
    param.mop_mode.level = 66
    param.fan.suction = 1
    encoded = encode_message(CleanParamResponse(clean_param=param))

    with caplog.at_level(logging.DEBUG, logger=parser.__name__):
        state, _ = update_state(VacuumState(), {DPS_MAP["CLEANING_PARAMETERS"]: encoded})

    assert state.cleaning_mode == "Vacuum"
    assert state.mop_water_level == "Medium"
    assert state.fan_speed == "Standard"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_device_info_debug_log_omits_private_fields(caplog):
    """wifi name/IP, MAC, serial and user id never reach a debug log."""
    info = DeviceInfo(
        product_name="eufy Test Model",
        video_sn="SNTEST0000000001",
        device_mac="02:00:00:00:00:01",
        wifi_name="ExampleHomeWifi",
        wifi_ip="192.168.1.23",
        last_user_id="user-0000-example",
    )
    with caplog.at_level(logging.DEBUG, logger=parser.__name__):
        state, _ = update_state(VacuumState(), {DPS_MAP["MAP_MANAGE"]: encode_message(info)})

    assert state.wifi_ssid == "ExampleHomeWifi"  # still parsed into state
    assert "eufy Test Model" in caplog.text
    for secret in (
        "SNTEST0000000001", "02:00:00:00:00:01", "ExampleHomeWifi",
        "192.168.1.23", "user-0000-example",
    ):
        assert secret not in caplog.text
