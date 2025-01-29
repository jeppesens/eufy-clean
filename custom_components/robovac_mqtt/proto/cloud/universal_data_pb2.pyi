from typing import ClassVar as _ClassVar
from typing import Iterable as _Iterable
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers

from ...proto.cloud import common_pb2 as _common_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class UniversalDataRequest(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class UniversalDataResponse(_message.Message):
    __slots__ = ["cur_map_room"]
    class RoomTable(_message.Message):
        __slots__ = ["data", "map_id"]
        class Data(_message.Message):
            __slots__ = ["id", "name", "scene"]
            ID_FIELD_NUMBER: _ClassVar[int]
            NAME_FIELD_NUMBER: _ClassVar[int]
            SCENE_FIELD_NUMBER: _ClassVar[int]
            id: int
            name: str
            scene: _common_pb2.RoomScene
            def __init__(self, id: _Optional[int] = ..., name: _Optional[str] = ..., scene: _Optional[_Union[_common_pb2.RoomScene, _Mapping]] = ...) -> None: ...
        DATA_FIELD_NUMBER: _ClassVar[int]
        MAP_ID_FIELD_NUMBER: _ClassVar[int]
        data: _containers.RepeatedCompositeFieldContainer[UniversalDataResponse.RoomTable.Data]
        map_id: int
        def __init__(self, map_id: _Optional[int] = ..., data: _Optional[_Iterable[_Union[UniversalDataResponse.RoomTable.Data, _Mapping]]] = ...) -> None: ...
    CUR_MAP_ROOM_FIELD_NUMBER: _ClassVar[int]
    cur_map_room: UniversalDataResponse.RoomTable
    def __init__(self, cur_map_room: _Optional[_Union[UniversalDataResponse.RoomTable, _Mapping]] = ...) -> None: ...
