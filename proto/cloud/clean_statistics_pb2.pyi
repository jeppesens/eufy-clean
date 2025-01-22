from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CleanStatistics(_message.Message):
    __slots__ = ["single", "total", "user_total"]
    class Single(_message.Message):
        __slots__ = ["clean_area", "clean_duration"]
        CLEAN_AREA_FIELD_NUMBER: _ClassVar[int]
        CLEAN_DURATION_FIELD_NUMBER: _ClassVar[int]
        clean_area: int
        clean_duration: int
        def __init__(self, clean_duration: _Optional[int] = ..., clean_area: _Optional[int] = ...) -> None: ...
    class Total(_message.Message):
        __slots__ = ["clean_area", "clean_count", "clean_duration"]
        CLEAN_AREA_FIELD_NUMBER: _ClassVar[int]
        CLEAN_COUNT_FIELD_NUMBER: _ClassVar[int]
        CLEAN_DURATION_FIELD_NUMBER: _ClassVar[int]
        clean_area: int
        clean_count: int
        clean_duration: int
        def __init__(self, clean_duration: _Optional[int] = ..., clean_area: _Optional[int] = ..., clean_count: _Optional[int] = ...) -> None: ...
    SINGLE_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    USER_TOTAL_FIELD_NUMBER: _ClassVar[int]
    single: CleanStatistics.Single
    total: CleanStatistics.Total
    user_total: CleanStatistics.Total
    def __init__(self, single: _Optional[_Union[CleanStatistics.Single, _Mapping]] = ..., total: _Optional[_Union[CleanStatistics.Total, _Mapping]] = ..., user_total: _Optional[_Union[CleanStatistics.Total, _Mapping]] = ...) -> None: ...
