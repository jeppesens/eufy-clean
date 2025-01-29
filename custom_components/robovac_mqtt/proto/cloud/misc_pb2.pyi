from typing import ClassVar as _ClassVar
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message

from ...proto.cloud import common_pb2 as _common_pb2

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
