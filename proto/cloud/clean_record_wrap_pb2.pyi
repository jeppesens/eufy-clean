from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class CleanRecordWrap(_message.Message):
    __slots__ = ["data", "desc", "id"]
    DATA_FIELD_NUMBER: _ClassVar[int]
    DESC_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    desc: bytes
    id: int
    def __init__(self, id: _Optional[int] = ..., desc: _Optional[bytes] = ..., data: _Optional[bytes] = ...) -> None: ...
