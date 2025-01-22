from proto.cloud import ble_pb2 as _ble_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SocketBroadcast(_message.Message):
    __slots__ = ["device_sn", "is_bind", "user_id"]
    DEVICE_SN_FIELD_NUMBER: _ClassVar[int]
    IS_BIND_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    device_sn: str
    is_bind: bool
    user_id: str
    def __init__(self, is_bind: bool = ..., device_sn: _Optional[str] = ..., user_id: _Optional[str] = ...) -> None: ...

class SocketTransData(_message.Message):
    __slots__ = ["distribute", "type"]
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    DISTRIBUTE_FIELD_NUMBER: _ClassVar[int]
    E_DISTRIBUTE: SocketTransData.Type
    E_DP: SocketTransData.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    distribute: _ble_pb2.BtAppMsg.Distribute
    type: SocketTransData.Type
    def __init__(self, type: _Optional[_Union[SocketTransData.Type, str]] = ..., distribute: _Optional[_Union[_ble_pb2.BtAppMsg.Distribute, _Mapping]] = ...) -> None: ...

class SocketVerify(_message.Message):
    __slots__ = ["device_sn", "random", "user_id"]
    DEVICE_SN_FIELD_NUMBER: _ClassVar[int]
    RANDOM_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    device_sn: str
    random: str
    user_id: str
    def __init__(self, random: _Optional[str] = ..., device_sn: _Optional[str] = ..., user_id: _Optional[str] = ...) -> None: ...
