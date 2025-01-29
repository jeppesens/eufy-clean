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

DESCRIPTOR: _descriptor.FileDescriptor

class AutoClean(_message.Message):
    __slots__ = ["clean_times", "force_mapping"]
    CLEAN_TIMES_FIELD_NUMBER: _ClassVar[int]
    FORCE_MAPPING_FIELD_NUMBER: _ClassVar[int]
    clean_times: int
    force_mapping: bool
    def __init__(self, clean_times: _Optional[int] = ..., force_mapping: bool = ...) -> None: ...

class GlobalCruise(_message.Message):
    __slots__ = ["map_id", "releases"]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    map_id: int
    releases: int
    def __init__(self, map_id: _Optional[int] = ..., releases: _Optional[int] = ...) -> None: ...

class Goto(_message.Message):
    __slots__ = ["clean_times", "destination", "map_id", "releases", "type"]
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    CLEAN_TIMES_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_FIELD_NUMBER: _ClassVar[int]
    GOTO_AUTO: Goto.Type
    GOTO_DESTINATION: Goto.Type
    GOTO_SPOT: Goto.Type
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    clean_times: int
    destination: _common_pb2.Point
    map_id: int
    releases: int
    type: Goto.Type
    def __init__(self, destination: _Optional[_Union[_common_pb2.Point, _Mapping]] = ..., type: _Optional[_Union[Goto.Type, str]] = ..., clean_times: _Optional[int] = ..., map_id: _Optional[int] = ..., releases: _Optional[int] = ...) -> None: ...

class ModeCtrlRequest(_message.Message):
    __slots__ = ["auto_clean", "global_cruise", "go_to", "method", "point_cruise", "scene_clean", "sche_auto_clean", "sche_cruise", "sche_rooms_clean", "select_rooms_clean", "select_zones_clean", "seq", "spot_clean", "zones_cruise"]
    class Method(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    AUTO_CLEAN_FIELD_NUMBER: _ClassVar[int]
    GLOBAL_CRUISE_FIELD_NUMBER: _ClassVar[int]
    GO_TO_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    PAUSE_TASK: ModeCtrlRequest.Method
    POINT_CRUISE_FIELD_NUMBER: _ClassVar[int]
    RESUME_TASK: ModeCtrlRequest.Method
    SCENE_CLEAN_FIELD_NUMBER: _ClassVar[int]
    SCHE_AUTO_CLEAN_FIELD_NUMBER: _ClassVar[int]
    SCHE_CRUISE_FIELD_NUMBER: _ClassVar[int]
    SCHE_ROOMS_CLEAN_FIELD_NUMBER: _ClassVar[int]
    SELECT_ROOMS_CLEAN_FIELD_NUMBER: _ClassVar[int]
    SELECT_ZONES_CLEAN_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    SPOT_CLEAN_FIELD_NUMBER: _ClassVar[int]
    START_AUTO_CLEAN: ModeCtrlRequest.Method
    START_FAST_MAPPING: ModeCtrlRequest.Method
    START_GLOBAL_CRUISE: ModeCtrlRequest.Method
    START_GOHOME: ModeCtrlRequest.Method
    START_GOTO_CLEAN: ModeCtrlRequest.Method
    START_GOWASH: ModeCtrlRequest.Method
    START_MAPPING_THEN_CLEAN: ModeCtrlRequest.Method
    START_POINT_CRUISE: ModeCtrlRequest.Method
    START_RC_CLEAN: ModeCtrlRequest.Method
    START_SCENE_CLEAN: ModeCtrlRequest.Method
    START_SCHEDULE_AUTO_CLEAN: ModeCtrlRequest.Method
    START_SCHEDULE_CRUISE: ModeCtrlRequest.Method
    START_SCHEDULE_ROOMS_CLEAN: ModeCtrlRequest.Method
    START_SELECT_ROOMS_CLEAN: ModeCtrlRequest.Method
    START_SELECT_ZONES_CLEAN: ModeCtrlRequest.Method
    START_SPOT_CLEAN: ModeCtrlRequest.Method
    START_ZONES_CRUISE: ModeCtrlRequest.Method
    STOP_GOHOME: ModeCtrlRequest.Method
    STOP_GOWASH: ModeCtrlRequest.Method
    STOP_RC_CLEAN: ModeCtrlRequest.Method
    STOP_SMART_FOLLOW: ModeCtrlRequest.Method
    STOP_TASK: ModeCtrlRequest.Method
    ZONES_CRUISE_FIELD_NUMBER: _ClassVar[int]
    auto_clean: AutoClean
    global_cruise: GlobalCruise
    go_to: Goto
    method: ModeCtrlRequest.Method
    point_cruise: PointCruise
    scene_clean: SceneClean
    sche_auto_clean: ScheduleAutoClean
    sche_cruise: ScheduleCruise
    sche_rooms_clean: ScheduleRoomsClean
    select_rooms_clean: SelectRoomsClean
    select_zones_clean: SelectZonesClean
    seq: int
    spot_clean: SpotClean
    zones_cruise: ZonesCruise
    def __init__(self, method: _Optional[_Union[ModeCtrlRequest.Method, str]] = ..., seq: _Optional[int] = ..., auto_clean: _Optional[_Union[AutoClean, _Mapping]] = ..., select_rooms_clean: _Optional[_Union[SelectRoomsClean, _Mapping]] = ..., select_zones_clean: _Optional[_Union[SelectZonesClean, _Mapping]] = ..., spot_clean: _Optional[_Union[SpotClean, _Mapping]] = ..., go_to: _Optional[_Union[Goto, _Mapping]] = ..., sche_auto_clean: _Optional[_Union[ScheduleAutoClean, _Mapping]] = ..., sche_rooms_clean: _Optional[_Union[ScheduleRoomsClean, _Mapping]] = ..., global_cruise: _Optional[_Union[GlobalCruise, _Mapping]] = ..., point_cruise: _Optional[_Union[PointCruise, _Mapping]] = ..., zones_cruise: _Optional[_Union[ZonesCruise, _Mapping]] = ..., sche_cruise: _Optional[_Union[ScheduleCruise, _Mapping]] = ..., scene_clean: _Optional[_Union[SceneClean, _Mapping]] = ...) -> None: ...

class ModeCtrlResponse(_message.Message):
    __slots__ = ["method", "result", "seq"]
    class Result(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    FAILED: ModeCtrlResponse.Result
    METHOD_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    SUCCESS: ModeCtrlResponse.Result
    method: ModeCtrlRequest.Method
    result: ModeCtrlResponse.Result
    seq: int
    def __init__(self, method: _Optional[_Union[ModeCtrlRequest.Method, str]] = ..., seq: _Optional[int] = ..., result: _Optional[_Union[ModeCtrlResponse.Result, str]] = ...) -> None: ...

class PointCruise(_message.Message):
    __slots__ = ["map_id", "points", "releases"]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    POINTS_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    map_id: int
    points: _common_pb2.Point
    releases: int
    def __init__(self, points: _Optional[_Union[_common_pb2.Point, _Mapping]] = ..., map_id: _Optional[int] = ..., releases: _Optional[int] = ...) -> None: ...

class RemoteCtrl(_message.Message):
    __slots__ = ["direction"]
    class Direction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    BACK: RemoteCtrl.Direction
    BRAKE: RemoteCtrl.Direction
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    FORWARD: RemoteCtrl.Direction
    LEFT: RemoteCtrl.Direction
    RIGHT: RemoteCtrl.Direction
    direction: RemoteCtrl.Direction
    def __init__(self, direction: _Optional[_Union[RemoteCtrl.Direction, str]] = ...) -> None: ...

class SceneClean(_message.Message):
    __slots__ = ["scene_id"]
    SCENE_ID_FIELD_NUMBER: _ClassVar[int]
    scene_id: int
    def __init__(self, scene_id: _Optional[int] = ...) -> None: ...

class ScheduleAutoClean(_message.Message):
    __slots__ = ["clean_extent", "clean_type", "fan", "mop_mode"]
    CLEAN_EXTENT_FIELD_NUMBER: _ClassVar[int]
    CLEAN_TYPE_FIELD_NUMBER: _ClassVar[int]
    FAN_FIELD_NUMBER: _ClassVar[int]
    MOP_MODE_FIELD_NUMBER: _ClassVar[int]
    clean_extent: _clean_param_pb2.CleanExtent
    clean_type: _clean_param_pb2.CleanType
    fan: _clean_param_pb2.Fan
    mop_mode: _clean_param_pb2.MopMode
    def __init__(self, fan: _Optional[_Union[_clean_param_pb2.Fan, _Mapping]] = ..., mop_mode: _Optional[_Union[_clean_param_pb2.MopMode, _Mapping]] = ..., clean_type: _Optional[_Union[_clean_param_pb2.CleanType, _Mapping]] = ..., clean_extent: _Optional[_Union[_clean_param_pb2.CleanExtent, _Mapping]] = ...) -> None: ...

class ScheduleCruise(_message.Message):
    __slots__ = ["map_id", "releases"]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    map_id: int
    releases: int
    def __init__(self, map_id: _Optional[int] = ..., releases: _Optional[int] = ...) -> None: ...

class ScheduleRoomsClean(_message.Message):
    __slots__ = ["clean_extent", "clean_type", "fan", "map_id", "mop_mode", "releases", "rooms"]
    class Room(_message.Message):
        __slots__ = ["id", "order"]
        ID_FIELD_NUMBER: _ClassVar[int]
        ORDER_FIELD_NUMBER: _ClassVar[int]
        id: int
        order: int
        def __init__(self, id: _Optional[int] = ..., order: _Optional[int] = ...) -> None: ...
    CLEAN_EXTENT_FIELD_NUMBER: _ClassVar[int]
    CLEAN_TYPE_FIELD_NUMBER: _ClassVar[int]
    FAN_FIELD_NUMBER: _ClassVar[int]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    MOP_MODE_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    ROOMS_FIELD_NUMBER: _ClassVar[int]
    clean_extent: _clean_param_pb2.CleanExtent
    clean_type: _clean_param_pb2.CleanType
    fan: _clean_param_pb2.Fan
    map_id: int
    mop_mode: _clean_param_pb2.MopMode
    releases: int
    rooms: _containers.RepeatedCompositeFieldContainer[ScheduleRoomsClean.Room]
    def __init__(self, fan: _Optional[_Union[_clean_param_pb2.Fan, _Mapping]] = ..., mop_mode: _Optional[_Union[_clean_param_pb2.MopMode, _Mapping]] = ..., clean_type: _Optional[_Union[_clean_param_pb2.CleanType, _Mapping]] = ..., clean_extent: _Optional[_Union[_clean_param_pb2.CleanExtent, _Mapping]] = ..., rooms: _Optional[_Iterable[_Union[ScheduleRoomsClean.Room, _Mapping]]] = ..., map_id: _Optional[int] = ..., releases: _Optional[int] = ...) -> None: ...

class SelectRoomsClean(_message.Message):
    __slots__ = ["clean_times", "map_id", "mode", "releases", "rooms"]
    class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Room(_message.Message):
        __slots__ = ["id", "order"]
        ID_FIELD_NUMBER: _ClassVar[int]
        ORDER_FIELD_NUMBER: _ClassVar[int]
        id: int
        order: int
        def __init__(self, id: _Optional[int] = ..., order: _Optional[int] = ...) -> None: ...
    CLEAN_TIMES_FIELD_NUMBER: _ClassVar[int]
    CUSTOMIZE: SelectRoomsClean.Mode
    GENERAL: SelectRoomsClean.Mode
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    ROOMS_FIELD_NUMBER: _ClassVar[int]
    clean_times: int
    map_id: int
    mode: SelectRoomsClean.Mode
    releases: int
    rooms: _containers.RepeatedCompositeFieldContainer[SelectRoomsClean.Room]
    def __init__(self, rooms: _Optional[_Iterable[_Union[SelectRoomsClean.Room, _Mapping]]] = ..., clean_times: _Optional[int] = ..., map_id: _Optional[int] = ..., releases: _Optional[int] = ..., mode: _Optional[_Union[SelectRoomsClean.Mode, str]] = ...) -> None: ...

class SelectZonesClean(_message.Message):
    __slots__ = ["map_id", "releases", "type", "zones"]
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Zone(_message.Message):
        __slots__ = ["clean_times", "quadrangle"]
        CLEAN_TIMES_FIELD_NUMBER: _ClassVar[int]
        QUADRANGLE_FIELD_NUMBER: _ClassVar[int]
        clean_times: int
        quadrangle: _common_pb2.Quadrangle
        def __init__(self, quadrangle: _Optional[_Union[_common_pb2.Quadrangle, _Mapping]] = ..., clean_times: _Optional[int] = ...) -> None: ...
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    NORMAL: SelectZonesClean.Type
    POOP_CLEANING: SelectZonesClean.Type
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    ZONES_FIELD_NUMBER: _ClassVar[int]
    map_id: int
    releases: int
    type: SelectZonesClean.Type
    zones: _containers.RepeatedCompositeFieldContainer[SelectZonesClean.Zone]
    def __init__(self, zones: _Optional[_Iterable[_Union[SelectZonesClean.Zone, _Mapping]]] = ..., map_id: _Optional[int] = ..., releases: _Optional[int] = ..., type: _Optional[_Union[SelectZonesClean.Type, str]] = ...) -> None: ...

class SpotClean(_message.Message):
    __slots__ = ["clean_times"]
    CLEAN_TIMES_FIELD_NUMBER: _ClassVar[int]
    clean_times: int
    def __init__(self, clean_times: _Optional[int] = ...) -> None: ...

class ZonesCruise(_message.Message):
    __slots__ = ["map_id", "points", "releases"]
    MAP_ID_FIELD_NUMBER: _ClassVar[int]
    POINTS_FIELD_NUMBER: _ClassVar[int]
    RELEASES_FIELD_NUMBER: _ClassVar[int]
    map_id: int
    points: _containers.RepeatedCompositeFieldContainer[_common_pb2.Point]
    releases: int
    def __init__(self, points: _Optional[_Iterable[_Union[_common_pb2.Point, _Mapping]]] = ..., map_id: _Optional[int] = ..., releases: _Optional[int] = ...) -> None: ...
