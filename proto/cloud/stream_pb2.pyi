from proto.cloud import common_pb2 as _common_pb2
from proto.cloud import clean_param_pb2 as _clean_param_pb2
from proto.cloud import control_pb2 as _control_pb2
from proto.cloud import scene_pb2 as _scene_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CruiseData(_message.Message):
    __slots__ = ["cruise_data", "map_id", "releases"]
    class ProcessData(_message.Message):
        __slots__ = ["photo_id", "points"]
        PHOTO_ID_FIELD_NUMBER: _ClassVar[int]
        POINTS_FIELD_NUMBER: _ClassVar[int]
        photo_id: _containers.RepeatedScalarFieldContainer[str]
        points: _common_pb2.Point
        def __init__(self, points: _Optional[_Union[_common_pb2.Point, _Mapping]] = ..., photo_id: _Optional[_Iterable[str]] = ...) -> None: ...
    CRUISE_DATA_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    cruise_data: _containers.RepeatedCompositeFieldContainer[CruiseData.ProcessData]
    map_id: int
    releases: int
    def __init__(self, cruise_data: _Optional[_Iterable[_Union[CruiseData.ProcessData, _Mapping]]] = ..., map_id: _Optional[int] = ..., releases: _Optional[int] = ...) -> None: ...

class DynamicData(_message.Message):
    __slots__ = ["cur_pose"]
    CUR_POSE_FIELD_NUMBER: _ClassVar[int]
    cur_pose: _common_pb2.Pose
    def __init__(self, cur_pose: _Optional[_Union[_common_pb2.Pose, _Mapping]] = ...) -> None: ...

class Map(_message.Message):
    __slots__ = ["frame", "id", "index", "info", "map_id", "name", "pixel_size", "pixels", "releases", "seq"]
    class Frame(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class PixelValue(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Index(_message.Message):
        __slots__ = ["value"]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        value: int
        def __init__(self, value: _Optional[int] = ...) -> None: ...
    CARPET: Map.PixelValue
    FRAME_FIELD_NUMBER: _ClassVar[int]
    FREE: Map.PixelValue
    I: Map.Frame
    ID_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    INFO_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    OBSTACLE: Map.PixelValue
    P: Map.Frame
    PIXELS_FIELD_NUMBER: _ClassVar[int]
    PIXEL_SIZE_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    UNKNOW: Map.PixelValue
    frame: Map.Frame
    id: int
    index: Map.Index
    info: MapInfo
    map_id: int
    name: str
    pixel_size: int
    pixels: bytes
    releases: int
    seq: int
    def __init__(self, map_id: _Optional[int] = ..., seq: _Optional[int] = ..., frame: _Optional[_Union[Map.Frame, str]] = ..., pixels: _Optional[bytes] = ..., pixel_size: _Optional[int] = ..., info: _Optional[_Union[MapInfo, _Mapping]] = ..., name: _Optional[str] = ..., id: _Optional[int] = ..., releases: _Optional[int] = ..., index: _Optional[_Union[Map.Index, _Mapping]] = ...) -> None: ...

class MapBackup(_message.Message):
    __slots__ = ["desc", "map", "restricted_zone", "room_params", "rooms"]
    DESC_FIELD_NUMBER: _ClassVar[int]
    MAP_FIELD_NUMBER: _ClassVar[int]
    RESTRICTED_ZONE_FIELD_NUMBER: _ClassVar[int]
    ROOMS_FIELD_NUMBER: _ClassVar[int]
    ROOM_PARAMS_FIELD_NUMBER: _ClassVar[int]
    desc: MapDescription
    map: Map
    restricted_zone: RestrictedZone
    room_params: RoomParams
    rooms: RoomOutline
    def __init__(self, desc: _Optional[_Union[MapDescription, _Mapping]] = ..., map: _Optional[_Union[Map, _Mapping]] = ..., rooms: _Optional[_Union[RoomOutline, _Mapping]] = ..., room_params: _Optional[_Union[RoomParams, _Mapping]] = ..., restricted_zone: _Optional[_Union[RestrictedZone, _Mapping]] = ...) -> None: ...

class MapDescription(_message.Message):
    __slots__ = ["create_cause", "create_time", "last_time", "map_id", "name", "releases"]
    CREATE_CAUSE_FIELD_NUMBER: _ClassVar[int]
    CREATE_TIME_FIELD_NUMBER: _ClassVar[int]
    LAST_TIME_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    create_cause: int
    create_time: int
    last_time: int
    map_id: int
    name: str
    releases: int
    def __init__(self, name: _Optional[str] = ..., create_cause: _Optional[int] = ..., create_time: _Optional[int] = ..., last_time: _Optional[int] = ..., map_id: _Optional[int] = ..., releases: _Optional[int] = ...) -> None: ...

class MapInfo(_message.Message):
    __slots__ = ["angle", "docks", "docks_v2", "height", "map_id", "origin", "resolution", "seq", "type", "width"]
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Dock(_message.Message):
        __slots__ = ["pose", "type"]
        class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        ADAPTER: MapInfo.Dock.Type
        POSE_FIELD_NUMBER: _ClassVar[int]
        STATION: MapInfo.Dock.Type
        TYPE_FIELD_NUMBER: _ClassVar[int]
        pose: _common_pb2.Pose
        type: MapInfo.Dock.Type
        def __init__(self, type: _Optional[_Union[MapInfo.Dock.Type, str]] = ..., pose: _Optional[_Union[_common_pb2.Pose, _Mapping]] = ...) -> None: ...
    ANGLE_FIELD_NUMBER: _ClassVar[int]
    DOCKS_FIELD_NUMBER: _ClassVar[int]
    DOCKS_V2_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE: MapInfo.Type
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    INCOMPLETE: MapInfo.Type
    LIST_FULL: MapInfo.Type
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_FIELD_NUMBER: _ClassVar[int]
    RESOLUTION_FIELD_NUMBER: _ClassVar[int]
    ROUGH: MapInfo.Type
    SEQ_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    WIDTH_FIELD_NUMBER: _ClassVar[int]
    angle: int
    docks: _containers.RepeatedCompositeFieldContainer[_common_pb2.Pose]
    docks_v2: _containers.RepeatedCompositeFieldContainer[MapInfo.Dock]
    height: int
    map_id: int
    origin: _common_pb2.Point
    resolution: int
    seq: int
    type: MapInfo.Type
    width: int
    def __init__(self, map_id: _Optional[int] = ..., width: _Optional[int] = ..., height: _Optional[int] = ..., resolution: _Optional[int] = ..., origin: _Optional[_Union[_common_pb2.Point, _Mapping]] = ..., docks: _Optional[_Iterable[_Union[_common_pb2.Pose, _Mapping]]] = ..., type: _Optional[_Union[MapInfo.Type, str]] = ..., seq: _Optional[int] = ..., angle: _Optional[int] = ..., docks_v2: _Optional[_Iterable[_Union[MapInfo.Dock, _Mapping]]] = ...) -> None: ...

class Metadata(_message.Message):
    __slots__ = ["chan_ids", "versions"]
    class ChanIds(_message.Message):
        __slots__ = ["cruise_data", "dynamic_data", "map_data", "map_info", "obstacle_info", "path", "restricted_zone", "room_outline", "room_params", "temporary_data"]
        CRUISE_DATA_FIELD_NUMBER: _ClassVar[int]
        DYNAMIC_DATA_FIELD_NUMBER: _ClassVar[int]
        MAP_DATA_FIELD_NUMBER: _ClassVar[int]
        MAP_INFO_FIELD_NUMBER: _ClassVar[int]
        OBSTACLE_INFO_FIELD_NUMBER: _ClassVar[int]
        PATH_FIELD_NUMBER: _ClassVar[int]
        RESTRICTED_ZONE_FIELD_NUMBER: _ClassVar[int]
        ROOM_OUTLINE_FIELD_NUMBER: _ClassVar[int]
        ROOM_PARAMS_FIELD_NUMBER: _ClassVar[int]
        TEMPORARY_DATA_FIELD_NUMBER: _ClassVar[int]
        cruise_data: int
        dynamic_data: int
        map_data: int
        map_info: int
        obstacle_info: int
        path: int
        restricted_zone: int
        room_outline: int
        room_params: int
        temporary_data: int
        def __init__(self, map_info: _Optional[int] = ..., path: _Optional[int] = ..., room_outline: _Optional[int] = ..., room_params: _Optional[int] = ..., restricted_zone: _Optional[int] = ..., dynamic_data: _Optional[int] = ..., temporary_data: _Optional[int] = ..., obstacle_info: _Optional[int] = ..., map_data: _Optional[int] = ..., cruise_data: _Optional[int] = ...) -> None: ...
    class Versions(_message.Message):
        __slots__ = ["map_data"]
        MAP_DATA_FIELD_NUMBER: _ClassVar[int]
        map_data: int
        def __init__(self, map_data: _Optional[int] = ...) -> None: ...
    CHAN_IDS_FIELD_NUMBER: _ClassVar[int]
    VERSIONS_FIELD_NUMBER: _ClassVar[int]
    chan_ids: Metadata.ChanIds
    versions: Metadata.Versions
    def __init__(self, versions: _Optional[_Union[Metadata.Versions, _Mapping]] = ..., chan_ids: _Optional[_Union[Metadata.ChanIds, _Mapping]] = ...) -> None: ...

class ObstacleInfo(_message.Message):
    __slots__ = ["map_id", "obstacles", "releases"]
    class Obstacle(_message.Message):
        __slots__ = ["accuracy", "bitmap", "object_type", "photo_id", "show_points", "show_type", "theta", "valid"]
        class ShowType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class Bitmap(_message.Message):
            __slots__ = ["data", "data_len", "height", "ref_point", "width"]
            DATA_FIELD_NUMBER: _ClassVar[int]
            DATA_LEN_FIELD_NUMBER: _ClassVar[int]
            HEIGHT_FIELD_NUMBER: _ClassVar[int]
            REF_POINT_FIELD_NUMBER: _ClassVar[int]
            WIDTH_FIELD_NUMBER: _ClassVar[int]
            data: bytes
            data_len: int
            height: int
            ref_point: _common_pb2.Point
            width: int
            def __init__(self, ref_point: _Optional[_Union[_common_pb2.Point, _Mapping]] = ..., width: _Optional[int] = ..., height: _Optional[int] = ..., data_len: _Optional[int] = ..., data: _Optional[bytes] = ...) -> None: ...
        class Valid(_message.Message):
            __slots__ = ["value"]
            VALUE_FIELD_NUMBER: _ClassVar[int]
            value: bool
            def __init__(self, value: bool = ...) -> None: ...
        ACCURACY_FIELD_NUMBER: _ClassVar[int]
        BITMAP: ObstacleInfo.Obstacle.ShowType
        BITMAP_FIELD_NUMBER: _ClassVar[int]
        FILL: ObstacleInfo.Obstacle.ShowType
        OBJECT_TYPE_FIELD_NUMBER: _ClassVar[int]
        OUTLINE: ObstacleInfo.Obstacle.ShowType
        PHOTO_ID_FIELD_NUMBER: _ClassVar[int]
        POSITION: ObstacleInfo.Obstacle.ShowType
        SHOW_POINTS_FIELD_NUMBER: _ClassVar[int]
        SHOW_TYPE_FIELD_NUMBER: _ClassVar[int]
        THETA_FIELD_NUMBER: _ClassVar[int]
        VALID_FIELD_NUMBER: _ClassVar[int]
        accuracy: int
        bitmap: ObstacleInfo.Obstacle.Bitmap
        object_type: str
        photo_id: str
        show_points: _containers.RepeatedCompositeFieldContainer[_common_pb2.Point]
        show_type: ObstacleInfo.Obstacle.ShowType
        theta: int
        valid: ObstacleInfo.Obstacle.Valid
        def __init__(self, object_type: _Optional[str] = ..., show_type: _Optional[_Union[ObstacleInfo.Obstacle.ShowType, str]] = ..., show_points: _Optional[_Iterable[_Union[_common_pb2.Point, _Mapping]]] = ..., bitmap: _Optional[_Union[ObstacleInfo.Obstacle.Bitmap, _Mapping]] = ..., theta: _Optional[int] = ..., photo_id: _Optional[str] = ..., accuracy: _Optional[int] = ..., valid: _Optional[_Union[ObstacleInfo.Obstacle.Valid, _Mapping]] = ...) -> None: ...
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    OBSTACLES_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    map_id: int
    obstacles: _containers.RepeatedCompositeFieldContainer[ObstacleInfo.Obstacle]
    releases: int
    def __init__(self, map_id: _Optional[int] = ..., releases: _Optional[int] = ..., obstacles: _Optional[_Iterable[_Union[ObstacleInfo.Obstacle, _Mapping]]] = ...) -> None: ...

class PathPoint(_message.Message):
    __slots__ = ["flags", "xy"]
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    XY_FIELD_NUMBER: _ClassVar[int]
    flags: int
    xy: int
    def __init__(self, xy: _Optional[int] = ..., flags: _Optional[int] = ...) -> None: ...

class RestrictedZone(_message.Message):
    __slots__ = ["ban_mop_zones", "forbidden_zones", "map_id", "releases", "suggestion", "virtual_walls"]
    class Suggestion(_message.Message):
        __slots__ = ["ban_mop_zones", "forbidden_zones", "virtual_walls"]
        class LineWrap(_message.Message):
            __slots__ = ["id", "line"]
            ID_FIELD_NUMBER: _ClassVar[int]
            LINE_FIELD_NUMBER: _ClassVar[int]
            id: int
            line: _common_pb2.Line
            def __init__(self, id: _Optional[int] = ..., line: _Optional[_Union[_common_pb2.Line, _Mapping]] = ...) -> None: ...
        class QuadrangleWrap(_message.Message):
            __slots__ = ["id", "quadrangle"]
            ID_FIELD_NUMBER: _ClassVar[int]
            QUADRANGLE_FIELD_NUMBER: _ClassVar[int]
            id: int
            quadrangle: _common_pb2.Quadrangle
            def __init__(self, id: _Optional[int] = ..., quadrangle: _Optional[_Union[_common_pb2.Quadrangle, _Mapping]] = ...) -> None: ...
        BAN_MOP_ZONES_FIELD_NUMBER: _ClassVar[int]
        FORBIDDEN_ZONES_FIELD_NUMBER: _ClassVar[int]
        VIRTUAL_WALLS_FIELD_NUMBER: _ClassVar[int]
        ban_mop_zones: _containers.RepeatedCompositeFieldContainer[RestrictedZone.Suggestion.QuadrangleWrap]
        forbidden_zones: _containers.RepeatedCompositeFieldContainer[RestrictedZone.Suggestion.QuadrangleWrap]
        virtual_walls: _containers.RepeatedCompositeFieldContainer[RestrictedZone.Suggestion.LineWrap]
        def __init__(self, virtual_walls: _Optional[_Iterable[_Union[RestrictedZone.Suggestion.LineWrap, _Mapping]]] = ..., forbidden_zones: _Optional[_Iterable[_Union[RestrictedZone.Suggestion.QuadrangleWrap, _Mapping]]] = ..., ban_mop_zones: _Optional[_Iterable[_Union[RestrictedZone.Suggestion.QuadrangleWrap, _Mapping]]] = ...) -> None: ...
    BAN_MOP_ZONES_FIELD_NUMBER: _ClassVar[int]
    FORBIDDEN_ZONES_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    SUGGESTION_FIELD_NUMBER: _ClassVar[int]
    VIRTUAL_WALLS_FIELD_NUMBER: _ClassVar[int]
    ban_mop_zones: _containers.RepeatedCompositeFieldContainer[_common_pb2.Quadrangle]
    forbidden_zones: _containers.RepeatedCompositeFieldContainer[_common_pb2.Quadrangle]
    map_id: int
    releases: int
    suggestion: RestrictedZone.Suggestion
    virtual_walls: _containers.RepeatedCompositeFieldContainer[_common_pb2.Line]
    def __init__(self, virtual_walls: _Optional[_Iterable[_Union[_common_pb2.Line, _Mapping]]] = ..., forbidden_zones: _Optional[_Iterable[_Union[_common_pb2.Quadrangle, _Mapping]]] = ..., ban_mop_zones: _Optional[_Iterable[_Union[_common_pb2.Quadrangle, _Mapping]]] = ..., map_id: _Optional[int] = ..., releases: _Optional[int] = ..., suggestion: _Optional[_Union[RestrictedZone.Suggestion, _Mapping]] = ...) -> None: ...

class RoomOutline(_message.Message):
    __slots__ = ["height", "map_id", "origin", "pixel_size", "pixels", "releases", "resolution", "width"]
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_FIELD_NUMBER: _ClassVar[int]
    PIXELS_FIELD_NUMBER: _ClassVar[int]
    PIXEL_SIZE_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    RESOLUTION_FIELD_NUMBER: _ClassVar[int]
    WIDTH_FIELD_NUMBER: _ClassVar[int]
    height: int
    map_id: int
    origin: _common_pb2.Point
    pixel_size: int
    pixels: bytes
    releases: int
    resolution: int
    width: int
    def __init__(self, map_id: _Optional[int] = ..., releases: _Optional[int] = ..., width: _Optional[int] = ..., height: _Optional[int] = ..., resolution: _Optional[int] = ..., origin: _Optional[_Union[_common_pb2.Point, _Mapping]] = ..., pixels: _Optional[bytes] = ..., pixel_size: _Optional[int] = ...) -> None: ...

class RoomParams(_message.Message):
    __slots__ = ["custom_enable", "map_id", "releases", "rooms", "smart_mode_sw"]
    class Room(_message.Message):
        __slots__ = ["custom", "floor", "id", "name", "order", "scene"]
        class Custom(_message.Message):
            __slots__ = ["clean_extent", "clean_times", "clean_type", "fan", "mop_mode"]
            CLEAN_EXTENT_FIELD_NUMBER: _ClassVar[int]
            CLEAN_TIMES_FIELD_NUMBER: _ClassVar[int]
            CLEAN_TYPE_FIELD_NUMBER: _ClassVar[int]
            FAN_FIELD_NUMBER: _ClassVar[int]
            MOP_MODE_FIELD_NUMBER: _ClassVar[int]
            clean_extent: _clean_param_pb2.CleanExtent
            clean_times: int
            clean_type: _clean_param_pb2.CleanType
            fan: _clean_param_pb2.Fan
            mop_mode: _clean_param_pb2.MopMode
            def __init__(self, clean_type: _Optional[_Union[_clean_param_pb2.CleanType, _Mapping]] = ..., fan: _Optional[_Union[_clean_param_pb2.Fan, _Mapping]] = ..., mop_mode: _Optional[_Union[_clean_param_pb2.MopMode, _Mapping]] = ..., clean_extent: _Optional[_Union[_clean_param_pb2.CleanExtent, _Mapping]] = ..., clean_times: _Optional[int] = ...) -> None: ...
        class Order(_message.Message):
            __slots__ = ["value"]
            VALUE_FIELD_NUMBER: _ClassVar[int]
            value: int
            def __init__(self, value: _Optional[int] = ...) -> None: ...
        CUSTOM_FIELD_NUMBER: _ClassVar[int]
        FLOOR_FIELD_NUMBER: _ClassVar[int]
        ID_FIELD_NUMBER: _ClassVar[int]
        NAME_FIELD_NUMBER: _ClassVar[int]
        ORDER_FIELD_NUMBER: _ClassVar[int]
        SCENE_FIELD_NUMBER: _ClassVar[int]
        custom: RoomParams.Room.Custom
        floor: _common_pb2.Floor
        id: int
        name: str
        order: RoomParams.Room.Order
        scene: _common_pb2.RoomScene
        def __init__(self, id: _Optional[int] = ..., name: _Optional[str] = ..., floor: _Optional[_Union[_common_pb2.Floor, _Mapping]] = ..., scene: _Optional[_Union[_common_pb2.RoomScene, _Mapping]] = ..., order: _Optional[_Union[RoomParams.Room.Order, _Mapping]] = ..., custom: _Optional[_Union[RoomParams.Room.Custom, _Mapping]] = ...) -> None: ...
    CUSTOM_ENABLE_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    ROOMS_FIELD_NUMBER: _ClassVar[int]
    SMART_MODE_SW_FIELD_NUMBER: _ClassVar[int]
    custom_enable: bool
    map_id: int
    releases: int
    rooms: _containers.RepeatedCompositeFieldContainer[RoomParams.Room]
    smart_mode_sw: _common_pb2.Switch
    def __init__(self, custom_enable: bool = ..., rooms: _Optional[_Iterable[_Union[RoomParams.Room, _Mapping]]] = ..., map_id: _Optional[int] = ..., releases: _Optional[int] = ..., smart_mode_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ...) -> None: ...

class SceneWrap(_message.Message):
    __slots__ = ["scenes"]
    class Scene(_message.Message):
        __slots__ = ["info", "tasks"]
        INFO_FIELD_NUMBER: _ClassVar[int]
        TASKS_FIELD_NUMBER: _ClassVar[int]
        info: _scene_pb2.SceneInfo
        tasks: _containers.RepeatedCompositeFieldContainer[_scene_pb2.SceneTask]
        def __init__(self, info: _Optional[_Union[_scene_pb2.SceneInfo, _Mapping]] = ..., tasks: _Optional[_Iterable[_Union[_scene_pb2.SceneTask, _Mapping]]] = ...) -> None: ...
    SCENES_FIELD_NUMBER: _ClassVar[int]
    scenes: _containers.RepeatedCompositeFieldContainer[SceneWrap.Scene]
    def __init__(self, scenes: _Optional[_Iterable[_Union[SceneWrap.Scene, _Mapping]]] = ...) -> None: ...

class TemporaryData(_message.Message):
    __slots__ = ["goto_location", "select_point_cruise", "select_rooms_clean", "select_zones_clean", "select_zones_cruise"]
    GOTO_LOCATION_FIELD_NUMBER: _ClassVar[int]
    SELECT_POINT_CRUISE_FIELD_NUMBER: _ClassVar[int]
    SELECT_ROOMS_CLEAN_FIELD_NUMBER: _ClassVar[int]
    SELECT_ZONES_CLEAN_FIELD_NUMBER: _ClassVar[int]
    SELECT_ZONES_CRUISE_FIELD_NUMBER: _ClassVar[int]
    goto_location: _control_pb2.Goto
    select_point_cruise: _control_pb2.PointCruise
    select_rooms_clean: _control_pb2.SelectRoomsClean
    select_zones_clean: _control_pb2.SelectZonesClean
    select_zones_cruise: _control_pb2.ZonesCruise
    def __init__(self, select_rooms_clean: _Optional[_Union[_control_pb2.SelectRoomsClean, _Mapping]] = ..., select_zones_clean: _Optional[_Union[_control_pb2.SelectZonesClean, _Mapping]] = ..., goto_location: _Optional[_Union[_control_pb2.Goto, _Mapping]] = ..., select_point_cruise: _Optional[_Union[_control_pb2.PointCruise, _Mapping]] = ..., select_zones_cruise: _Optional[_Union[_control_pb2.ZonesCruise, _Mapping]] = ...) -> None: ...
