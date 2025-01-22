from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor
NONE: Global
PROTO_VERSION: Global

class AppFunction(_message.Message):
    __slots__ = ["multi_maps", "optimization"]
    class MultiMapsFunctionBit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class OptimizationFunctionBit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Module(_message.Message):
        __slots__ = ["options", "version"]
        OPTIONS_FIELD_NUMBER: _ClassVar[int]
        VERSION_FIELD_NUMBER: _ClassVar[int]
        options: int
        version: int
        def __init__(self, version: _Optional[int] = ..., options: _Optional[int] = ...) -> None: ...
    MULTI_MAPS_FIELD_NUMBER: _ClassVar[int]
    OPTIMIZATION_FIELD_NUMBER: _ClassVar[int]
    PATH_HIDE_TYPE: AppFunction.OptimizationFunctionBit
    REMIND_MAP_SAVE: AppFunction.MultiMapsFunctionBit
    multi_maps: AppFunction.Module
    optimization: AppFunction.Module
    def __init__(self, multi_maps: _Optional[_Union[AppFunction.Module, _Mapping]] = ..., optimization: _Optional[_Union[AppFunction.Module, _Mapping]] = ...) -> None: ...

class ProtoInfo(_message.Message):
    __slots__ = ["collect_dust", "continue_clean", "cut_hair", "global_verison", "map_format", "timing"]
    class CollectDustOptionBit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class ContinueCleanOptionBit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class MapFormatOptionBit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class TimingOptionBit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Module(_message.Message):
        __slots__ = ["options", "version"]
        OPTIONS_FIELD_NUMBER: _ClassVar[int]
        VERSION_FIELD_NUMBER: _ClassVar[int]
        options: int
        version: int
        def __init__(self, version: _Optional[int] = ..., options: _Optional[int] = ...) -> None: ...
    COLLECT_DUST_APP_START: ProtoInfo.CollectDustOptionBit
    COLLECT_DUST_FIELD_NUMBER: _ClassVar[int]
    CONTINUE_CLEAN_FIELD_NUMBER: _ClassVar[int]
    CUT_HAIR_FIELD_NUMBER: _ClassVar[int]
    GLOBAL_VERISON_FIELD_NUMBER: _ClassVar[int]
    MAP_FORMAT_ANGLE: ProtoInfo.MapFormatOptionBit
    MAP_FORMAT_DEFAULT_NAME: ProtoInfo.MapFormatOptionBit
    MAP_FORMAT_FIELD_NUMBER: _ClassVar[int]
    MAP_FORMAT_RESERVE_MAP: ProtoInfo.MapFormatOptionBit
    SCHEDULE_ROOMS_CLEAN_CUSTOM: ProtoInfo.TimingOptionBit
    SCHEDULE_SCENE_CLEAN: ProtoInfo.TimingOptionBit
    SMART_CONTINUE_CLEAN: ProtoInfo.ContinueCleanOptionBit
    TIMING_FIELD_NUMBER: _ClassVar[int]
    collect_dust: ProtoInfo.Module
    continue_clean: ProtoInfo.Module
    cut_hair: ProtoInfo.Module
    global_verison: int
    map_format: ProtoInfo.Module
    timing: ProtoInfo.Module
    def __init__(self, global_verison: _Optional[int] = ..., collect_dust: _Optional[_Union[ProtoInfo.Module, _Mapping]] = ..., map_format: _Optional[_Union[ProtoInfo.Module, _Mapping]] = ..., continue_clean: _Optional[_Union[ProtoInfo.Module, _Mapping]] = ..., cut_hair: _Optional[_Union[ProtoInfo.Module, _Mapping]] = ..., timing: _Optional[_Union[ProtoInfo.Module, _Mapping]] = ...) -> None: ...

class Global(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
