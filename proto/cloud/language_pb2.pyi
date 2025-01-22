from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class LanguageRequest(_message.Message):
    __slots__ = ["desc", "selection"]
    class Desc(_message.Message):
        __slots__ = ["md5", "set_id", "size", "url", "version"]
        MD5_FIELD_NUMBER: _ClassVar[int]
        SET_ID_FIELD_NUMBER: _ClassVar[int]
        SIZE_FIELD_NUMBER: _ClassVar[int]
        URL_FIELD_NUMBER: _ClassVar[int]
        VERSION_FIELD_NUMBER: _ClassVar[int]
        md5: str
        set_id: int
        size: int
        url: str
        version: int
        def __init__(self, set_id: _Optional[int] = ..., url: _Optional[str] = ..., md5: _Optional[str] = ..., version: _Optional[int] = ..., size: _Optional[int] = ...) -> None: ...
    class Selection(_message.Message):
        __slots__ = ["value"]
        class Value(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        DEFAULT: LanguageRequest.Selection.Value
        USER: LanguageRequest.Selection.Value
        VALUE_FIELD_NUMBER: _ClassVar[int]
        value: LanguageRequest.Selection.Value
        def __init__(self, value: _Optional[_Union[LanguageRequest.Selection.Value, str]] = ...) -> None: ...
    DESC_FIELD_NUMBER: _ClassVar[int]
    SELECTION_FIELD_NUMBER: _ClassVar[int]
    desc: LanguageRequest.Desc
    selection: LanguageRequest.Selection
    def __init__(self, desc: _Optional[_Union[LanguageRequest.Desc, _Mapping]] = ..., selection: _Optional[_Union[LanguageRequest.Selection, _Mapping]] = ...) -> None: ...

class LanguageResponse(_message.Message):
    __slots__ = ["current_id", "default_id", "set_id", "state", "version"]
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    CURRENT_ID_FIELD_NUMBER: _ClassVar[int]
    DEFAULT_ID_FIELD_NUMBER: _ClassVar[int]
    FAILURE: LanguageResponse.State
    IDLE: LanguageResponse.State
    SET_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    SUCCESS: LanguageResponse.State
    UPDATING: LanguageResponse.State
    VERSION_FIELD_NUMBER: _ClassVar[int]
    current_id: int
    default_id: int
    set_id: int
    state: LanguageResponse.State
    version: int
    def __init__(self, default_id: _Optional[int] = ..., current_id: _Optional[int] = ..., version: _Optional[int] = ..., set_id: _Optional[int] = ..., state: _Optional[_Union[LanguageResponse.State, str]] = ...) -> None: ...
