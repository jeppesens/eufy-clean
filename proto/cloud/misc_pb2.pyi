from proto.cloud import common_pb2 as _common_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Battery(_message.Message):
    __slots__ = ["level"]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    level: int
    def __init__(self, level: _Optional[int] = ...) -> None: ...

class Power(_message.Message):
    __slots__ = ["sw"]
    SW_FIELD_NUMBER: _ClassVar[int]
    sw: _common_pb2.Switch
    def __init__(self, sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ...) -> None: ...

class Volume(_message.Message):
    __slots__ = ["value"]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    value: int
    def __init__(self, value: _Optional[int] = ...) -> None: ...
