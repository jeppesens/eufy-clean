from typing import ClassVar as _ClassVar
from typing import Iterable as _Iterable
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

from ...proto.cloud import common_pb2 as _common_pb2
from ...proto.cloud import stream_pb2 as _stream_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class CompleteMap(_message.Message):
    __slots__ = ["docks", "is_new_map", "map", "map_height", "map_id", "map_stable", "map_width", "name", "obstacles", "origin", "releases", "restricted_zones", "room_outline", "room_params", "temporary_data"]
    DOCKS_FIELD_NUMBER: _ClassVar[int]
    IS_NEW_MAP_FIELD_NUMBER: _ClassVar[int]
    MAP_FIELD_NUMBER: _ClassVar[int]
    MAP_HEIGHT_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    MAP_STABLE_FIELD_NUMBER: _ClassVar[int]
    MAP_WIDTH_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    OBSTACLES_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    RESTRICTED_ZONES_FIELD_NUMBER: _ClassVar[int]
    ROOM_OUTLINE_FIELD_NUMBER: _ClassVar[int]
    ROOM_PARAMS_FIELD_NUMBER: _ClassVar[int]
    TEMPORARY_DATA_FIELD_NUMBER: _ClassVar[int]
    docks: _containers.RepeatedCompositeFieldContainer[_common_pb2.Pose]
    is_new_map: int
    map: MapPixels
    map_height: int
    map_id: int
    map_stable: bool
    map_width: int
    name: str
    obstacles: _stream_pb2.ObstacleInfo
    origin: _common_pb2.Point
    releases: int
    restricted_zones: _stream_pb2.RestrictedZone
    room_outline: MapPixels
    room_params: _stream_pb2.RoomParams
    temporary_data: _stream_pb2.TemporaryData
    def __init__(self, releases: _Optional[int] = ..., map_id: _Optional[int] = ..., map_stable: bool = ..., map_width: _Optional[int] = ..., map_height: _Optional[int] = ..., origin: _Optional[_Union[_common_pb2.Point, _Mapping]] = ..., docks: _Optional[_Iterable[_Union[_common_pb2.Pose, _Mapping]]] = ..., map: _Optional[_Union[MapPixels, _Mapping]] = ..., room_outline: _Optional[_Union[MapPixels, _Mapping]] = ..., obstacles: _Optional[_Union[_stream_pb2.ObstacleInfo, _Mapping]] = ..., restricted_zones: _Optional[_Union[_stream_pb2.RestrictedZone, _Mapping]] = ..., room_params: _Optional[_Union[_stream_pb2.RoomParams, _Mapping]] = ..., temporary_data: _Optional[_Union[_stream_pb2.TemporaryData, _Mapping]] = ..., is_new_map: _Optional[int] = ..., name: _Optional[str] = ...) -> None: ...

class CompletePath(_message.Message):
    __slots__ = ["path", "path_lz4len"]
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    FOLLOW: CompletePath.State
    GOHOME: CompletePath.Type
    MOP: CompletePath.Type
    NAVI: CompletePath.Type
    NEW: CompletePath.State
    PATH_FIELD_NUMBER: _ClassVar[int]
    PATH_LZ4LEN_FIELD_NUMBER: _ClassVar[int]
    SWEEP: CompletePath.Type
    SWEEP_MOP: CompletePath.Type
    path: bytes
    path_lz4len: int
    def __init__(self, path: _Optional[bytes] = ..., path_lz4len: _Optional[int] = ...) -> None: ...

class MapChannelMsg(_message.Message):
    __slots__ = ["map_info", "multi_map_response", "type"]
    class MsgType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    MAP_INFO: MapChannelMsg.MsgType
    MAP_INFO_FIELD_NUMBER: _ClassVar[int]
    MULTI_MAP_RESPONSE: MapChannelMsg.MsgType
    MULTI_MAP_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    map_info: MapInfo
    multi_map_response: bytes
    type: MapChannelMsg.MsgType
    def __init__(self, type: _Optional[_Union[MapChannelMsg.MsgType, str]] = ..., map_info: _Optional[_Union[MapInfo, _Mapping]] = ..., multi_map_response: _Optional[bytes] = ...) -> None: ...

class MapInfo(_message.Message):
    __slots__ = ["cruise_data", "docks", "is_new_map", "map_height", "map_id", "map_stable", "map_width", "msg_type", "name", "obstacles", "origin", "pixels", "releases", "restricted_zones", "room_params", "temporary_data"]
    class MapMsgType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    CRUISE_DATA: MapInfo.MapMsgType
    CRUISE_DATA_FIELD_NUMBER: _ClassVar[int]
    DOCKS_FIELD_NUMBER: _ClassVar[int]
    IS_NEW_MAP_FIELD_NUMBER: _ClassVar[int]
    MAP_HEIGHT_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    MAP_REALTIME: MapInfo.MapMsgType
    MAP_ROOMOUTLINE: MapInfo.MapMsgType
    MAP_STABLE_FIELD_NUMBER: _ClassVar[int]
    MAP_WIDTH_FIELD_NUMBER: _ClassVar[int]
    MSG_TYPE_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    OBSTACLES_FIELD_NUMBER: _ClassVar[int]
    OBSTACLE_INFO: MapInfo.MapMsgType
    ORIGIN_FIELD_NUMBER: _ClassVar[int]
    PIXELS_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    RESTRICTED_ZONES_FIELD_NUMBER: _ClassVar[int]
    RESTRICT_ZONES: MapInfo.MapMsgType
    ROOM_PARAMS: MapInfo.MapMsgType
    ROOM_PARAMS_FIELD_NUMBER: _ClassVar[int]
    TEMPORARY_DATA: MapInfo.MapMsgType
    TEMPORARY_DATA_FIELD_NUMBER: _ClassVar[int]
    cruise_data: _stream_pb2.CruiseData
    docks: _containers.RepeatedCompositeFieldContainer[_common_pb2.Pose]
    is_new_map: int
    map_height: int
    map_id: int
    map_stable: bool
    map_width: int
    msg_type: MapInfo.MapMsgType
    name: str
    obstacles: _stream_pb2.ObstacleInfo
    origin: _common_pb2.Point
    pixels: MapPixels
    releases: int
    restricted_zones: _stream_pb2.RestrictedZone
    room_params: _stream_pb2.RoomParams
    temporary_data: _stream_pb2.TemporaryData
    def __init__(self, releases: _Optional[int] = ..., map_id: _Optional[int] = ..., map_stable: bool = ..., map_width: _Optional[int] = ..., map_height: _Optional[int] = ..., origin: _Optional[_Union[_common_pb2.Point, _Mapping]] = ..., docks: _Optional[_Iterable[_Union[_common_pb2.Pose, _Mapping]]] = ..., msg_type: _Optional[_Union[MapInfo.MapMsgType, str]] = ..., pixels: _Optional[_Union[MapPixels, _Mapping]] = ..., obstacles: _Optional[_Union[_stream_pb2.ObstacleInfo, _Mapping]] = ..., restricted_zones: _Optional[_Union[_stream_pb2.RestrictedZone, _Mapping]] = ..., room_params: _Optional[_Union[_stream_pb2.RoomParams, _Mapping]] = ..., cruise_data: _Optional[_Union[_stream_pb2.CruiseData, _Mapping]] = ..., temporary_data: _Optional[_Union[_stream_pb2.TemporaryData, _Mapping]] = ..., is_new_map: _Optional[int] = ..., name: _Optional[str] = ...) -> None: ...

class MapPixels(_message.Message):
    __slots__ = ["pixel_size", "pixels"]
    PIXELS_FIELD_NUMBER: _ClassVar[int]
    PIXEL_SIZE_FIELD_NUMBER: _ClassVar[int]
    pixel_size: int
    pixels: bytes
    def __init__(self, pixels: _Optional[bytes] = ..., pixel_size: _Optional[int] = ...) -> None: ...
