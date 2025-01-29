from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class KeepAliveRequest(_message.Message):
    __slots__ = ["force_sync", "timestamp"]
    FORCE_SYNC_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    force_sync: bool
    timestamp: int
    def __init__(self, timestamp: _Optional[int] = ..., force_sync: bool = ...) -> None: ...
