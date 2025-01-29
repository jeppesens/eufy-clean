from typing import ClassVar as _ClassVar
from typing import Iterable as _Iterable
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

from ...proto.cloud import clean_param_pb2 as _clean_param_pb2
from ...proto.cloud import common_pb2 as _common_pb2
from ...proto.cloud import stream_pb2 as _stream_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class MapEditRequest(_message.Message):
    __slots__ = ["cruise_points", "divide_room", "ignore_obstacle", "map_id", "merge_rooms", "method", "restricted_zone", "room_desc", "rooms_custom", "rotation", "seq"]
    class Method(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class CruisePoints(_message.Message):
        __slots__ = ["points"]
        POINTS_FIELD_NUMBER: _ClassVar[int]
        points: _containers.RepeatedCompositeFieldContainer[_common_pb2.Point]
        def __init__(self, points: _Optional[_Iterable[_Union[_common_pb2.Point, _Mapping]]] = ...) -> None: ...
    class DivideRoom(_message.Message):
        __slots__ = ["points", "room_id"]
        POINTS_FIELD_NUMBER: _ClassVar[int]
        ROOM_ID_FIELD_NUMBER: _ClassVar[int]
        points: _containers.RepeatedCompositeFieldContainer[_common_pb2.Point]
        room_id: int
        def __init__(self, room_id: _Optional[int] = ..., points: _Optional[_Iterable[_Union[_common_pb2.Point, _Mapping]]] = ...) -> None: ...
    class IgnoreObstacle(_message.Message):
        __slots__ = ["object_type", "photo_id", "point", "valid"]
        OBJECT_TYPE_FIELD_NUMBER: _ClassVar[int]
        PHOTO_ID_FIELD_NUMBER: _ClassVar[int]
        POINT_FIELD_NUMBER: _ClassVar[int]
        VALID_FIELD_NUMBER: _ClassVar[int]
        object_type: str
        photo_id: str
        point: _common_pb2.Point
        valid: bool
        def __init__(self, valid: bool = ..., object_type: _Optional[str] = ..., photo_id: _Optional[str] = ..., point: _Optional[_Union[_common_pb2.Point, _Mapping]] = ...) -> None: ...
    class MergeRooms(_message.Message):
        __slots__ = ["room_ids"]
        ROOM_IDS_FIELD_NUMBER: _ClassVar[int]
        room_ids: _containers.RepeatedScalarFieldContainer[int]
        def __init__(self, room_ids: _Optional[_Iterable[int]] = ...) -> None: ...
    class RoomDesc(_message.Message):
        __slots__ = ["floor", "id", "name", "scene"]
        FLOOR_FIELD_NUMBER: _ClassVar[int]
        ID_FIELD_NUMBER: _ClassVar[int]
        NAME_FIELD_NUMBER: _ClassVar[int]
        SCENE_FIELD_NUMBER: _ClassVar[int]
        floor: _common_pb2.Floor
        id: int
        name: str
        scene: _common_pb2.RoomScene
        def __init__(self, id: _Optional[int] = ..., name: _Optional[str] = ..., floor: _Optional[_Union[_common_pb2.Floor, _Mapping]] = ..., scene: _Optional[_Union[_common_pb2.RoomScene, _Mapping]] = ...) -> None: ...
    class RoomsCustom(_message.Message):
        __slots__ = ["condition", "custom_enable", "rooms_order", "rooms_parm", "smart_mode_sw"]
        class Condition(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class Enable(_message.Message):
            __slots__ = ["value"]
            VALUE_FIELD_NUMBER: _ClassVar[int]
            value: bool
            def __init__(self, value: bool = ...) -> None: ...
        class Order(_message.Message):
            __slots__ = ["rooms"]
            class Room(_message.Message):
                __slots__ = ["id", "order"]
                ID_FIELD_NUMBER: _ClassVar[int]
                ORDER_FIELD_NUMBER: _ClassVar[int]
                id: int
                order: int
                def __init__(self, id: _Optional[int] = ..., order: _Optional[int] = ...) -> None: ...
            ROOMS_FIELD_NUMBER: _ClassVar[int]
            rooms: _containers.RepeatedCompositeFieldContainer[MapEditRequest.RoomsCustom.Order.Room]
            def __init__(self, rooms: _Optional[_Iterable[_Union[MapEditRequest.RoomsCustom.Order.Room, _Mapping]]] = ...) -> None: ...
        class Parm(_message.Message):
            __slots__ = ["rooms"]
            class Room(_message.Message):
                __slots__ = ["custom", "id"]
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
                CUSTOM_FIELD_NUMBER: _ClassVar[int]
                ID_FIELD_NUMBER: _ClassVar[int]
                custom: MapEditRequest.RoomsCustom.Parm.Room.Custom
                id: int
                def __init__(self, id: _Optional[int] = ..., custom: _Optional[_Union[MapEditRequest.RoomsCustom.Parm.Room.Custom, _Mapping]] = ...) -> None: ...
            ROOMS_FIELD_NUMBER: _ClassVar[int]
            rooms: _containers.RepeatedCompositeFieldContainer[MapEditRequest.RoomsCustom.Parm.Room]
            def __init__(self, rooms: _Optional[_Iterable[_Union[MapEditRequest.RoomsCustom.Parm.Room, _Mapping]]] = ...) -> None: ...
        CONDITION_FIELD_NUMBER: _ClassVar[int]
        CUSTOM_ENABLE_FIELD_NUMBER: _ClassVar[int]
        GENERAL: MapEditRequest.RoomsCustom.Condition
        RESERVATION_IN_PROGRESS: MapEditRequest.RoomsCustom.Condition
        ROOMS_ORDER_FIELD_NUMBER: _ClassVar[int]
        ROOMS_PARM_FIELD_NUMBER: _ClassVar[int]
        SMART_MODE_SW_FIELD_NUMBER: _ClassVar[int]
        condition: MapEditRequest.RoomsCustom.Condition
        custom_enable: MapEditRequest.RoomsCustom.Enable
        rooms_order: MapEditRequest.RoomsCustom.Order
        rooms_parm: MapEditRequest.RoomsCustom.Parm
        smart_mode_sw: _common_pb2.Switch
        def __init__(self, custom_enable: _Optional[_Union[MapEditRequest.RoomsCustom.Enable, _Mapping]] = ..., rooms_order: _Optional[_Union[MapEditRequest.RoomsCustom.Order, _Mapping]] = ..., rooms_parm: _Optional[_Union[MapEditRequest.RoomsCustom.Parm, _Mapping]] = ..., smart_mode_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., condition: _Optional[_Union[MapEditRequest.RoomsCustom.Condition, str]] = ...) -> None: ...
    class Rotation(_message.Message):
        __slots__ = ["angle"]
        ANGLE_FIELD_NUMBER: _ClassVar[int]
        angle: int
        def __init__(self, angle: _Optional[int] = ...) -> None: ...
    CRUISE_POINTS_FIELD_NUMBER: _ClassVar[int]
    DIVIDE_ROOM: MapEditRequest.Method
    DIVIDE_ROOM_FIELD_NUMBER: _ClassVar[int]
    IGNORE_OBSTACLE: MapEditRequest.Method
    IGNORE_OBSTACLE_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    MERGE_ROOMS: MapEditRequest.Method
    MERGE_ROOMS_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    RENAME_ROOM: MapEditRequest.Method
    RESET_ROOMS: MapEditRequest.Method
    RESTRICTED_ZONE_FIELD_NUMBER: _ClassVar[int]
    ROOMS_CUSTOM_FIELD_NUMBER: _ClassVar[int]
    ROOM_DESC_FIELD_NUMBER: _ClassVar[int]
    ROTATION: MapEditRequest.Method
    ROTATION_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    SET_CRUISE_POINTS: MapEditRequest.Method
    SET_RESTRICTED_ZONES: MapEditRequest.Method
    SET_ROOMS_CUSTOM: MapEditRequest.Method
    cruise_points: MapEditRequest.CruisePoints
    divide_room: MapEditRequest.DivideRoom
    ignore_obstacle: MapEditRequest.IgnoreObstacle
    map_id: int
    merge_rooms: MapEditRequest.MergeRooms
    method: MapEditRequest.Method
    restricted_zone: _stream_pb2.RestrictedZone
    room_desc: MapEditRequest.RoomDesc
    rooms_custom: MapEditRequest.RoomsCustom
    rotation: MapEditRequest.Rotation
    seq: int
    def __init__(self, method: _Optional[_Union[MapEditRequest.Method, str]] = ..., seq: _Optional[int] = ..., map_id: _Optional[int] = ..., merge_rooms: _Optional[_Union[MapEditRequest.MergeRooms, _Mapping]] = ..., divide_room: _Optional[_Union[MapEditRequest.DivideRoom, _Mapping]] = ..., restricted_zone: _Optional[_Union[_stream_pb2.RestrictedZone, _Mapping]] = ..., room_desc: _Optional[_Union[MapEditRequest.RoomDesc, _Mapping]] = ..., rooms_custom: _Optional[_Union[MapEditRequest.RoomsCustom, _Mapping]] = ..., cruise_points: _Optional[_Union[MapEditRequest.CruisePoints, _Mapping]] = ..., rotation: _Optional[_Union[MapEditRequest.Rotation, _Mapping]] = ..., ignore_obstacle: _Optional[_Union[MapEditRequest.IgnoreObstacle, _Mapping]] = ...) -> None: ...

class MapEditResponse(_message.Message):
    __slots__ = ["fail_code", "method", "result", "seq"]
    class Result(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class FailCode(_message.Message):
        __slots__ = ["value"]
        class Value(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        AREA_SMALL: MapEditResponse.FailCode.Value
        ROOM_UNADJACENT: MapEditResponse.FailCode.Value
        TOO_MANY_ROOMS: MapEditResponse.FailCode.Value
        UNKNOWN: MapEditResponse.FailCode.Value
        VALUE_FIELD_NUMBER: _ClassVar[int]
        value: MapEditResponse.FailCode.Value
        def __init__(self, value: _Optional[_Union[MapEditResponse.FailCode.Value, str]] = ...) -> None: ...
    FAILED: MapEditResponse.Result
    FAIL_CODE_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    STARTED: MapEditResponse.Result
    SUCCESS: MapEditResponse.Result
    fail_code: MapEditResponse.FailCode
    method: MapEditRequest.Method
    result: MapEditResponse.Result
    seq: int
    def __init__(self, method: _Optional[_Union[MapEditRequest.Method, str]] = ..., seq: _Optional[int] = ..., result: _Optional[_Union[MapEditResponse.Result, str]] = ..., fail_code: _Optional[_Union[MapEditResponse.FailCode, _Mapping]] = ...) -> None: ...
