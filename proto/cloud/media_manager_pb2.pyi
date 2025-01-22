from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class MediaManagerRequest(_message.Message):
    __slots__ = ["bind_media_svc_data", "control", "setting"]
    class BindMediaSvc(_message.Message):
        __slots__ = ["c", "d", "g", "j", "seq", "user_account"]
        C_FIELD_NUMBER: _ClassVar[int]
        D_FIELD_NUMBER: _ClassVar[int]
        G_FIELD_NUMBER: _ClassVar[int]
        J_FIELD_NUMBER: _ClassVar[int]
        SEQ_FIELD_NUMBER: _ClassVar[int]
        USER_ACCOUNT_FIELD_NUMBER: _ClassVar[int]
        c: int
        d: int
        g: str
        j: int
        seq: int
        user_account: str
        def __init__(self, seq: _Optional[int] = ..., c: _Optional[int] = ..., d: _Optional[int] = ..., g: _Optional[str] = ..., j: _Optional[int] = ..., user_account: _Optional[str] = ...) -> None: ...
    class Control(_message.Message):
        __slots__ = ["method", "seq"]
        class Method(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        CAPTURE: MediaManagerRequest.Control.Method
        METHOD_FIELD_NUMBER: _ClassVar[int]
        RECORD_START: MediaManagerRequest.Control.Method
        RECORD_STOP: MediaManagerRequest.Control.Method
        SEQ_FIELD_NUMBER: _ClassVar[int]
        method: MediaManagerRequest.Control.Method
        seq: int
        def __init__(self, method: _Optional[_Union[MediaManagerRequest.Control.Method, str]] = ..., seq: _Optional[int] = ...) -> None: ...
    BIND_MEDIA_SVC_DATA_FIELD_NUMBER: _ClassVar[int]
    CONTROL_FIELD_NUMBER: _ClassVar[int]
    SETTING_FIELD_NUMBER: _ClassVar[int]
    bind_media_svc_data: MediaManagerRequest.BindMediaSvc
    control: MediaManagerRequest.Control
    setting: MediaSetting
    def __init__(self, control: _Optional[_Union[MediaManagerRequest.Control, _Mapping]] = ..., setting: _Optional[_Union[MediaSetting, _Mapping]] = ..., bind_media_svc_data: _Optional[_Union[MediaManagerRequest.BindMediaSvc, _Mapping]] = ...) -> None: ...

class MediaManagerResponse(_message.Message):
    __slots__ = ["bind_media_svc", "control", "setting", "status"]
    class BindMediaSvc(_message.Message):
        __slots__ = ["result", "seq"]
        class Result(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        FAIL: MediaManagerResponse.BindMediaSvc.Result
        RESULT_FIELD_NUMBER: _ClassVar[int]
        SEQ_FIELD_NUMBER: _ClassVar[int]
        SUCCESS: MediaManagerResponse.BindMediaSvc.Result
        result: MediaManagerResponse.BindMediaSvc.Result
        seq: int
        def __init__(self, seq: _Optional[int] = ..., result: _Optional[_Union[MediaManagerResponse.BindMediaSvc.Result, str]] = ...) -> None: ...
    class Control(_message.Message):
        __slots__ = ["file_info", "method", "result", "seq"]
        class Result(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class FileInfo(_message.Message):
            __slots__ = ["filepath", "id"]
            FILEPATH_FIELD_NUMBER: _ClassVar[int]
            ID_FIELD_NUMBER: _ClassVar[int]
            filepath: str
            id: str
            def __init__(self, filepath: _Optional[str] = ..., id: _Optional[str] = ...) -> None: ...
        FAIL: MediaManagerResponse.Control.Result
        FILE_INFO_FIELD_NUMBER: _ClassVar[int]
        METHOD_FIELD_NUMBER: _ClassVar[int]
        RESULT_FIELD_NUMBER: _ClassVar[int]
        SEQ_FIELD_NUMBER: _ClassVar[int]
        SUCCESS: MediaManagerResponse.Control.Result
        file_info: MediaManagerResponse.Control.FileInfo
        method: MediaManagerRequest.Control.Method
        result: MediaManagerResponse.Control.Result
        seq: int
        def __init__(self, method: _Optional[_Union[MediaManagerRequest.Control.Method, str]] = ..., seq: _Optional[int] = ..., result: _Optional[_Union[MediaManagerResponse.Control.Result, str]] = ..., file_info: _Optional[_Union[MediaManagerResponse.Control.FileInfo, _Mapping]] = ...) -> None: ...
    BIND_MEDIA_SVC_FIELD_NUMBER: _ClassVar[int]
    CONTROL_FIELD_NUMBER: _ClassVar[int]
    SETTING_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    bind_media_svc: MediaManagerResponse.BindMediaSvc
    control: MediaManagerResponse.Control
    setting: MediaSetting
    status: MediaStatus
    def __init__(self, control: _Optional[_Union[MediaManagerResponse.Control, _Mapping]] = ..., setting: _Optional[_Union[MediaSetting, _Mapping]] = ..., status: _Optional[_Union[MediaStatus, _Mapping]] = ..., bind_media_svc: _Optional[_Union[MediaManagerResponse.BindMediaSvc, _Mapping]] = ...) -> None: ...

class MediaSetting(_message.Message):
    __slots__ = ["capture", "record", "rt_stream"]
    class Resolution(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Capture(_message.Message):
        __slots__ = ["height", "width"]
        HEIGHT_FIELD_NUMBER: _ClassVar[int]
        WIDTH_FIELD_NUMBER: _ClassVar[int]
        height: int
        width: int
        def __init__(self, width: _Optional[int] = ..., height: _Optional[int] = ...) -> None: ...
    class RTStream(_message.Message):
        __slots__ = ["resolution"]
        RESOLUTION_FIELD_NUMBER: _ClassVar[int]
        resolution: MediaSetting.Resolution
        def __init__(self, resolution: _Optional[_Union[MediaSetting.Resolution, str]] = ...) -> None: ...
    class Record(_message.Message):
        __slots__ = ["bitrate", "resolution"]
        BITRATE_FIELD_NUMBER: _ClassVar[int]
        RESOLUTION_FIELD_NUMBER: _ClassVar[int]
        bitrate: int
        resolution: MediaSetting.Resolution
        def __init__(self, resolution: _Optional[_Union[MediaSetting.Resolution, str]] = ..., bitrate: _Optional[int] = ...) -> None: ...
    CAPTURE_FIELD_NUMBER: _ClassVar[int]
    RECORD_FIELD_NUMBER: _ClassVar[int]
    RT_STREAM_FIELD_NUMBER: _ClassVar[int]
    R_1080P: MediaSetting.Resolution
    R_480P: MediaSetting.Resolution
    R_720P: MediaSetting.Resolution
    capture: MediaSetting.Capture
    record: MediaSetting.Record
    rt_stream: MediaSetting.RTStream
    def __init__(self, rt_stream: _Optional[_Union[MediaSetting.RTStream, _Mapping]] = ..., record: _Optional[_Union[MediaSetting.Record, _Mapping]] = ..., capture: _Optional[_Union[MediaSetting.Capture, _Mapping]] = ...) -> None: ...

class MediaStatus(_message.Message):
    __slots__ = ["bind_state", "photo_space", "state", "storage", "total_space", "video_space"]
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Storage(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    BIND_STATE_FIELD_NUMBER: _ClassVar[int]
    FULL: MediaStatus.Storage
    IDLE: MediaStatus.State
    NORMAL: MediaStatus.Storage
    PHOTO_SPACE_FIELD_NUMBER: _ClassVar[int]
    RECORDING: MediaStatus.State
    STATE_FIELD_NUMBER: _ClassVar[int]
    STORAGE_FIELD_NUMBER: _ClassVar[int]
    THRESHOLD: MediaStatus.Storage
    TOTAL_SPACE_FIELD_NUMBER: _ClassVar[int]
    VIDEO_SPACE_FIELD_NUMBER: _ClassVar[int]
    bind_state: bool
    photo_space: int
    state: MediaStatus.State
    storage: MediaStatus.Storage
    total_space: int
    video_space: int
    def __init__(self, state: _Optional[_Union[MediaStatus.State, str]] = ..., storage: _Optional[_Union[MediaStatus.Storage, str]] = ..., total_space: _Optional[int] = ..., photo_space: _Optional[int] = ..., video_space: _Optional[int] = ..., bind_state: bool = ...) -> None: ...
