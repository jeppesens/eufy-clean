from proto.cloud import stream_pb2 as _stream_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ObstacleInfoWrap(_message.Message):
    __slots__ = ["obstacle_info"]
    OBSTACLE_INFO_FIELD_NUMBER: _ClassVar[int]
    obstacle_info: _containers.RepeatedCompositeFieldContainer[_stream_pb2.ObstacleInfo]
    def __init__(self, obstacle_info: _Optional[_Iterable[_Union[_stream_pb2.ObstacleInfo, _Mapping]]] = ...) -> None: ...

class RoomParamsWrap(_message.Message):
    __slots__ = ["room_params"]
    ROOM_PARAMS_FIELD_NUMBER: _ClassVar[int]
    room_params: _containers.RepeatedCompositeFieldContainer[_stream_pb2.RoomParams]
    def __init__(self, room_params: _Optional[_Iterable[_Union[_stream_pb2.RoomParams, _Mapping]]] = ...) -> None: ...
