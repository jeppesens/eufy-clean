from typing import ClassVar as _ClassVar
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message

from ...proto.cloud import common_pb2 as _common_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class DebugRequest(_message.Message):
    __slots__ = ["capture_sw", "fault_report", "image_feedback", "log_sw", "toggle_mop_raise", "toggle_mop_spin"]
    class FaultReport(_message.Message):
        __slots__ = ["seq"]
        SEQ_FIELD_NUMBER: _ClassVar[int]
        seq: int
        def __init__(self, seq: _Optional[int] = ...) -> None: ...
    class ImageFeedback(_message.Message):
        __slots__ = ["object_type", "photo_id"]
        OBJECT_TYPE_FIELD_NUMBER: _ClassVar[int]
        PHOTO_ID_FIELD_NUMBER: _ClassVar[int]
        object_type: str
        photo_id: str
        def __init__(self, object_type: _Optional[str] = ..., photo_id: _Optional[str] = ...) -> None: ...
    CAPTURE_SW_FIELD_NUMBER: _ClassVar[int]
    FAULT_REPORT_FIELD_NUMBER: _ClassVar[int]
    IMAGE_FEEDBACK_FIELD_NUMBER: _ClassVar[int]
    LOG_SW_FIELD_NUMBER: _ClassVar[int]
    TOGGLE_MOP_RAISE_FIELD_NUMBER: _ClassVar[int]
    TOGGLE_MOP_SPIN_FIELD_NUMBER: _ClassVar[int]
    capture_sw: _common_pb2.Switch
    fault_report: DebugRequest.FaultReport
    image_feedback: DebugRequest.ImageFeedback
    log_sw: _common_pb2.Switch
    toggle_mop_raise: _common_pb2.Switch
    toggle_mop_spin: _common_pb2.Switch
    def __init__(self, log_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., fault_report: _Optional[_Union[DebugRequest.FaultReport, _Mapping]] = ..., capture_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., image_feedback: _Optional[_Union[DebugRequest.ImageFeedback, _Mapping]] = ..., toggle_mop_raise: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., toggle_mop_spin: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ...) -> None: ...

class DebugResponse(_message.Message):
    __slots__ = ["capture_sw", "log_sw", "update_info", "webtty_info"]
    class UpdateInfo(_message.Message):
        __slots__ = ["err_code"]
        ERR_CODE_FIELD_NUMBER: _ClassVar[int]
        err_code: int
        def __init__(self, err_code: _Optional[int] = ...) -> None: ...
    class WebTtyInfo(_message.Message):
        __slots__ = ["connection_data"]
        CONNECTION_DATA_FIELD_NUMBER: _ClassVar[int]
        connection_data: str
        def __init__(self, connection_data: _Optional[str] = ...) -> None: ...
    CAPTURE_SW_FIELD_NUMBER: _ClassVar[int]
    LOG_SW_FIELD_NUMBER: _ClassVar[int]
    UPDATE_INFO_FIELD_NUMBER: _ClassVar[int]
    WEBTTY_INFO_FIELD_NUMBER: _ClassVar[int]
    capture_sw: _common_pb2.Switch
    log_sw: _common_pb2.Switch
    update_info: DebugResponse.UpdateInfo
    webtty_info: DebugResponse.WebTtyInfo
    def __init__(self, log_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., update_info: _Optional[_Union[DebugResponse.UpdateInfo, _Mapping]] = ..., webtty_info: _Optional[_Union[DebugResponse.WebTtyInfo, _Mapping]] = ..., capture_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ...) -> None: ...
