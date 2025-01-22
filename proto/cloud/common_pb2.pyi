from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Active(_message.Message):
    __slots__ = ["value"]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    value: bool
    def __init__(self, value: bool = ...) -> None: ...

class Empty(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class Floor(_message.Message):
    __slots__ = ["type"]
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    BLANKET: Floor.Type
    CERAMIC: Floor.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    UNKNOW: Floor.Type
    WOOD: Floor.Type
    type: Floor.Type
    def __init__(self, type: _Optional[_Union[Floor.Type, str]] = ...) -> None: ...

class Line(_message.Message):
    __slots__ = ["p0", "p1"]
    P0_FIELD_NUMBER: _ClassVar[int]
    P1_FIELD_NUMBER: _ClassVar[int]
    p0: Point
    p1: Point
    def __init__(self, p0: _Optional[_Union[Point, _Mapping]] = ..., p1: _Optional[_Union[Point, _Mapping]] = ...) -> None: ...

class Numerical(_message.Message):
    __slots__ = ["value"]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    value: int
    def __init__(self, value: _Optional[int] = ...) -> None: ...

class Point(_message.Message):
    __slots__ = ["x", "y"]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    x: int
    y: int
    def __init__(self, x: _Optional[int] = ..., y: _Optional[int] = ...) -> None: ...

class Polygon(_message.Message):
    __slots__ = ["points"]
    POINTS_FIELD_NUMBER: _ClassVar[int]
    points: _containers.RepeatedCompositeFieldContainer[Point]
    def __init__(self, points: _Optional[_Iterable[_Union[Point, _Mapping]]] = ...) -> None: ...

class Pose(_message.Message):
    __slots__ = ["theta", "x", "y"]
    THETA_FIELD_NUMBER: _ClassVar[int]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    theta: int
    x: int
    y: int
    def __init__(self, x: _Optional[int] = ..., y: _Optional[int] = ..., theta: _Optional[int] = ...) -> None: ...

class Quadrangle(_message.Message):
    __slots__ = ["p0", "p1", "p2", "p3"]
    P0_FIELD_NUMBER: _ClassVar[int]
    P1_FIELD_NUMBER: _ClassVar[int]
    P2_FIELD_NUMBER: _ClassVar[int]
    P3_FIELD_NUMBER: _ClassVar[int]
    p0: Point
    p1: Point
    p2: Point
    p3: Point
    def __init__(self, p0: _Optional[_Union[Point, _Mapping]] = ..., p1: _Optional[_Union[Point, _Mapping]] = ..., p2: _Optional[_Union[Point, _Mapping]] = ..., p3: _Optional[_Union[Point, _Mapping]] = ...) -> None: ...

class RoomScene(_message.Message):
    __slots__ = ["index", "type"]
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Index(_message.Message):
        __slots__ = ["value"]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        value: int
        def __init__(self, value: _Optional[int] = ...) -> None: ...
    BEDROOM: RoomScene.Type
    CORRIDOR: RoomScene.Type
    DININGROOM: RoomScene.Type
    INDEX_FIELD_NUMBER: _ClassVar[int]
    KITCHEN: RoomScene.Type
    LIVINGROOM: RoomScene.Type
    RESTROOM: RoomScene.Type
    STUDYROOM: RoomScene.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    UNKNOW: RoomScene.Type
    index: RoomScene.Index
    type: RoomScene.Type
    def __init__(self, type: _Optional[_Union[RoomScene.Type, str]] = ..., index: _Optional[_Union[RoomScene.Index, _Mapping]] = ...) -> None: ...

class Switch(_message.Message):
    __slots__ = ["value"]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    value: bool
    def __init__(self, value: bool = ...) -> None: ...
