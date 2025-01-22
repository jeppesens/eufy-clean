from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AnalysisInternalStatus(_message.Message):
    __slots__ = ["motion_state", "robotapp_state"]
    MOTION_STATE_FIELD_NUMBER: _ClassVar[int]
    ROBOTAPP_STATE_FIELD_NUMBER: _ClassVar[int]
    motion_state: str
    robotapp_state: str
    def __init__(self, robotapp_state: _Optional[str] = ..., motion_state: _Optional[str] = ...) -> None: ...

class AnalysisRequest(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class AnalysisResponse(_message.Message):
    __slots__ = ["internal_status", "statistics"]
    INTERNAL_STATUS_FIELD_NUMBER: _ClassVar[int]
    STATISTICS_FIELD_NUMBER: _ClassVar[int]
    internal_status: AnalysisInternalStatus
    statistics: AnalysisStatistics
    def __init__(self, internal_status: _Optional[_Union[AnalysisInternalStatus, _Mapping]] = ..., statistics: _Optional[_Union[AnalysisStatistics, _Mapping]] = ...) -> None: ...

class AnalysisStatistics(_message.Message):
    __slots__ = ["battery_info", "clean", "collect", "ctrl_event", "distribute_event", "gohome", "relocate"]
    class BatteryInfo(_message.Message):
        __slots__ = ["current", "real_level", "show_level", "temperature", "update_time", "voltage"]
        CURRENT_FIELD_NUMBER: _ClassVar[int]
        REAL_LEVEL_FIELD_NUMBER: _ClassVar[int]
        SHOW_LEVEL_FIELD_NUMBER: _ClassVar[int]
        TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
        UPDATE_TIME_FIELD_NUMBER: _ClassVar[int]
        VOLTAGE_FIELD_NUMBER: _ClassVar[int]
        current: int
        real_level: int
        show_level: int
        temperature: _containers.RepeatedScalarFieldContainer[int]
        update_time: int
        voltage: int
        def __init__(self, update_time: _Optional[int] = ..., show_level: _Optional[int] = ..., real_level: _Optional[int] = ..., voltage: _Optional[int] = ..., current: _Optional[int] = ..., temperature: _Optional[_Iterable[int]] = ...) -> None: ...
    class CleanRecord(_message.Message):
        __slots__ = ["clean_area", "clean_id", "clean_time", "end_time", "fail_code", "map_id", "mode", "result", "roll_brush", "room_count", "slam_area", "start_time", "type"]
        class FailCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class RollBrush(_message.Message):
            __slots__ = ["protect_count", "stalled_count"]
            PROTECT_COUNT_FIELD_NUMBER: _ClassVar[int]
            STALLED_COUNT_FIELD_NUMBER: _ClassVar[int]
            protect_count: int
            stalled_count: int
            def __init__(self, protect_count: _Optional[int] = ..., stalled_count: _Optional[int] = ...) -> None: ...
        AUTO_CLEAN: AnalysisStatistics.CleanRecord.Mode
        CLEAN_AREA_FIELD_NUMBER: _ClassVar[int]
        CLEAN_ID_FIELD_NUMBER: _ClassVar[int]
        CLEAN_TIME_FIELD_NUMBER: _ClassVar[int]
        END_TIME_FIELD_NUMBER: _ClassVar[int]
        FAIL_CODE_FIELD_NUMBER: _ClassVar[int]
        FAST_MAPPING: AnalysisStatistics.CleanRecord.Mode
        MANUAL_BREAK: AnalysisStatistics.CleanRecord.FailCode
        MAP_ID_FIELD_NUMBER: _ClassVar[int]
        MODE_FIELD_NUMBER: _ClassVar[int]
        MOP_ONLY: AnalysisStatistics.CleanRecord.Type
        RESULT_FIELD_NUMBER: _ClassVar[int]
        ROBOT_ALERT: AnalysisStatistics.CleanRecord.FailCode
        ROBOT_FAULT: AnalysisStatistics.CleanRecord.FailCode
        ROLL_BRUSH_FIELD_NUMBER: _ClassVar[int]
        ROOM_COUNT_FIELD_NUMBER: _ClassVar[int]
        SELECT_ROOMS_CLEAN: AnalysisStatistics.CleanRecord.Mode
        SELECT_ZONES_CLEAN: AnalysisStatistics.CleanRecord.Mode
        SLAM_AREA_FIELD_NUMBER: _ClassVar[int]
        SPOT_CLEAN: AnalysisStatistics.CleanRecord.Mode
        START_TIME_FIELD_NUMBER: _ClassVar[int]
        SWEEP_AND_MOP: AnalysisStatistics.CleanRecord.Type
        SWEEP_ONLY: AnalysisStatistics.CleanRecord.Type
        TYPE_FIELD_NUMBER: _ClassVar[int]
        UNKNOW: AnalysisStatistics.CleanRecord.FailCode
        clean_area: int
        clean_id: int
        clean_time: int
        end_time: int
        fail_code: AnalysisStatistics.CleanRecord.FailCode
        map_id: int
        mode: AnalysisStatistics.CleanRecord.Mode
        result: bool
        roll_brush: AnalysisStatistics.CleanRecord.RollBrush
        room_count: int
        slam_area: int
        start_time: int
        type: AnalysisStatistics.CleanRecord.Type
        def __init__(self, clean_id: _Optional[int] = ..., result: bool = ..., fail_code: _Optional[_Union[AnalysisStatistics.CleanRecord.FailCode, str]] = ..., mode: _Optional[_Union[AnalysisStatistics.CleanRecord.Mode, str]] = ..., type: _Optional[_Union[AnalysisStatistics.CleanRecord.Type, str]] = ..., start_time: _Optional[int] = ..., end_time: _Optional[int] = ..., clean_time: _Optional[int] = ..., clean_area: _Optional[int] = ..., slam_area: _Optional[int] = ..., map_id: _Optional[int] = ..., room_count: _Optional[int] = ..., roll_brush: _Optional[_Union[AnalysisStatistics.CleanRecord.RollBrush, _Mapping]] = ...) -> None: ...
    class CollectRecord(_message.Message):
        __slots__ = ["clean_id", "result", "start_time"]
        CLEAN_ID_FIELD_NUMBER: _ClassVar[int]
        RESULT_FIELD_NUMBER: _ClassVar[int]
        START_TIME_FIELD_NUMBER: _ClassVar[int]
        clean_id: int
        result: bool
        start_time: int
        def __init__(self, clean_id: _Optional[int] = ..., result: bool = ..., start_time: _Optional[int] = ...) -> None: ...
    class ControlEvent(_message.Message):
        __slots__ = ["clean_id", "source", "timestamp", "type"]
        class Source(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        APP: AnalysisStatistics.ControlEvent.Source
        AUTO_CLEAN: AnalysisStatistics.ControlEvent.Type
        CLEAN_ID_FIELD_NUMBER: _ClassVar[int]
        CLEAN_PAUSE: AnalysisStatistics.ControlEvent.Type
        CLEAN_RESUME: AnalysisStatistics.ControlEvent.Type
        GOHOME: AnalysisStatistics.ControlEvent.Type
        KEY: AnalysisStatistics.ControlEvent.Source
        SOURCE_FIELD_NUMBER: _ClassVar[int]
        SPOT_CLEAN: AnalysisStatistics.ControlEvent.Type
        TIMER: AnalysisStatistics.ControlEvent.Source
        TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
        TYPE_FIELD_NUMBER: _ClassVar[int]
        clean_id: int
        source: AnalysisStatistics.ControlEvent.Source
        timestamp: int
        type: AnalysisStatistics.ControlEvent.Type
        def __init__(self, clean_id: _Optional[int] = ..., type: _Optional[_Union[AnalysisStatistics.ControlEvent.Type, str]] = ..., source: _Optional[_Union[AnalysisStatistics.ControlEvent.Source, str]] = ..., timestamp: _Optional[int] = ...) -> None: ...
    class DistributeEvent(_message.Message):
        __slots__ = ["country_code", "mac", "mode", "result", "sn", "software_version", "timestamp", "token", "uuid"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class Result(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class TimeStamp(_message.Message):
            __slots__ = ["value"]
            VALUE_FIELD_NUMBER: _ClassVar[int]
            value: int
            def __init__(self, value: _Optional[int] = ...) -> None: ...
        AP: AnalysisStatistics.DistributeEvent.Mode
        BLE: AnalysisStatistics.DistributeEvent.Mode
        COUNTRY_CODE_FIELD_NUMBER: _ClassVar[int]
        E_AP_NOT_FOUND: AnalysisStatistics.DistributeEvent.Result
        E_DHCP_ERR: AnalysisStatistics.DistributeEvent.Result
        E_DNS_ERR: AnalysisStatistics.DistributeEvent.Result
        E_GW_ERR: AnalysisStatistics.DistributeEvent.Result
        E_NET_ERR: AnalysisStatistics.DistributeEvent.Result
        E_OK: AnalysisStatistics.DistributeEvent.Result
        E_PASSWD_ERR: AnalysisStatistics.DistributeEvent.Result
        E_SRV_ERR: AnalysisStatistics.DistributeEvent.Result
        MAC_FIELD_NUMBER: _ClassVar[int]
        MODE_FIELD_NUMBER: _ClassVar[int]
        RESULT_FIELD_NUMBER: _ClassVar[int]
        SN_FIELD_NUMBER: _ClassVar[int]
        SOFTWARE_VERSION_FIELD_NUMBER: _ClassVar[int]
        TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
        TOKEN_FIELD_NUMBER: _ClassVar[int]
        UUID_FIELD_NUMBER: _ClassVar[int]
        country_code: str
        mac: str
        mode: AnalysisStatistics.DistributeEvent.Mode
        result: AnalysisStatistics.DistributeEvent.Result
        sn: str
        software_version: str
        timestamp: AnalysisStatistics.DistributeEvent.TimeStamp
        token: str
        uuid: str
        def __init__(self, timestamp: _Optional[_Union[AnalysisStatistics.DistributeEvent.TimeStamp, _Mapping]] = ..., mode: _Optional[_Union[AnalysisStatistics.DistributeEvent.Mode, str]] = ..., result: _Optional[_Union[AnalysisStatistics.DistributeEvent.Result, str]] = ..., software_version: _Optional[str] = ..., sn: _Optional[str] = ..., mac: _Optional[str] = ..., uuid: _Optional[str] = ..., country_code: _Optional[str] = ..., token: _Optional[str] = ...) -> None: ...
    class GoHomeRecord(_message.Message):
        __slots__ = ["clean_id", "end_time", "fail_code", "power_level", "result", "start_time"]
        class FailCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        CLEAN_ID_FIELD_NUMBER: _ClassVar[int]
        END_TIME_FIELD_NUMBER: _ClassVar[int]
        ENTER_HOME_FAIL: AnalysisStatistics.GoHomeRecord.FailCode
        FAIL_CODE_FIELD_NUMBER: _ClassVar[int]
        MANUAL_BREAK: AnalysisStatistics.GoHomeRecord.FailCode
        NAVIGATE_FAIL: AnalysisStatistics.GoHomeRecord.FailCode
        POWER_LEVEL_FIELD_NUMBER: _ClassVar[int]
        RESULT_FIELD_NUMBER: _ClassVar[int]
        START_TIME_FIELD_NUMBER: _ClassVar[int]
        UNKNOW: AnalysisStatistics.GoHomeRecord.FailCode
        clean_id: int
        end_time: int
        fail_code: AnalysisStatistics.GoHomeRecord.FailCode
        power_level: int
        result: bool
        start_time: int
        def __init__(self, clean_id: _Optional[int] = ..., result: bool = ..., fail_code: _Optional[_Union[AnalysisStatistics.GoHomeRecord.FailCode, str]] = ..., power_level: _Optional[int] = ..., start_time: _Optional[int] = ..., end_time: _Optional[int] = ...) -> None: ...
    class RelocateRecord(_message.Message):
        __slots__ = ["clean_id", "end_time", "map_count", "result", "start_time"]
        CLEAN_ID_FIELD_NUMBER: _ClassVar[int]
        END_TIME_FIELD_NUMBER: _ClassVar[int]
        MAP_COUNT_FIELD_NUMBER: _ClassVar[int]
        RESULT_FIELD_NUMBER: _ClassVar[int]
        START_TIME_FIELD_NUMBER: _ClassVar[int]
        clean_id: int
        end_time: int
        map_count: int
        result: bool
        start_time: int
        def __init__(self, clean_id: _Optional[int] = ..., result: bool = ..., map_count: _Optional[int] = ..., start_time: _Optional[int] = ..., end_time: _Optional[int] = ...) -> None: ...
    BATTERY_INFO_FIELD_NUMBER: _ClassVar[int]
    CLEAN_FIELD_NUMBER: _ClassVar[int]
    COLLECT_FIELD_NUMBER: _ClassVar[int]
    CTRL_EVENT_FIELD_NUMBER: _ClassVar[int]
    DISTRIBUTE_EVENT_FIELD_NUMBER: _ClassVar[int]
    GOHOME_FIELD_NUMBER: _ClassVar[int]
    RELOCATE_FIELD_NUMBER: _ClassVar[int]
    battery_info: AnalysisStatistics.BatteryInfo
    clean: AnalysisStatistics.CleanRecord
    collect: AnalysisStatistics.CollectRecord
    ctrl_event: AnalysisStatistics.ControlEvent
    distribute_event: AnalysisStatistics.DistributeEvent
    gohome: AnalysisStatistics.GoHomeRecord
    relocate: AnalysisStatistics.RelocateRecord
    def __init__(self, clean: _Optional[_Union[AnalysisStatistics.CleanRecord, _Mapping]] = ..., gohome: _Optional[_Union[AnalysisStatistics.GoHomeRecord, _Mapping]] = ..., relocate: _Optional[_Union[AnalysisStatistics.RelocateRecord, _Mapping]] = ..., collect: _Optional[_Union[AnalysisStatistics.CollectRecord, _Mapping]] = ..., ctrl_event: _Optional[_Union[AnalysisStatistics.ControlEvent, _Mapping]] = ..., distribute_event: _Optional[_Union[AnalysisStatistics.DistributeEvent, _Mapping]] = ..., battery_info: _Optional[_Union[AnalysisStatistics.BatteryInfo, _Mapping]] = ...) -> None: ...
