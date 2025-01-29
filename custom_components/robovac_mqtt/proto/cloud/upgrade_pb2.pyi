from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class QueryUpgradeStatus(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class UpgradeStatus(_message.Message):
    __slots__ = ["error", "progress", "status"]
    class Error(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Status(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    AP_INSTALL_FAILED: UpgradeStatus.Error
    BATTERY_NOT_ENOUGH: UpgradeStatus.Error
    DOWNLOADING: UpgradeStatus.Status
    DOWNLOAD_COMPLETE: UpgradeStatus.Status
    DOWNLOAD_FAILED: UpgradeStatus.Status
    ERROR_FIELD_NUMBER: _ClassVar[int]
    IDLE: UpgradeStatus.Status
    INSTALLING: UpgradeStatus.Status
    INSTALL_COMPLETE: UpgradeStatus.Status
    INSTALL_FAILED: UpgradeStatus.Status
    MCU_INSTALL_FAILED: UpgradeStatus.Error
    NONE: UpgradeStatus.Error
    NOT_IN_STATION: UpgradeStatus.Error
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    STATION_INSTALL_FAILED: UpgradeStatus.Error
    STATION_NOT_CONNECTED: UpgradeStatus.Error
    STATUS_FIELD_NUMBER: _ClassVar[int]
    error: str
    progress: int
    status: UpgradeStatus.Status
    def __init__(self, status: _Optional[_Union[UpgradeStatus.Status, str]] = ..., progress: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...
