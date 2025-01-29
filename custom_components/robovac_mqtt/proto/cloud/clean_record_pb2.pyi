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
from ...proto.cloud import p2pdata_pb2 as _p2pdata_pb2
from ...proto.cloud import stream_pb2 as _stream_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class CleanRecordData(_message.Message):
    __slots__ = ["map", "map_p2p", "obstacle_info", "path_data", "path_data_v2", "path_p2p", "restricted_zone", "room_outline", "room_params", "temp_data"]
    class PathData(_message.Message):
        __slots__ = ["points"]
        POINTS_FIELD_NUMBER: _ClassVar[int]
        points: _containers.RepeatedCompositeFieldContainer[_stream_pb2.PathPoint]
        def __init__(self, points: _Optional[_Iterable[_Union[_stream_pb2.PathPoint, _Mapping]]] = ...) -> None: ...
    MAP_FIELD_NUMBER: _ClassVar[int]
    MAP_P2P_FIELD_NUMBER: _ClassVar[int]
    OBSTACLE_INFO_FIELD_NUMBER: _ClassVar[int]
    PATH_DATA_FIELD_NUMBER: _ClassVar[int]
    PATH_DATA_V2_FIELD_NUMBER: _ClassVar[int]
    PATH_P2P_FIELD_NUMBER: _ClassVar[int]
    RESTRICTED_ZONE_FIELD_NUMBER: _ClassVar[int]
    ROOM_OUTLINE_FIELD_NUMBER: _ClassVar[int]
    ROOM_PARAMS_FIELD_NUMBER: _ClassVar[int]
    TEMP_DATA_FIELD_NUMBER: _ClassVar[int]
    map: _stream_pb2.Map
    map_p2p: _p2pdata_pb2.CompleteMap
    obstacle_info: _stream_pb2.ObstacleInfo
    path_data: bytes
    path_data_v2: CleanRecordData.PathData
    path_p2p: _p2pdata_pb2.CompletePath
    restricted_zone: _stream_pb2.RestrictedZone
    room_outline: _stream_pb2.RoomOutline
    room_params: _stream_pb2.RoomParams
    temp_data: _stream_pb2.TemporaryData
    def __init__(self, restricted_zone: _Optional[_Union[_stream_pb2.RestrictedZone, _Mapping]] = ..., temp_data: _Optional[_Union[_stream_pb2.TemporaryData, _Mapping]] = ..., room_params: _Optional[_Union[_stream_pb2.RoomParams, _Mapping]] = ..., path_data: _Optional[bytes] = ..., map: _Optional[_Union[_stream_pb2.Map, _Mapping]] = ..., room_outline: _Optional[_Union[_stream_pb2.RoomOutline, _Mapping]] = ..., obstacle_info: _Optional[_Union[_stream_pb2.ObstacleInfo, _Mapping]] = ..., path_data_v2: _Optional[_Union[CleanRecordData.PathData, _Mapping]] = ..., map_p2p: _Optional[_Union[_p2pdata_pb2.CompleteMap, _Mapping]] = ..., path_p2p: _Optional[_Union[_p2pdata_pb2.CompletePath, _Mapping]] = ...) -> None: ...

class CleanRecordDesc(_message.Message):
    __slots__ = ["area", "clean_type", "duration", "end_time", "extra", "finish_reason", "start_time"]
    class FinishReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Extra(_message.Message):
        __slots__ = ["error_code", "mode", "mus", "prompt_code"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        AUTO: CleanRecordDesc.Extra.Mode
        ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
        MODE_FIELD_NUMBER: _ClassVar[int]
        MUS_FIELD_NUMBER: _ClassVar[int]
        PROMPT_CODE_FIELD_NUMBER: _ClassVar[int]
        SCHEDULE_AUTO_CLEAN: CleanRecordDesc.Extra.Mode
        SCHEDULE_ROOMS_CLEAN: CleanRecordDesc.Extra.Mode
        SELECT_ROOM: CleanRecordDesc.Extra.Mode
        SELECT_ZONE: CleanRecordDesc.Extra.Mode
        SPOT: CleanRecordDesc.Extra.Mode
        error_code: int
        mode: CleanRecordDesc.Extra.Mode
        mus: int
        prompt_code: int
        def __init__(self, mode: _Optional[_Union[CleanRecordDesc.Extra.Mode, str]] = ..., mus: _Optional[int] = ..., error_code: _Optional[int] = ..., prompt_code: _Optional[int] = ...) -> None: ...
    AREA_FIELD_NUMBER: _ClassVar[int]
    CLEAN_TYPE_FIELD_NUMBER: _ClassVar[int]
    COMPLETED: CleanRecordDesc.FinishReason
    DURATION_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    EXCEPTION: CleanRecordDesc.FinishReason
    EXTRA_FIELD_NUMBER: _ClassVar[int]
    FINISH_REASON_FIELD_NUMBER: _ClassVar[int]
    LOW_POWER: CleanRecordDesc.FinishReason
    MANUDAL: CleanRecordDesc.FinishReason
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    area: int
    clean_type: _clean_param_pb2.CleanType
    duration: int
    end_time: int
    extra: CleanRecordDesc.Extra
    finish_reason: CleanRecordDesc.FinishReason
    start_time: int
    def __init__(self, start_time: _Optional[int] = ..., end_time: _Optional[int] = ..., duration: _Optional[int] = ..., area: _Optional[int] = ..., clean_type: _Optional[_Union[_clean_param_pb2.CleanType, _Mapping]] = ..., finish_reason: _Optional[_Union[CleanRecordDesc.FinishReason, str]] = ..., extra: _Optional[_Union[CleanRecordDesc.Extra, _Mapping]] = ...) -> None: ...

class CruiseRecordData(_message.Message):
    __slots__ = ["cruise_data", "map", "map_p2p", "obstacle_info", "path_data", "path_p2p", "restricted_zone", "room_outline", "room_params", "temp_data"]
    CRUISE_DATA_FIELD_NUMBER: _ClassVar[int]
    MAP_FIELD_NUMBER: _ClassVar[int]
    MAP_P2P_FIELD_NUMBER: _ClassVar[int]
    OBSTACLE_INFO_FIELD_NUMBER: _ClassVar[int]
    PATH_DATA_FIELD_NUMBER: _ClassVar[int]
    PATH_P2P_FIELD_NUMBER: _ClassVar[int]
    RESTRICTED_ZONE_FIELD_NUMBER: _ClassVar[int]
    ROOM_OUTLINE_FIELD_NUMBER: _ClassVar[int]
    ROOM_PARAMS_FIELD_NUMBER: _ClassVar[int]
    TEMP_DATA_FIELD_NUMBER: _ClassVar[int]
    cruise_data: _stream_pb2.CruiseData
    map: _stream_pb2.Map
    map_p2p: _p2pdata_pb2.CompleteMap
    obstacle_info: _stream_pb2.ObstacleInfo
    path_data: bytes
    path_p2p: _p2pdata_pb2.CompletePath
    restricted_zone: _stream_pb2.RestrictedZone
    room_outline: _stream_pb2.RoomOutline
    room_params: _stream_pb2.RoomParams
    temp_data: _stream_pb2.TemporaryData
    def __init__(self, restricted_zone: _Optional[_Union[_stream_pb2.RestrictedZone, _Mapping]] = ..., temp_data: _Optional[_Union[_stream_pb2.TemporaryData, _Mapping]] = ..., room_params: _Optional[_Union[_stream_pb2.RoomParams, _Mapping]] = ..., obstacle_info: _Optional[_Union[_stream_pb2.ObstacleInfo, _Mapping]] = ..., path_data: _Optional[bytes] = ..., cruise_data: _Optional[_Union[_stream_pb2.CruiseData, _Mapping]] = ..., map: _Optional[_Union[_stream_pb2.Map, _Mapping]] = ..., room_outline: _Optional[_Union[_stream_pb2.RoomOutline, _Mapping]] = ..., map_p2p: _Optional[_Union[_p2pdata_pb2.CompleteMap, _Mapping]] = ..., path_p2p: _Optional[_Union[_p2pdata_pb2.CompletePath, _Mapping]] = ...) -> None: ...

class CruiseRecordDesc(_message.Message):
    __slots__ = ["duration", "end_time", "extra", "finish_reason", "start_time"]
    class FinishReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Extra(_message.Message):
        __slots__ = ["mode"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        GLOBAL_CRUISE: CruiseRecordDesc.Extra.Mode
        MODE_FIELD_NUMBER: _ClassVar[int]
        POINT_CRUISE: CruiseRecordDesc.Extra.Mode
        SCHEDULE_CRUISE: CruiseRecordDesc.Extra.Mode
        ZONES_CRUISE: CruiseRecordDesc.Extra.Mode
        mode: CruiseRecordDesc.Extra.Mode
        def __init__(self, mode: _Optional[_Union[CruiseRecordDesc.Extra.Mode, str]] = ...) -> None: ...
    COMPLETED: CruiseRecordDesc.FinishReason
    DURATION_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    EXCEPTION: CruiseRecordDesc.FinishReason
    EXTRA_FIELD_NUMBER: _ClassVar[int]
    FINISH_REASON_FIELD_NUMBER: _ClassVar[int]
    LOW_POWER: CruiseRecordDesc.FinishReason
    MANUDAL: CruiseRecordDesc.FinishReason
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    duration: int
    end_time: int
    extra: CruiseRecordDesc.Extra
    finish_reason: CruiseRecordDesc.FinishReason
    start_time: int
    def __init__(self, start_time: _Optional[int] = ..., end_time: _Optional[int] = ..., duration: _Optional[int] = ..., finish_reason: _Optional[_Union[CruiseRecordDesc.FinishReason, str]] = ..., extra: _Optional[_Union[CruiseRecordDesc.Extra, _Mapping]] = ...) -> None: ...
