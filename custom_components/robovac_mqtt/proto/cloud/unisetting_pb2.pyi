from typing import ClassVar as _ClassVar
from typing import Iterable as _Iterable
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

from ...proto.cloud import common_pb2 as _common_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class UnisettingRequest(_message.Message):
    __slots__ = ["ai_see", "children_lock", "cruise_continue_sw", "deep_mop_corner_sw", "dust_full_remind", "live_photo_sw", "multi_map_options", "multi_map_sw", "pet_mode_sw", "poop_avoidance_sw", "smart_follow_sw", "suggest_restricted_zone_sw", "water_level_sw", "wifi_setting"]
    class MultiMapOptions(_message.Message):
        __slots__ = ["retain"]
        class Retain(_message.Message):
            __slots__ = ["map_id"]
            MAP_ID_FIELD_NUMBER: _ClassVar[int]
            map_id: _containers.RepeatedScalarFieldContainer[int]
            def __init__(self, map_id: _Optional[_Iterable[int]] = ...) -> None: ...
        RETAIN_FIELD_NUMBER: _ClassVar[int]
        retain: UnisettingRequest.MultiMapOptions.Retain
        def __init__(self, retain: _Optional[_Union[UnisettingRequest.MultiMapOptions.Retain, _Mapping]] = ...) -> None: ...
    class WifiSetting(_message.Message):
        __slots__ = ["deletion"]
        class Deletion(_message.Message):
            __slots__ = ["ssid"]
            SSID_FIELD_NUMBER: _ClassVar[int]
            ssid: _containers.RepeatedScalarFieldContainer[str]
            def __init__(self, ssid: _Optional[_Iterable[str]] = ...) -> None: ...
        DELETION_FIELD_NUMBER: _ClassVar[int]
        deletion: UnisettingRequest.WifiSetting.Deletion
        def __init__(self, deletion: _Optional[_Union[UnisettingRequest.WifiSetting.Deletion, _Mapping]] = ...) -> None: ...
    AI_SEE_FIELD_NUMBER: _ClassVar[int]
    CHILDREN_LOCK_FIELD_NUMBER: _ClassVar[int]
    CRUISE_CONTINUE_SW_FIELD_NUMBER: _ClassVar[int]
    DEEP_MOP_CORNER_SW_FIELD_NUMBER: _ClassVar[int]
    DUST_FULL_REMIND_FIELD_NUMBER: _ClassVar[int]
    LIVE_PHOTO_SW_FIELD_NUMBER: _ClassVar[int]
    MULTI_MAP_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    MULTI_MAP_SW_FIELD_NUMBER: _ClassVar[int]
    PET_MODE_SW_FIELD_NUMBER: _ClassVar[int]
    POOP_AVOIDANCE_SW_FIELD_NUMBER: _ClassVar[int]
    SMART_FOLLOW_SW_FIELD_NUMBER: _ClassVar[int]
    SUGGEST_RESTRICTED_ZONE_SW_FIELD_NUMBER: _ClassVar[int]
    WATER_LEVEL_SW_FIELD_NUMBER: _ClassVar[int]
    WIFI_SETTING_FIELD_NUMBER: _ClassVar[int]
    ai_see: _common_pb2.Switch
    children_lock: _common_pb2.Switch
    cruise_continue_sw: _common_pb2.Switch
    deep_mop_corner_sw: _common_pb2.Switch
    dust_full_remind: _common_pb2.Numerical
    live_photo_sw: _common_pb2.Switch
    multi_map_options: UnisettingRequest.MultiMapOptions
    multi_map_sw: _common_pb2.Switch
    pet_mode_sw: _common_pb2.Switch
    poop_avoidance_sw: _common_pb2.Switch
    smart_follow_sw: _common_pb2.Switch
    suggest_restricted_zone_sw: _common_pb2.Switch
    water_level_sw: _common_pb2.Switch
    wifi_setting: UnisettingRequest.WifiSetting
    def __init__(self, children_lock: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., cruise_continue_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., multi_map_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., ai_see: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., multi_map_options: _Optional[_Union[UnisettingRequest.MultiMapOptions, _Mapping]] = ..., wifi_setting: _Optional[_Union[UnisettingRequest.WifiSetting, _Mapping]] = ..., water_level_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., suggest_restricted_zone_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., deep_mop_corner_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., dust_full_remind: _Optional[_Union[_common_pb2.Numerical, _Mapping]] = ..., live_photo_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., smart_follow_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., poop_avoidance_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., pet_mode_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ...) -> None: ...

class UnisettingResponse(_message.Message):
    __slots__ = ["ai_see", "ap_signal_strength", "children_lock", "cruise_continue_sw", "deep_mop_corner_sw", "dust_full_remind", "live_photo_sw", "multi_map_sw", "pet_mode_sw", "poop_avoidance_sw", "smart_follow_sw", "suggest_restricted_zone_sw", "unistate", "water_level_sw", "wifi_data"]
    AI_SEE_FIELD_NUMBER: _ClassVar[int]
    AP_SIGNAL_STRENGTH_FIELD_NUMBER: _ClassVar[int]
    CHILDREN_LOCK_FIELD_NUMBER: _ClassVar[int]
    CRUISE_CONTINUE_SW_FIELD_NUMBER: _ClassVar[int]
    DEEP_MOP_CORNER_SW_FIELD_NUMBER: _ClassVar[int]
    DUST_FULL_REMIND_FIELD_NUMBER: _ClassVar[int]
    LIVE_PHOTO_SW_FIELD_NUMBER: _ClassVar[int]
    MULTI_MAP_SW_FIELD_NUMBER: _ClassVar[int]
    PET_MODE_SW_FIELD_NUMBER: _ClassVar[int]
    POOP_AVOIDANCE_SW_FIELD_NUMBER: _ClassVar[int]
    SMART_FOLLOW_SW_FIELD_NUMBER: _ClassVar[int]
    SUGGEST_RESTRICTED_ZONE_SW_FIELD_NUMBER: _ClassVar[int]
    UNISTATE_FIELD_NUMBER: _ClassVar[int]
    WATER_LEVEL_SW_FIELD_NUMBER: _ClassVar[int]
    WIFI_DATA_FIELD_NUMBER: _ClassVar[int]
    ai_see: _common_pb2.Switch
    ap_signal_strength: int
    children_lock: _common_pb2.Switch
    cruise_continue_sw: _common_pb2.Switch
    deep_mop_corner_sw: _common_pb2.Switch
    dust_full_remind: _common_pb2.Numerical
    live_photo_sw: _common_pb2.Switch
    multi_map_sw: _common_pb2.Switch
    pet_mode_sw: _common_pb2.Switch
    poop_avoidance_sw: _common_pb2.Switch
    smart_follow_sw: _common_pb2.Switch
    suggest_restricted_zone_sw: _common_pb2.Switch
    unistate: Unistate
    water_level_sw: _common_pb2.Switch
    wifi_data: WifiData
    def __init__(self, children_lock: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., cruise_continue_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., multi_map_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., ai_see: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., water_level_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., suggest_restricted_zone_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., deep_mop_corner_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., dust_full_remind: _Optional[_Union[_common_pb2.Numerical, _Mapping]] = ..., live_photo_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., unistate: _Optional[_Union[Unistate, _Mapping]] = ..., ap_signal_strength: _Optional[int] = ..., wifi_data: _Optional[_Union[WifiData, _Mapping]] = ..., smart_follow_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., poop_avoidance_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., pet_mode_sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ...) -> None: ...

class Unistate(_message.Message):
    __slots__ = ["clean_strategy_version", "custom_clean_mode", "live_map", "map_valid", "mop_holder_state_l", "mop_holder_state_r", "mop_state"]
    class LiveMap(_message.Message):
        __slots__ = ["state_bits"]
        class StateBit(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        BASE: Unistate.LiveMap.StateBit
        KITCHEN: Unistate.LiveMap.StateBit
        PET: Unistate.LiveMap.StateBit
        ROOM: Unistate.LiveMap.StateBit
        STATE_BITS_FIELD_NUMBER: _ClassVar[int]
        state_bits: int
        def __init__(self, state_bits: _Optional[int] = ...) -> None: ...
    CLEAN_STRATEGY_VERSION_FIELD_NUMBER: _ClassVar[int]
    CUSTOM_CLEAN_MODE_FIELD_NUMBER: _ClassVar[int]
    LIVE_MAP_FIELD_NUMBER: _ClassVar[int]
    MAP_VALID_FIELD_NUMBER: _ClassVar[int]
    MOP_HOLDER_STATE_L_FIELD_NUMBER: _ClassVar[int]
    MOP_HOLDER_STATE_R_FIELD_NUMBER: _ClassVar[int]
    MOP_STATE_FIELD_NUMBER: _ClassVar[int]
    clean_strategy_version: int
    custom_clean_mode: _common_pb2.Switch
    live_map: Unistate.LiveMap
    map_valid: _common_pb2.Active
    mop_holder_state_l: _common_pb2.Switch
    mop_holder_state_r: _common_pb2.Switch
    mop_state: _common_pb2.Switch
    def __init__(self, mop_holder_state_l: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., mop_holder_state_r: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., custom_clean_mode: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., map_valid: _Optional[_Union[_common_pb2.Active, _Mapping]] = ..., mop_state: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., live_map: _Optional[_Union[Unistate.LiveMap, _Mapping]] = ..., clean_strategy_version: _Optional[int] = ...) -> None: ...

class WifiData(_message.Message):
    __slots__ = ["ap"]
    class Ap(_message.Message):
        __slots__ = ["connection", "frequency", "ssid"]
        class Frequency(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class Connection(_message.Message):
            __slots__ = ["result", "timestamp"]
            class Result(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
                __slots__ = []
            OK: WifiData.Ap.Connection.Result
            PASSWD_ERR: WifiData.Ap.Connection.Result
            RESULT_FIELD_NUMBER: _ClassVar[int]
            TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
            result: WifiData.Ap.Connection.Result
            timestamp: int
            def __init__(self, result: _Optional[_Union[WifiData.Ap.Connection.Result, str]] = ..., timestamp: _Optional[int] = ...) -> None: ...
        CONNECTION_FIELD_NUMBER: _ClassVar[int]
        FREQUENCY_FIELD_NUMBER: _ClassVar[int]
        FREQ_2_4G: WifiData.Ap.Frequency
        FREQ_5G: WifiData.Ap.Frequency
        SSID_FIELD_NUMBER: _ClassVar[int]
        connection: WifiData.Ap.Connection
        frequency: WifiData.Ap.Frequency
        ssid: str
        def __init__(self, ssid: _Optional[str] = ..., frequency: _Optional[_Union[WifiData.Ap.Frequency, str]] = ..., connection: _Optional[_Union[WifiData.Ap.Connection, _Mapping]] = ...) -> None: ...
    AP_FIELD_NUMBER: _ClassVar[int]
    ap: _containers.RepeatedCompositeFieldContainer[WifiData.Ap]
    def __init__(self, ap: _Optional[_Iterable[_Union[WifiData.Ap, _Mapping]]] = ...) -> None: ...
