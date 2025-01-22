from proto.cloud import version_pb2 as _version_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AppInfo(_message.Message):
    __slots__ = ["app_function", "app_version", "data_center", "family_id", "platform", "time_zone_id", "user_id"]
    class DataCenter(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Platform(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    APP_FUNCTION_FIELD_NUMBER: _ClassVar[int]
    APP_VERSION_FIELD_NUMBER: _ClassVar[int]
    AY: AppInfo.DataCenter
    AZ: AppInfo.DataCenter
    DATA_CENTER_FIELD_NUMBER: _ClassVar[int]
    EU: AppInfo.DataCenter
    FAMILY_ID_FIELD_NUMBER: _ClassVar[int]
    PF_ANDROID: AppInfo.Platform
    PF_CLOUD: AppInfo.Platform
    PF_IOS: AppInfo.Platform
    PF_OTHER: AppInfo.Platform
    PLATFORM_FIELD_NUMBER: _ClassVar[int]
    TIME_ZONE_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    app_function: _version_pb2.AppFunction
    app_version: str
    data_center: AppInfo.DataCenter
    family_id: str
    platform: AppInfo.Platform
    time_zone_id: str
    user_id: str
    def __init__(self, platform: _Optional[_Union[AppInfo.Platform, str]] = ..., app_version: _Optional[str] = ..., family_id: _Optional[str] = ..., user_id: _Optional[str] = ..., data_center: _Optional[_Union[AppInfo.DataCenter, str]] = ..., app_function: _Optional[_Union[_version_pb2.AppFunction, _Mapping]] = ..., time_zone_id: _Optional[str] = ...) -> None: ...

class DeviceInfo(_message.Message):
    __slots__ = ["device_mac", "hardware", "last_user_id", "product_name", "proto_info", "software", "station", "video_sn", "wifi_ip", "wifi_name"]
    class Station(_message.Message):
        __slots__ = ["hardware", "software"]
        HARDWARE_FIELD_NUMBER: _ClassVar[int]
        SOFTWARE_FIELD_NUMBER: _ClassVar[int]
        hardware: int
        software: str
        def __init__(self, software: _Optional[str] = ..., hardware: _Optional[int] = ...) -> None: ...
    DEVICE_MAC_FIELD_NUMBER: _ClassVar[int]
    HARDWARE_FIELD_NUMBER: _ClassVar[int]
    LAST_USER_ID_FIELD_NUMBER: _ClassVar[int]
    PRODUCT_NAME_FIELD_NUMBER: _ClassVar[int]
    PROTO_INFO_FIELD_NUMBER: _ClassVar[int]
    SOFTWARE_FIELD_NUMBER: _ClassVar[int]
    STATION_FIELD_NUMBER: _ClassVar[int]
    VIDEO_SN_FIELD_NUMBER: _ClassVar[int]
    WIFI_IP_FIELD_NUMBER: _ClassVar[int]
    WIFI_NAME_FIELD_NUMBER: _ClassVar[int]
    device_mac: str
    hardware: int
    last_user_id: str
    product_name: str
    proto_info: _version_pb2.ProtoInfo
    software: str
    station: DeviceInfo.Station
    video_sn: str
    wifi_ip: str
    wifi_name: str
    def __init__(self, product_name: _Optional[str] = ..., video_sn: _Optional[str] = ..., device_mac: _Optional[str] = ..., software: _Optional[str] = ..., hardware: _Optional[int] = ..., wifi_name: _Optional[str] = ..., wifi_ip: _Optional[str] = ..., last_user_id: _Optional[str] = ..., station: _Optional[_Union[DeviceInfo.Station, _Mapping]] = ..., proto_info: _Optional[_Union[_version_pb2.ProtoInfo, _Mapping]] = ...) -> None: ...
