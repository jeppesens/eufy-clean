from typing import ClassVar as _ClassVar
from typing import Iterable as _Iterable
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

from ...proto.cloud import clean_param_pb2 as _clean_param_pb2
from ...proto.cloud import common_pb2 as _common_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class TimerInfo(_message.Message):
    __slots__ = ["action", "addition", "desc", "id", "status"]
    class Action(_message.Message):
        __slots__ = ["precondition", "sche_auto_clean", "sche_cruise", "sche_rooms_clean", "sche_scene_clean", "type"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class Precondition(_message.Message):
            __slots__ = []
            def __init__(self) -> None: ...
        class ScheduleAutoClean(_message.Message):
            __slots__ = ["general", "mode"]
            class General(_message.Message):
                __slots__ = ["clean_extent", "clean_type", "fan", "mop_mode", "smart_mode_sw"]
                CLEAN_EXTENT_FIELD_NUMBER: _ClassVar[int]
                CLEAN_TYPE_FIELD_NUMBER: _ClassVar[int]
                FAN_FIELD_NUMBER: _ClassVar[int]
                MOP_MODE_FIELD_NUMBER: _ClassVar[int]
                SMART_MODE_SW_FIELD_NUMBER: _ClassVar[int]
                clean_extent: _clean_param_pb2.CleanExtent
                clean_type: _clean_param_pb2.CleanType
                fan: _clean_param_pb2.Fan
                mop_mode: _clean_param_pb2.MopMode
                smart_mode_sw: _common_pb2.Switch
                def __init__(self, fan: _Optional[_Union[_clean_param_pb2.Fan, _Mapping]] = ..., mop_mode: _Optional[_Union[_clean_param_pb2.MopMode, _Mapping]] = ..., clean_type: _Optional[_Union[_clean_param_pb2.CleanType, _Mapping]] = ..., clean_extent: _Optional[_Union[_clean_param_pb2.CleanExtent, _Mapping]] = ..., smart_mode_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ...) -> None: ...
            GENERAL_FIELD_NUMBER: _ClassVar[int]
            MODE_FIELD_NUMBER: _ClassVar[int]
            general: TimerInfo.Action.ScheduleAutoClean.General
            mode: TimerInfo.Action.Mode
            def __init__(self, mode: _Optional[_Union[TimerInfo.Action.Mode, str]] = ..., general: _Optional[_Union[TimerInfo.Action.ScheduleAutoClean.General, _Mapping]] = ...) -> None: ...
        class ScheduleCruise(_message.Message):
            __slots__ = ["map_id"]
            MAP_ID_FIELD_NUMBER: _ClassVar[int]
            map_id: int
            def __init__(self, map_id: _Optional[int] = ...) -> None: ...
        class ScheduleRoomsClean(_message.Message):
            __slots__ = ["custom", "general", "mode"]
            class Custom(_message.Message):
                __slots__ = ["map_id", "rooms", "smart_mode_sw"]
                class Room(_message.Message):
                    __slots__ = ["clean_extent", "clean_times", "clean_type", "fan", "id", "mop_mode", "order"]
                    CLEAN_EXTENT_FIELD_NUMBER: _ClassVar[int]
                    CLEAN_TIMES_FIELD_NUMBER: _ClassVar[int]
                    CLEAN_TYPE_FIELD_NUMBER: _ClassVar[int]
                    FAN_FIELD_NUMBER: _ClassVar[int]
                    ID_FIELD_NUMBER: _ClassVar[int]
                    MOP_MODE_FIELD_NUMBER: _ClassVar[int]
                    ORDER_FIELD_NUMBER: _ClassVar[int]
                    clean_extent: _clean_param_pb2.CleanExtent
                    clean_times: int
                    clean_type: _clean_param_pb2.CleanType
                    fan: _clean_param_pb2.Fan
                    id: int
                    mop_mode: _clean_param_pb2.MopMode
                    order: int
                    def __init__(self, id: _Optional[int] = ..., order: _Optional[int] = ..., clean_type: _Optional[_Union[_clean_param_pb2.CleanType, _Mapping]] = ..., fan: _Optional[_Union[_clean_param_pb2.Fan, _Mapping]] = ..., mop_mode: _Optional[_Union[_clean_param_pb2.MopMode, _Mapping]] = ..., clean_extent: _Optional[_Union[_clean_param_pb2.CleanExtent, _Mapping]] = ..., clean_times: _Optional[int] = ...) -> None: ...
                MAP_ID_FIELD_NUMBER: _ClassVar[int]
                ROOMS_FIELD_NUMBER: _ClassVar[int]
                SMART_MODE_SW_FIELD_NUMBER: _ClassVar[int]
                map_id: int
                rooms: _containers.RepeatedCompositeFieldContainer[TimerInfo.Action.ScheduleRoomsClean.Custom.Room]
                smart_mode_sw: _common_pb2.Switch
                def __init__(self, map_id: _Optional[int] = ..., smart_mode_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., rooms: _Optional[_Iterable[_Union[TimerInfo.Action.ScheduleRoomsClean.Custom.Room, _Mapping]]] = ...) -> None: ...
            class General(_message.Message):
                __slots__ = ["clean_extent", "clean_type", "fan", "map_id", "mop_mode", "rooms"]
                class Room(_message.Message):
                    __slots__ = ["id", "order"]
                    ID_FIELD_NUMBER: _ClassVar[int]
                    ORDER_FIELD_NUMBER: _ClassVar[int]
                    id: int
                    order: int
                    def __init__(self, id: _Optional[int] = ..., order: _Optional[int] = ...) -> None: ...
                CLEAN_EXTENT_FIELD_NUMBER: _ClassVar[int]
                CLEAN_TYPE_FIELD_NUMBER: _ClassVar[int]
                FAN_FIELD_NUMBER: _ClassVar[int]
                MAP_ID_FIELD_NUMBER: _ClassVar[int]
                MOP_MODE_FIELD_NUMBER: _ClassVar[int]
                ROOMS_FIELD_NUMBER: _ClassVar[int]
                clean_extent: _clean_param_pb2.CleanExtent
                clean_type: _clean_param_pb2.CleanType
                fan: _clean_param_pb2.Fan
                map_id: int
                mop_mode: _clean_param_pb2.MopMode
                rooms: _containers.RepeatedCompositeFieldContainer[TimerInfo.Action.ScheduleRoomsClean.General.Room]
                def __init__(self, map_id: _Optional[int] = ..., fan: _Optional[_Union[_clean_param_pb2.Fan, _Mapping]] = ..., mop_mode: _Optional[_Union[_clean_param_pb2.MopMode, _Mapping]] = ..., clean_type: _Optional[_Union[_clean_param_pb2.CleanType, _Mapping]] = ..., clean_extent: _Optional[_Union[_clean_param_pb2.CleanExtent, _Mapping]] = ..., rooms: _Optional[_Iterable[_Union[TimerInfo.Action.ScheduleRoomsClean.General.Room, _Mapping]]] = ...) -> None: ...
            CUSTOM_FIELD_NUMBER: _ClassVar[int]
            GENERAL_FIELD_NUMBER: _ClassVar[int]
            MODE_FIELD_NUMBER: _ClassVar[int]
            custom: TimerInfo.Action.ScheduleRoomsClean.Custom
            general: TimerInfo.Action.ScheduleRoomsClean.General
            mode: TimerInfo.Action.Mode
            def __init__(self, mode: _Optional[_Union[TimerInfo.Action.Mode, str]] = ..., general: _Optional[_Union[TimerInfo.Action.ScheduleRoomsClean.General, _Mapping]] = ..., custom: _Optional[_Union[TimerInfo.Action.ScheduleRoomsClean.Custom, _Mapping]] = ...) -> None: ...
        class ScheduleSceneClean(_message.Message):
            __slots__ = ["scene_id", "scene_name"]
            SCENE_ID_FIELD_NUMBER: _ClassVar[int]
            SCENE_NAME_FIELD_NUMBER: _ClassVar[int]
            scene_id: int
            scene_name: str
            def __init__(self, scene_id: _Optional[int] = ..., scene_name: _Optional[str] = ...) -> None: ...
        CUSTOMIZE: TimerInfo.Action.Mode
        GENERAL: TimerInfo.Action.Mode
        PRECONDITION_FIELD_NUMBER: _ClassVar[int]
        SCHEDULE_AUTO_CLEAN: TimerInfo.Action.Type
        SCHEDULE_CRUISE: TimerInfo.Action.Type
        SCHEDULE_ROOMS_CLEAN: TimerInfo.Action.Type
        SCHEDULE_SCENE_CLEAN: TimerInfo.Action.Type
        SCHE_AUTO_CLEAN_FIELD_NUMBER: _ClassVar[int]
        SCHE_CRUISE_FIELD_NUMBER: _ClassVar[int]
        SCHE_ROOMS_CLEAN_FIELD_NUMBER: _ClassVar[int]
        SCHE_SCENE_CLEAN_FIELD_NUMBER: _ClassVar[int]
        TYPE_FIELD_NUMBER: _ClassVar[int]
        precondition: TimerInfo.Action.Precondition
        sche_auto_clean: TimerInfo.Action.ScheduleAutoClean
        sche_cruise: TimerInfo.Action.ScheduleCruise
        sche_rooms_clean: TimerInfo.Action.ScheduleRoomsClean
        sche_scene_clean: TimerInfo.Action.ScheduleSceneClean
        type: TimerInfo.Action.Type
        def __init__(self, type: _Optional[_Union[TimerInfo.Action.Type, str]] = ..., precondition: _Optional[_Union[TimerInfo.Action.Precondition, _Mapping]] = ..., sche_auto_clean: _Optional[_Union[TimerInfo.Action.ScheduleAutoClean, _Mapping]] = ..., sche_rooms_clean: _Optional[_Union[TimerInfo.Action.ScheduleRoomsClean, _Mapping]] = ..., sche_cruise: _Optional[_Union[TimerInfo.Action.ScheduleCruise, _Mapping]] = ..., sche_scene_clean: _Optional[_Union[TimerInfo.Action.ScheduleSceneClean, _Mapping]] = ...) -> None: ...
    class Addition(_message.Message):
        __slots__ = ["create_time", "create_user_id", "renew_time", "renew_user_id"]
        CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
        CREATE_USER_ID_FIELD_NUMBER: _ClassVar[int]
        RENEW_TIME_FIELD_NUMBER: _ClassVar[int]
        RENEW_USER_ID_FIELD_NUMBER: _ClassVar[int]
        create_time: int
        create_user_id: str
        renew_time: int
        renew_user_id: str
        def __init__(self, create_time: _Optional[int] = ..., create_user_id: _Optional[str] = ..., renew_time: _Optional[int] = ..., renew_user_id: _Optional[str] = ...) -> None: ...
    class Desc(_message.Message):
        __slots__ = ["cycle", "timing", "trigger"]
        class Trigger(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class Cycle(_message.Message):
            __slots__ = ["week_bits"]
            WEEK_BITS_FIELD_NUMBER: _ClassVar[int]
            week_bits: int
            def __init__(self, week_bits: _Optional[int] = ...) -> None: ...
        class Timing(_message.Message):
            __slots__ = ["hours", "minutes", "summer", "user_tz"]
            HOURS_FIELD_NUMBER: _ClassVar[int]
            MINUTES_FIELD_NUMBER: _ClassVar[int]
            SUMMER_FIELD_NUMBER: _ClassVar[int]
            USER_TZ_FIELD_NUMBER: _ClassVar[int]
            hours: int
            minutes: int
            summer: bool
            user_tz: int
            def __init__(self, user_tz: _Optional[int] = ..., summer: bool = ..., hours: _Optional[int] = ..., minutes: _Optional[int] = ...) -> None: ...
        CYCLE: TimerInfo.Desc.Trigger
        CYCLE_FIELD_NUMBER: _ClassVar[int]
        SINGLE: TimerInfo.Desc.Trigger
        TIMING_FIELD_NUMBER: _ClassVar[int]
        TRIGGER_FIELD_NUMBER: _ClassVar[int]
        cycle: TimerInfo.Desc.Cycle
        timing: TimerInfo.Desc.Timing
        trigger: TimerInfo.Desc.Trigger
        def __init__(self, trigger: _Optional[_Union[TimerInfo.Desc.Trigger, str]] = ..., timing: _Optional[_Union[TimerInfo.Desc.Timing, _Mapping]] = ..., cycle: _Optional[_Union[TimerInfo.Desc.Cycle, _Mapping]] = ...) -> None: ...
    class Id(_message.Message):
        __slots__ = ["value"]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        value: int
        def __init__(self, value: _Optional[int] = ...) -> None: ...
    class Status(_message.Message):
        __slots__ = ["opened", "valid"]
        OPENED_FIELD_NUMBER: _ClassVar[int]
        VALID_FIELD_NUMBER: _ClassVar[int]
        opened: bool
        valid: bool
        def __init__(self, valid: bool = ..., opened: bool = ...) -> None: ...
    ACTION_FIELD_NUMBER: _ClassVar[int]
    ADDITION_FIELD_NUMBER: _ClassVar[int]
    DESC_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    action: TimerInfo.Action
    addition: TimerInfo.Addition
    desc: TimerInfo.Desc
    id: TimerInfo.Id
    status: TimerInfo.Status
    def __init__(self, id: _Optional[_Union[TimerInfo.Id, _Mapping]] = ..., status: _Optional[_Union[TimerInfo.Status, _Mapping]] = ..., desc: _Optional[_Union[TimerInfo.Desc, _Mapping]] = ..., addition: _Optional[_Union[TimerInfo.Addition, _Mapping]] = ..., action: _Optional[_Union[TimerInfo.Action, _Mapping]] = ...) -> None: ...

class TimerRequest(_message.Message):
    __slots__ = ["method", "seq", "timer"]
    class Method(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    ADD: TimerRequest.Method
    CLOSE: TimerRequest.Method
    DEFAULT: TimerRequest.Method
    DELETE: TimerRequest.Method
    IGNORE_ONCE: TimerRequest.Method
    INQUIRY: TimerRequest.Method
    METHOD_FIELD_NUMBER: _ClassVar[int]
    MOTIFY: TimerRequest.Method
    OPEN: TimerRequest.Method
    SEQ_FIELD_NUMBER: _ClassVar[int]
    TIMER_FIELD_NUMBER: _ClassVar[int]
    method: TimerRequest.Method
    seq: int
    timer: TimerInfo
    def __init__(self, method: _Optional[_Union[TimerRequest.Method, str]] = ..., seq: _Optional[int] = ..., timer: _Optional[_Union[TimerInfo, _Mapping]] = ...) -> None: ...

class TimerResponse(_message.Message):
    __slots__ = ["method", "result", "seq", "timers"]
    class Result(_message.Message):
        __slots__ = ["err_code", "value"]
        class Value(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        ERR_CODE_FIELD_NUMBER: _ClassVar[int]
        FAILED: TimerResponse.Result.Value
        SUCCESS: TimerResponse.Result.Value
        VALUE_FIELD_NUMBER: _ClassVar[int]
        err_code: int
        value: TimerResponse.Result.Value
        def __init__(self, value: _Optional[_Union[TimerResponse.Result.Value, str]] = ..., err_code: _Optional[int] = ...) -> None: ...
    METHOD_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    TIMERS_FIELD_NUMBER: _ClassVar[int]
    method: TimerRequest.Method
    result: TimerResponse.Result
    seq: int
    timers: _containers.RepeatedCompositeFieldContainer[TimerInfo]
    def __init__(self, method: _Optional[_Union[TimerRequest.Method, str]] = ..., seq: _Optional[int] = ..., result: _Optional[_Union[TimerResponse.Result, _Mapping]] = ..., timers: _Optional[_Iterable[_Union[TimerInfo, _Mapping]]] = ...) -> None: ...
