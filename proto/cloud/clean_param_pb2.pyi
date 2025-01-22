from proto.cloud import common_pb2 as _common_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CleanCarpet(_message.Message):
    __slots__ = ["strategy"]
    class Strategy(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    AUTO_RAISE: CleanCarpet.Strategy
    AVOID: CleanCarpet.Strategy
    IGNORE: CleanCarpet.Strategy
    STRATEGY_FIELD_NUMBER: _ClassVar[int]
    strategy: CleanCarpet.Strategy
    def __init__(self, strategy: _Optional[_Union[CleanCarpet.Strategy, str]] = ...) -> None: ...

class CleanExtent(_message.Message):
    __slots__ = ["value"]
    class Value(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    NARROW: CleanExtent.Value
    NORMAL: CleanExtent.Value
    QUICK: CleanExtent.Value
    VALUE_FIELD_NUMBER: _ClassVar[int]
    value: CleanExtent.Value
    def __init__(self, value: _Optional[_Union[CleanExtent.Value, str]] = ...) -> None: ...

class CleanParam(_message.Message):
    __slots__ = ["clean_carpet", "clean_extent", "clean_times", "clean_type", "fan", "mop_mode", "smart_mode_sw"]
    CLEAN_CARPET_FIELD_NUMBER: _ClassVar[int]
    CLEAN_EXTENT_FIELD_NUMBER: _ClassVar[int]
    CLEAN_TIMES_FIELD_NUMBER: _ClassVar[int]
    CLEAN_TYPE_FIELD_NUMBER: _ClassVar[int]
    FAN_FIELD_NUMBER: _ClassVar[int]
    MOP_MODE_FIELD_NUMBER: _ClassVar[int]
    SMART_MODE_SW_FIELD_NUMBER: _ClassVar[int]
    clean_carpet: CleanCarpet
    clean_extent: CleanExtent
    clean_times: int
    clean_type: CleanType
    fan: Fan
    mop_mode: MopMode
    smart_mode_sw: _common_pb2.Switch
    def __init__(self, clean_type: _Optional[_Union[CleanType, _Mapping]] = ..., clean_carpet: _Optional[_Union[CleanCarpet, _Mapping]] = ..., clean_extent: _Optional[_Union[CleanExtent, _Mapping]] = ..., mop_mode: _Optional[_Union[MopMode, _Mapping]] = ..., smart_mode_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., fan: _Optional[_Union[Fan, _Mapping]] = ..., clean_times: _Optional[int] = ...) -> None: ...

class CleanParamRequest(_message.Message):
    __slots__ = ["area_clean_param", "clean_param"]
    AREA_CLEAN_PARAM_FIELD_NUMBER: _ClassVar[int]
    CLEAN_PARAM_FIELD_NUMBER: _ClassVar[int]
    area_clean_param: CleanParam
    clean_param: CleanParam
    def __init__(self, clean_param: _Optional[_Union[CleanParam, _Mapping]] = ..., area_clean_param: _Optional[_Union[CleanParam, _Mapping]] = ...) -> None: ...

class CleanParamResponse(_message.Message):
    __slots__ = ["area_clean_param", "clean_param", "clean_times", "running_clean_param"]
    AREA_CLEAN_PARAM_FIELD_NUMBER: _ClassVar[int]
    CLEAN_PARAM_FIELD_NUMBER: _ClassVar[int]
    CLEAN_TIMES_FIELD_NUMBER: _ClassVar[int]
    RUNNING_CLEAN_PARAM_FIELD_NUMBER: _ClassVar[int]
    area_clean_param: CleanParam
    clean_param: CleanParam
    clean_times: CleanTimes
    running_clean_param: CleanParam
    def __init__(self, clean_param: _Optional[_Union[CleanParam, _Mapping]] = ..., clean_times: _Optional[_Union[CleanTimes, _Mapping]] = ..., area_clean_param: _Optional[_Union[CleanParam, _Mapping]] = ..., running_clean_param: _Optional[_Union[CleanParam, _Mapping]] = ...) -> None: ...

class CleanTimes(_message.Message):
    __slots__ = ["auto_clean", "select_rooms", "spot_clean"]
    AUTO_CLEAN_FIELD_NUMBER: _ClassVar[int]
    SELECT_ROOMS_FIELD_NUMBER: _ClassVar[int]
    SPOT_CLEAN_FIELD_NUMBER: _ClassVar[int]
    auto_clean: int
    select_rooms: int
    spot_clean: int
    def __init__(self, auto_clean: _Optional[int] = ..., select_rooms: _Optional[int] = ..., spot_clean: _Optional[int] = ...) -> None: ...

class CleanType(_message.Message):
    __slots__ = ["value"]
    class Value(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    MOP_ONLY: CleanType.Value
    SWEEP_AND_MOP: CleanType.Value
    SWEEP_ONLY: CleanType.Value
    SWEEP_THEN_MOP: CleanType.Value
    VALUE_FIELD_NUMBER: _ClassVar[int]
    value: CleanType.Value
    def __init__(self, value: _Optional[_Union[CleanType.Value, str]] = ...) -> None: ...

class Fan(_message.Message):
    __slots__ = ["suction"]
    class Suction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    MAX: Fan.Suction
    MAX_PLUS: Fan.Suction
    QUIET: Fan.Suction
    STANDARD: Fan.Suction
    SUCTION_FIELD_NUMBER: _ClassVar[int]
    TURBO: Fan.Suction
    suction: Fan.Suction
    def __init__(self, suction: _Optional[_Union[Fan.Suction, str]] = ...) -> None: ...

class MopMode(_message.Message):
    __slots__ = ["corner_clean", "level"]
    class CornerClean(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Level(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    CORNER_CLEAN_FIELD_NUMBER: _ClassVar[int]
    DEEP: MopMode.CornerClean
    HIGH: MopMode.Level
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    LOW: MopMode.Level
    MIDDLE: MopMode.Level
    NORMAL: MopMode.CornerClean
    corner_clean: MopMode.CornerClean
    level: MopMode.Level
    def __init__(self, level: _Optional[_Union[MopMode.Level, str]] = ..., corner_clean: _Optional[_Union[MopMode.CornerClean, str]] = ...) -> None: ...
