from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Alarm(_message.Message):
    __slots__ = ["hours", "minutes", "repetition", "week_info"]
    HOURS_FIELD_NUMBER: _ClassVar[int]
    MINUTES_FIELD_NUMBER: _ClassVar[int]
    REPETITION_FIELD_NUMBER: _ClassVar[int]
    WEEK_INFO_FIELD_NUMBER: _ClassVar[int]
    hours: int
    minutes: int
    repetition: bool
    week_info: int
    def __init__(self, hours: _Optional[int] = ..., minutes: _Optional[int] = ..., repetition: bool = ..., week_info: _Optional[int] = ...) -> None: ...

class SyncTime(_message.Message):
    __slots__ = ["day", "hours", "minutes", "month", "seconds", "weekday", "year"]
    DAY_FIELD_NUMBER: _ClassVar[int]
    HOURS_FIELD_NUMBER: _ClassVar[int]
    MINUTES_FIELD_NUMBER: _ClassVar[int]
    MONTH_FIELD_NUMBER: _ClassVar[int]
    SECONDS_FIELD_NUMBER: _ClassVar[int]
    WEEKDAY_FIELD_NUMBER: _ClassVar[int]
    YEAR_FIELD_NUMBER: _ClassVar[int]
    day: int
    hours: int
    minutes: int
    month: int
    seconds: int
    weekday: int
    year: int
    def __init__(self, year: _Optional[int] = ..., month: _Optional[int] = ..., day: _Optional[int] = ..., weekday: _Optional[int] = ..., hours: _Optional[int] = ..., minutes: _Optional[int] = ..., seconds: _Optional[int] = ...) -> None: ...
