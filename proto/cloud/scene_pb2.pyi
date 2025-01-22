from proto.cloud import common_pb2 as _common_pb2
from proto.cloud import clean_param_pb2 as _clean_param_pb2
from proto.cloud import timing_pb2 as _timing_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SceneInfo(_message.Message):
    __slots__ = ["estimate_time", "id", "index", "invalid_reason", "mapid", "name", "type", "valid"]
    class InvalidReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Id(_message.Message):
        __slots__ = ["value"]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        value: int
        def __init__(self, value: _Optional[int] = ...) -> None: ...
    AFTER_DINNER_CLEANING: SceneInfo.Type
    DEFAULT: SceneInfo.InvalidReason
    ESTIMATE_TIME_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    INVALID_REASON_FIELD_NUMBER: _ClassVar[int]
    MAPID_FIELD_NUMBER: _ClassVar[int]
    MAP_NOT_AVAILABLE: SceneInfo.InvalidReason
    MAP_NOT_EXIST: SceneInfo.InvalidReason
    MAP_NOT_MATCH: SceneInfo.InvalidReason
    NAME_FIELD_NUMBER: _ClassVar[int]
    NORMAL: SceneInfo.InvalidReason
    OTHER: SceneInfo.InvalidReason
    PET_AREA_CLEANING: SceneInfo.Type
    SCENE_NORMAL: SceneInfo.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    VALID_FIELD_NUMBER: _ClassVar[int]
    WHOLE_HOUSE_DAILY_CLEANING: SceneInfo.Type
    WHOLE_HOUSE_DEEP_CLEANING: SceneInfo.Type
    estimate_time: int
    id: SceneInfo.Id
    index: int
    invalid_reason: SceneInfo.InvalidReason
    mapid: int
    name: str
    type: SceneInfo.Type
    valid: bool
    def __init__(self, id: _Optional[_Union[SceneInfo.Id, _Mapping]] = ..., valid: bool = ..., invalid_reason: _Optional[_Union[SceneInfo.InvalidReason, str]] = ..., name: _Optional[str] = ..., mapid: _Optional[int] = ..., estimate_time: _Optional[int] = ..., index: _Optional[int] = ..., type: _Optional[_Union[SceneInfo.Type, str]] = ...) -> None: ...

class SceneRequest(_message.Message):
    __slots__ = ["common", "method", "scene", "seq"]
    class Method(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Common(_message.Message):
        __slots__ = ["scene_id"]
        SCENE_ID_FIELD_NUMBER: _ClassVar[int]
        scene_id: int
        def __init__(self, scene_id: _Optional[int] = ...) -> None: ...
    class Scene(_message.Message):
        __slots__ = ["desc", "info", "tasks"]
        DESC_FIELD_NUMBER: _ClassVar[int]
        INFO_FIELD_NUMBER: _ClassVar[int]
        TASKS_FIELD_NUMBER: _ClassVar[int]
        desc: _timing_pb2.TimerInfo.Desc
        info: SceneInfo
        tasks: _containers.RepeatedCompositeFieldContainer[SceneTask]
        def __init__(self, info: _Optional[_Union[SceneInfo, _Mapping]] = ..., tasks: _Optional[_Iterable[_Union[SceneTask, _Mapping]]] = ..., desc: _Optional[_Union[_timing_pb2.TimerInfo.Desc, _Mapping]] = ...) -> None: ...
    ADD_SCENE: SceneRequest.Method
    COMMON_FIELD_NUMBER: _ClassVar[int]
    DEFAULT: SceneRequest.Method
    DELETE_SCENE: SceneRequest.Method
    METHOD_FIELD_NUMBER: _ClassVar[int]
    MODIFY_SCENE: SceneRequest.Method
    SCENE_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    common: SceneRequest.Common
    method: SceneRequest.Method
    scene: SceneRequest.Scene
    seq: int
    def __init__(self, method: _Optional[_Union[SceneRequest.Method, str]] = ..., seq: _Optional[int] = ..., common: _Optional[_Union[SceneRequest.Common, _Mapping]] = ..., scene: _Optional[_Union[SceneRequest.Scene, _Mapping]] = ...) -> None: ...

class SceneResponse(_message.Message):
    __slots__ = ["infos", "method", "result", "seq"]
    class Result(_message.Message):
        __slots__ = ["err_code", "value"]
        class Value(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        ERR_CODE_FIELD_NUMBER: _ClassVar[int]
        FAILED: SceneResponse.Result.Value
        SUCCESS: SceneResponse.Result.Value
        VALUE_FIELD_NUMBER: _ClassVar[int]
        err_code: int
        value: SceneResponse.Result.Value
        def __init__(self, value: _Optional[_Union[SceneResponse.Result.Value, str]] = ..., err_code: _Optional[int] = ...) -> None: ...
    INFOS_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    infos: _containers.RepeatedCompositeFieldContainer[SceneInfo]
    method: SceneRequest.Method
    result: SceneResponse.Result
    seq: int
    def __init__(self, method: _Optional[_Union[SceneRequest.Method, str]] = ..., seq: _Optional[int] = ..., result: _Optional[_Union[SceneResponse.Result, _Mapping]] = ..., infos: _Optional[_Iterable[_Union[SceneInfo, _Mapping]]] = ...) -> None: ...

class SceneTask(_message.Message):
    __slots__ = ["all_rooms", "current_room", "index", "type"]
    class CleanMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class AllRooms(_message.Message):
        __slots__ = ["general", "mode"]
        GENERAL_FIELD_NUMBER: _ClassVar[int]
        MODE_FIELD_NUMBER: _ClassVar[int]
        general: SceneTask.General
        mode: SceneTask.CleanMode
        def __init__(self, mode: _Optional[_Union[SceneTask.CleanMode, str]] = ..., general: _Optional[_Union[SceneTask.General, _Mapping]] = ...) -> None: ...
    class CurrentRoom(_message.Message):
        __slots__ = ["mode", "units"]
        class Unit(_message.Message):
            __slots__ = ["general", "room_clean", "zone_clean"]
            class RoomClean(_message.Message):
                __slots__ = ["room_id", "room_scene"]
                ROOM_ID_FIELD_NUMBER: _ClassVar[int]
                ROOM_SCENE_FIELD_NUMBER: _ClassVar[int]
                room_id: int
                room_scene: _common_pb2.RoomScene
                def __init__(self, room_id: _Optional[int] = ..., room_scene: _Optional[_Union[_common_pb2.RoomScene, _Mapping]] = ...) -> None: ...
            class ZoneClean(_message.Message):
                __slots__ = ["quadrangle"]
                QUADRANGLE_FIELD_NUMBER: _ClassVar[int]
                quadrangle: _common_pb2.Quadrangle
                def __init__(self, quadrangle: _Optional[_Union[_common_pb2.Quadrangle, _Mapping]] = ...) -> None: ...
            GENERAL_FIELD_NUMBER: _ClassVar[int]
            ROOM_CLEAN_FIELD_NUMBER: _ClassVar[int]
            ZONE_CLEAN_FIELD_NUMBER: _ClassVar[int]
            general: SceneTask.General
            room_clean: SceneTask.CurrentRoom.Unit.RoomClean
            zone_clean: SceneTask.CurrentRoom.Unit.ZoneClean
            def __init__(self, general: _Optional[_Union[SceneTask.General, _Mapping]] = ..., room_clean: _Optional[_Union[SceneTask.CurrentRoom.Unit.RoomClean, _Mapping]] = ..., zone_clean: _Optional[_Union[SceneTask.CurrentRoom.Unit.ZoneClean, _Mapping]] = ...) -> None: ...
        MODE_FIELD_NUMBER: _ClassVar[int]
        UNITS_FIELD_NUMBER: _ClassVar[int]
        mode: SceneTask.CleanMode
        units: _containers.RepeatedCompositeFieldContainer[SceneTask.CurrentRoom.Unit]
        def __init__(self, mode: _Optional[_Union[SceneTask.CleanMode, str]] = ..., units: _Optional[_Iterable[_Union[SceneTask.CurrentRoom.Unit, _Mapping]]] = ...) -> None: ...
    class General(_message.Message):
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
        def __init__(self, clean_type: _Optional[_Union[_clean_param_pb2.CleanType, _Mapping]] = ..., clean_times: _Optional[int] = ..., fan: _Optional[_Union[_clean_param_pb2.Fan, _Mapping]] = ..., mop_mode: _Optional[_Union[_clean_param_pb2.MopMode, _Mapping]] = ..., clean_extent: _Optional[_Union[_clean_param_pb2.CleanExtent, _Mapping]] = ...) -> None: ...
    ALL_ROOMS: SceneTask.Type
    ALL_ROOMS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_ROOM: SceneTask.Type
    CURRENT_ROOM_FIELD_NUMBER: _ClassVar[int]
    GENERAL: SceneTask.CleanMode
    INDEX_FIELD_NUMBER: _ClassVar[int]
    SMART: SceneTask.CleanMode
    TYPE_FIELD_NUMBER: _ClassVar[int]
    all_rooms: SceneTask.AllRooms
    current_room: SceneTask.CurrentRoom
    index: int
    type: SceneTask.Type
    def __init__(self, index: _Optional[int] = ..., type: _Optional[_Union[SceneTask.Type, str]] = ..., current_room: _Optional[_Union[SceneTask.CurrentRoom, _Mapping]] = ..., all_rooms: _Optional[_Union[SceneTask.AllRooms, _Mapping]] = ...) -> None: ...
