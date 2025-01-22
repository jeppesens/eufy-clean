from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ConsumableRequest(_message.Message):
    __slots__ = ["reset_types"]
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    DIRTY_WATERFILTER: ConsumableRequest.Type
    DIRTY_WATERTANK: ConsumableRequest.Type
    DUSTBAG: ConsumableRequest.Type
    FILTER_MESH: ConsumableRequest.Type
    MOP: ConsumableRequest.Type
    RESET_TYPES_FIELD_NUMBER: _ClassVar[int]
    ROLLING_BRUSH: ConsumableRequest.Type
    SCRAPE: ConsumableRequest.Type
    SENSOR: ConsumableRequest.Type
    SIDE_BRUSH: ConsumableRequest.Type
    reset_types: _containers.RepeatedScalarFieldContainer[ConsumableRequest.Type]
    def __init__(self, reset_types: _Optional[_Iterable[_Union[ConsumableRequest.Type, str]]] = ...) -> None: ...

class ConsumableResponse(_message.Message):
    __slots__ = ["runtime"]
    RUNTIME_FIELD_NUMBER: _ClassVar[int]
    runtime: ConsumableRuntime
    def __init__(self, runtime: _Optional[_Union[ConsumableRuntime, _Mapping]] = ...) -> None: ...

class ConsumableRuntime(_message.Message):
    __slots__ = ["dirty_waterfilter", "dirty_watertank", "dustbag", "filter_mesh", "last_time", "mop", "rolling_brush", "scrape", "sensor", "side_brush"]
    class Duration(_message.Message):
        __slots__ = ["duration"]
        DURATION_FIELD_NUMBER: _ClassVar[int]
        duration: int
        def __init__(self, duration: _Optional[int] = ...) -> None: ...
    DIRTY_WATERFILTER_FIELD_NUMBER: _ClassVar[int]
    DIRTY_WATERTANK_FIELD_NUMBER: _ClassVar[int]
    DUSTBAG_FIELD_NUMBER: _ClassVar[int]
    FILTER_MESH_FIELD_NUMBER: _ClassVar[int]
    LAST_TIME_FIELD_NUMBER: _ClassVar[int]
    MOP_FIELD_NUMBER: _ClassVar[int]
    ROLLING_BRUSH_FIELD_NUMBER: _ClassVar[int]
    SCRAPE_FIELD_NUMBER: _ClassVar[int]
    SENSOR_FIELD_NUMBER: _ClassVar[int]
    SIDE_BRUSH_FIELD_NUMBER: _ClassVar[int]
    dirty_waterfilter: ConsumableRuntime.Duration
    dirty_watertank: ConsumableRuntime.Duration
    dustbag: ConsumableRuntime.Duration
    filter_mesh: ConsumableRuntime.Duration
    last_time: int
    mop: ConsumableRuntime.Duration
    rolling_brush: ConsumableRuntime.Duration
    scrape: ConsumableRuntime.Duration
    sensor: ConsumableRuntime.Duration
    side_brush: ConsumableRuntime.Duration
    def __init__(self, side_brush: _Optional[_Union[ConsumableRuntime.Duration, _Mapping]] = ..., rolling_brush: _Optional[_Union[ConsumableRuntime.Duration, _Mapping]] = ..., filter_mesh: _Optional[_Union[ConsumableRuntime.Duration, _Mapping]] = ..., scrape: _Optional[_Union[ConsumableRuntime.Duration, _Mapping]] = ..., sensor: _Optional[_Union[ConsumableRuntime.Duration, _Mapping]] = ..., mop: _Optional[_Union[ConsumableRuntime.Duration, _Mapping]] = ..., dustbag: _Optional[_Union[ConsumableRuntime.Duration, _Mapping]] = ..., dirty_watertank: _Optional[_Union[ConsumableRuntime.Duration, _Mapping]] = ..., dirty_waterfilter: _Optional[_Union[ConsumableRuntime.Duration, _Mapping]] = ..., last_time: _Optional[int] = ...) -> None: ...
