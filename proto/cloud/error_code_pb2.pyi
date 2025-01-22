from proto.cloud import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ErrorCode(_message.Message):
    __slots__ = ["battery", "error", "last_time", "new_code", "obstacle_reminder", "setting", "warn"]
    class Battery(_message.Message):
        __slots__ = ["restored"]
        RESTORED_FIELD_NUMBER: _ClassVar[int]
        restored: bool
        def __init__(self, restored: bool = ...) -> None: ...
    class NewCode(_message.Message):
        __slots__ = ["error", "warn"]
        ERROR_FIELD_NUMBER: _ClassVar[int]
        WARN_FIELD_NUMBER: _ClassVar[int]
        error: _containers.RepeatedScalarFieldContainer[int]
        warn: _containers.RepeatedScalarFieldContainer[int]
        def __init__(self, error: _Optional[_Iterable[int]] = ..., warn: _Optional[_Iterable[int]] = ...) -> None: ...
    class ObstacleReminder(_message.Message):
        __slots__ = ["accuracy", "map_id", "photo_id", "point", "type"]
        class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        ACCURACY_FIELD_NUMBER: _ClassVar[int]
        MAP_ID_FIELD_NUMBER: _ClassVar[int]
        PHOTO_ID_FIELD_NUMBER: _ClassVar[int]
        POINT_FIELD_NUMBER: _ClassVar[int]
        POOP: ErrorCode.ObstacleReminder.Type
        TYPE_FIELD_NUMBER: _ClassVar[int]
        accuracy: int
        map_id: int
        photo_id: str
        point: _common_pb2.Point
        type: ErrorCode.ObstacleReminder.Type
        def __init__(self, type: _Optional[_Union[ErrorCode.ObstacleReminder.Type, str]] = ..., photo_id: _Optional[str] = ..., accuracy: _Optional[int] = ..., map_id: _Optional[int] = ..., point: _Optional[_Union[_common_pb2.Point, _Mapping]] = ...) -> None: ...
    BATTERY_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    LAST_TIME_FIELD_NUMBER: _ClassVar[int]
    NEW_CODE_FIELD_NUMBER: _ClassVar[int]
    OBSTACLE_REMINDER_FIELD_NUMBER: _ClassVar[int]
    SETTING_FIELD_NUMBER: _ClassVar[int]
    WARN_FIELD_NUMBER: _ClassVar[int]
    battery: ErrorCode.Battery
    error: _containers.RepeatedScalarFieldContainer[int]
    last_time: int
    new_code: ErrorCode.NewCode
    obstacle_reminder: _containers.RepeatedCompositeFieldContainer[ErrorCode.ObstacleReminder]
    setting: ErrorSetting
    warn: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, last_time: _Optional[int] = ..., error: _Optional[_Iterable[int]] = ..., warn: _Optional[_Iterable[int]] = ..., setting: _Optional[_Union[ErrorSetting, _Mapping]] = ..., new_code: _Optional[_Union[ErrorCode.NewCode, _Mapping]] = ..., battery: _Optional[_Union[ErrorCode.Battery, _Mapping]] = ..., obstacle_reminder: _Optional[_Iterable[_Union[ErrorCode.ObstacleReminder, _Mapping]]] = ...) -> None: ...

class ErrorSetting(_message.Message):
    __slots__ = ["obstacle_reminder_mask", "warn_mask"]
    OBSTACLE_REMINDER_MASK_FIELD_NUMBER: _ClassVar[int]
    WARN_MASK_FIELD_NUMBER: _ClassVar[int]
    obstacle_reminder_mask: _containers.RepeatedScalarFieldContainer[str]
    warn_mask: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, warn_mask: _Optional[_Iterable[int]] = ..., obstacle_reminder_mask: _Optional[_Iterable[str]] = ...) -> None: ...

class PromptCode(_message.Message):
    __slots__ = ["last_time", "value"]
    LAST_TIME_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    last_time: int
    value: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, last_time: _Optional[int] = ..., value: _Optional[_Iterable[int]] = ...) -> None: ...
