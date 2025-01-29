from typing import ClassVar as _ClassVar
from typing import Iterable as _Iterable
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers

from ...proto.cloud import common_pb2 as _common_pb2
from ...proto.cloud import stream_pb2 as _stream_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class MapEntity(_message.Message):
    __slots__ = ["desc", "pixel"]
    class Desc(_message.Message):
        __slots__ = ["docks", "height", "map_id", "origin", "resolution", "width"]
        DOCKS_FIELD_NUMBER: _ClassVar[int]
        HEIGHT_FIELD_NUMBER: _ClassVar[int]
        MAP_ID_FIELD_NUMBER: _ClassVar[int]
        ORIGIN_FIELD_NUMBER: _ClassVar[int]
        RESOLUTION_FIELD_NUMBER: _ClassVar[int]
        WIDTH_FIELD_NUMBER: _ClassVar[int]
        docks: _containers.RepeatedCompositeFieldContainer[_common_pb2.Pose]
        height: int
        map_id: int
        origin: _common_pb2.Point
        resolution: int
        width: int
        def __init__(self, map_id: _Optional[int] = ..., width: _Optional[int] = ..., height: _Optional[int] = ..., resolution: _Optional[int] = ..., origin: _Optional[_Union[_common_pb2.Point, _Mapping]] = ..., docks: _Optional[_Iterable[_Union[_common_pb2.Pose, _Mapping]]] = ...) -> None: ...
    DESC_FIELD_NUMBER: _ClassVar[int]
    PIXEL_FIELD_NUMBER: _ClassVar[int]
    desc: MapEntity.Desc
    pixel: bytes
    def __init__(self, desc: _Optional[_Union[MapEntity.Desc, _Mapping]] = ..., pixel: _Optional[bytes] = ...) -> None: ...

class MapExtras(_message.Message):
    __slots__ = ["name", "restricted_zone", "room_outline", "room_params"]
    NAME_FIELD_NUMBER: _ClassVar[int]
    RESTRICTED_ZONE_FIELD_NUMBER: _ClassVar[int]
    ROOM_OUTLINE_FIELD_NUMBER: _ClassVar[int]
    ROOM_PARAMS_FIELD_NUMBER: _ClassVar[int]
    name: str
    restricted_zone: _stream_pb2.RestrictedZone
    room_outline: _containers.RepeatedCompositeFieldContainer[_stream_pb2.RoomOutline]
    room_params: _containers.RepeatedCompositeFieldContainer[_stream_pb2.RoomParams]
    def __init__(self, name: _Optional[str] = ..., room_outline: _Optional[_Iterable[_Union[_stream_pb2.RoomOutline, _Mapping]]] = ..., room_params: _Optional[_Iterable[_Union[_stream_pb2.RoomParams, _Mapping]]] = ..., restricted_zone: _Optional[_Union[_stream_pb2.RestrictedZone, _Mapping]] = ...) -> None: ...
