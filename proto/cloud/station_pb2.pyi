from proto.cloud import common_pb2 as _common_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AutoActionCfg(_message.Message):
    __slots__ = ["collectdust", "collectdust_v2", "cut_hair", "detergent", "dry", "make_disinfectant", "self_purifying", "wash"]
    COLLECTDUST_FIELD_NUMBER: _ClassVar[int]
    COLLECTDUST_V2_FIELD_NUMBER: _ClassVar[int]
    CUT_HAIR_FIELD_NUMBER: _ClassVar[int]
    DETERGENT_FIELD_NUMBER: _ClassVar[int]
    DRY_FIELD_NUMBER: _ClassVar[int]
    MAKE_DISINFECTANT_FIELD_NUMBER: _ClassVar[int]
    SELF_PURIFYING_FIELD_NUMBER: _ClassVar[int]
    WASH_FIELD_NUMBER: _ClassVar[int]
    collectdust: CollectDustCfg
    collectdust_v2: CollectDustCfgV2
    cut_hair: CutHairCfg
    detergent: bool
    dry: DryCfg
    make_disinfectant: bool
    self_purifying: SelfPurifyingCfg
    wash: WashCfg
    def __init__(self, wash: _Optional[_Union[WashCfg, _Mapping]] = ..., dry: _Optional[_Union[DryCfg, _Mapping]] = ..., collectdust: _Optional[_Union[CollectDustCfg, _Mapping]] = ..., detergent: bool = ..., make_disinfectant: bool = ..., collectdust_v2: _Optional[_Union[CollectDustCfgV2, _Mapping]] = ..., cut_hair: _Optional[_Union[CutHairCfg, _Mapping]] = ..., self_purifying: _Optional[_Union[SelfPurifyingCfg, _Mapping]] = ...) -> None: ...

class CollectDustCfg(_message.Message):
    __slots__ = ["cfg"]
    class Cfg(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    CFG_FIELD_NUMBER: _ClassVar[int]
    CLOSE: CollectDustCfg.Cfg
    ONCE: CollectDustCfg.Cfg
    TWICE: CollectDustCfg.Cfg
    cfg: CollectDustCfg.Cfg
    def __init__(self, cfg: _Optional[_Union[CollectDustCfg.Cfg, str]] = ...) -> None: ...

class CollectDustCfgV2(_message.Message):
    __slots__ = ["mode", "sw"]
    class Mode(_message.Message):
        __slots__ = ["task", "time", "value"]
        class Value(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        BY_TASK: CollectDustCfgV2.Mode.Value
        BY_TIME: CollectDustCfgV2.Mode.Value
        TASK_FIELD_NUMBER: _ClassVar[int]
        TIME_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        task: int
        time: int
        value: CollectDustCfgV2.Mode.Value
        def __init__(self, value: _Optional[_Union[CollectDustCfgV2.Mode.Value, str]] = ..., task: _Optional[int] = ..., time: _Optional[int] = ...) -> None: ...
    MODE_FIELD_NUMBER: _ClassVar[int]
    SW_FIELD_NUMBER: _ClassVar[int]
    mode: CollectDustCfgV2.Mode
    sw: _common_pb2.Switch
    def __init__(self, sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ..., mode: _Optional[_Union[CollectDustCfgV2.Mode, _Mapping]] = ...) -> None: ...

class CutHairCfg(_message.Message):
    __slots__ = ["sw"]
    SW_FIELD_NUMBER: _ClassVar[int]
    sw: _common_pb2.Switch
    def __init__(self, sw: _Optional[_Union[_common_pb2.Switch, _Mapping]] = ...) -> None: ...

class DryCfg(_message.Message):
    __slots__ = ["cfg", "duration"]
    class Cfg(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    CFG_FIELD_NUMBER: _ClassVar[int]
    CLOSE: DryCfg.Cfg
    DURATION_FIELD_NUMBER: _ClassVar[int]
    QUICK: DryCfg.Cfg
    STANDARD: DryCfg.Cfg
    cfg: DryCfg.Cfg
    duration: Duration
    def __init__(self, cfg: _Optional[_Union[DryCfg.Cfg, str]] = ..., duration: _Optional[_Union[Duration, _Mapping]] = ...) -> None: ...

class Duration(_message.Message):
    __slots__ = ["level"]
    class Level(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    LONG: Duration.Level
    MEDIUM: Duration.Level
    SHORT: Duration.Level
    level: Duration.Level
    def __init__(self, level: _Optional[_Union[Duration.Level, str]] = ...) -> None: ...

class ManualActionCmd(_message.Message):
    __slots__ = ["go_collect_dust", "go_cut_hair", "go_dry", "go_remove_scale", "go_selfcleaning", "go_selfpurifying", "self_maintain"]
    GO_COLLECT_DUST_FIELD_NUMBER: _ClassVar[int]
    GO_CUT_HAIR_FIELD_NUMBER: _ClassVar[int]
    GO_DRY_FIELD_NUMBER: _ClassVar[int]
    GO_REMOVE_SCALE_FIELD_NUMBER: _ClassVar[int]
    GO_SELFCLEANING_FIELD_NUMBER: _ClassVar[int]
    GO_SELFPURIFYING_FIELD_NUMBER: _ClassVar[int]
    SELF_MAINTAIN_FIELD_NUMBER: _ClassVar[int]
    go_collect_dust: bool
    go_cut_hair: bool
    go_dry: bool
    go_remove_scale: bool
    go_selfcleaning: bool
    go_selfpurifying: bool
    self_maintain: bool
    def __init__(self, self_maintain: bool = ..., go_dry: bool = ..., go_collect_dust: bool = ..., go_selfcleaning: bool = ..., go_remove_scale: bool = ..., go_cut_hair: bool = ..., go_selfpurifying: bool = ...) -> None: ...

class SelfPurifyingCfg(_message.Message):
    __slots__ = ["custom_cfg", "energy_saving_cfg", "standard_cfg", "strong_cfg", "type"]
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Config(_message.Message):
        __slots__ = ["frequency", "intensity"]
        class Frequency(_message.Message):
            __slots__ = ["mode", "task", "time"]
            class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
                __slots__ = []
            BY_TASK: SelfPurifyingCfg.Config.Frequency.Mode
            BY_TIME: SelfPurifyingCfg.Config.Frequency.Mode
            MODE_FIELD_NUMBER: _ClassVar[int]
            TASK_FIELD_NUMBER: _ClassVar[int]
            TIME_FIELD_NUMBER: _ClassVar[int]
            mode: SelfPurifyingCfg.Config.Frequency.Mode
            task: int
            time: int
            def __init__(self, mode: _Optional[_Union[SelfPurifyingCfg.Config.Frequency.Mode, str]] = ..., task: _Optional[int] = ..., time: _Optional[int] = ...) -> None: ...
        class Intensity(_message.Message):
            __slots__ = ["level"]
            class Level(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
                __slots__ = []
            HIGH: SelfPurifyingCfg.Config.Intensity.Level
            LEVEL_FIELD_NUMBER: _ClassVar[int]
            LOW: SelfPurifyingCfg.Config.Intensity.Level
            MEDIUM: SelfPurifyingCfg.Config.Intensity.Level
            level: SelfPurifyingCfg.Config.Intensity.Level
            def __init__(self, level: _Optional[_Union[SelfPurifyingCfg.Config.Intensity.Level, str]] = ...) -> None: ...
        FREQUENCY_FIELD_NUMBER: _ClassVar[int]
        INTENSITY_FIELD_NUMBER: _ClassVar[int]
        frequency: SelfPurifyingCfg.Config.Frequency
        intensity: SelfPurifyingCfg.Config.Intensity
        def __init__(self, frequency: _Optional[_Union[SelfPurifyingCfg.Config.Frequency, _Mapping]] = ..., intensity: _Optional[_Union[SelfPurifyingCfg.Config.Intensity, _Mapping]] = ...) -> None: ...
    CUSTOM: SelfPurifyingCfg.Type
    CUSTOM_CFG_FIELD_NUMBER: _ClassVar[int]
    ENERGY_SAVING: SelfPurifyingCfg.Type
    ENERGY_SAVING_CFG_FIELD_NUMBER: _ClassVar[int]
    STANDARD: SelfPurifyingCfg.Type
    STANDARD_CFG_FIELD_NUMBER: _ClassVar[int]
    STRONG: SelfPurifyingCfg.Type
    STRONG_CFG_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    custom_cfg: SelfPurifyingCfg.Config
    energy_saving_cfg: SelfPurifyingCfg.Config
    standard_cfg: SelfPurifyingCfg.Config
    strong_cfg: SelfPurifyingCfg.Config
    type: SelfPurifyingCfg.Type
    def __init__(self, type: _Optional[_Union[SelfPurifyingCfg.Type, str]] = ..., standard_cfg: _Optional[_Union[SelfPurifyingCfg.Config, _Mapping]] = ..., strong_cfg: _Optional[_Union[SelfPurifyingCfg.Config, _Mapping]] = ..., energy_saving_cfg: _Optional[_Union[SelfPurifyingCfg.Config, _Mapping]] = ..., custom_cfg: _Optional[_Union[SelfPurifyingCfg.Config, _Mapping]] = ...) -> None: ...

class StationRequest(_message.Message):
    __slots__ = ["auto_cfg", "manual_cmd"]
    AUTO_CFG_FIELD_NUMBER: _ClassVar[int]
    MANUAL_CMD_FIELD_NUMBER: _ClassVar[int]
    auto_cfg: AutoActionCfg
    manual_cmd: ManualActionCmd
    def __init__(self, auto_cfg: _Optional[_Union[AutoActionCfg, _Mapping]] = ..., manual_cmd: _Optional[_Union[ManualActionCmd, _Mapping]] = ...) -> None: ...

class StationResponse(_message.Message):
    __slots__ = ["auto_cfg_status", "clean_level", "clean_water", "dirty_level", "status"]
    class WaterLevel(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class StationStatus(_message.Message):
        __slots__ = ["clear_water_adding", "collecting_dust", "connected", "cutting_hair", "disinfectant_making", "state", "waste_water_recycling"]
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        CLEAR_WATER_ADDING_FIELD_NUMBER: _ClassVar[int]
        COLLECTING_DUST_FIELD_NUMBER: _ClassVar[int]
        CONNECTED_FIELD_NUMBER: _ClassVar[int]
        CUTTING_HAIR_FIELD_NUMBER: _ClassVar[int]
        DISINFECTANT_MAKING_FIELD_NUMBER: _ClassVar[int]
        DRYING: StationResponse.StationStatus.State
        IDLE: StationResponse.StationStatus.State
        REMOVING_SCALE: StationResponse.StationStatus.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        WASHING: StationResponse.StationStatus.State
        WASTE_WATER_RECYCLING_FIELD_NUMBER: _ClassVar[int]
        clear_water_adding: bool
        collecting_dust: bool
        connected: bool
        cutting_hair: bool
        disinfectant_making: bool
        state: StationResponse.StationStatus.State
        waste_water_recycling: bool
        def __init__(self, connected: bool = ..., state: _Optional[_Union[StationResponse.StationStatus.State, str]] = ..., collecting_dust: bool = ..., clear_water_adding: bool = ..., waste_water_recycling: bool = ..., disinfectant_making: bool = ..., cutting_hair: bool = ...) -> None: ...
    AUTO_CFG_STATUS_FIELD_NUMBER: _ClassVar[int]
    CLEAN_LEVEL_FIELD_NUMBER: _ClassVar[int]
    CLEAN_WATER_FIELD_NUMBER: _ClassVar[int]
    DIRTY_LEVEL_FIELD_NUMBER: _ClassVar[int]
    EMPTY: StationResponse.WaterLevel
    HIGH: StationResponse.WaterLevel
    LOW: StationResponse.WaterLevel
    MEDIUM: StationResponse.WaterLevel
    STATUS_FIELD_NUMBER: _ClassVar[int]
    VERY_LOW: StationResponse.WaterLevel
    auto_cfg_status: AutoActionCfg
    clean_level: StationResponse.WaterLevel
    clean_water: _common_pb2.Numerical
    dirty_level: StationResponse.WaterLevel
    status: StationResponse.StationStatus
    def __init__(self, auto_cfg_status: _Optional[_Union[AutoActionCfg, _Mapping]] = ..., status: _Optional[_Union[StationResponse.StationStatus, _Mapping]] = ..., clean_level: _Optional[_Union[StationResponse.WaterLevel, str]] = ..., dirty_level: _Optional[_Union[StationResponse.WaterLevel, str]] = ..., clean_water: _Optional[_Union[_common_pb2.Numerical, _Mapping]] = ...) -> None: ...

class WashCfg(_message.Message):
    __slots__ = ["cfg", "wash_duration", "wash_freq"]
    class Cfg(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class BackwashFreq(_message.Message):
        __slots__ = ["duration", "mode", "time_or_area"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        ByArea: WashCfg.BackwashFreq.Mode
        ByPartition: WashCfg.BackwashFreq.Mode
        ByTime: WashCfg.BackwashFreq.Mode
        DURATION_FIELD_NUMBER: _ClassVar[int]
        MODE_FIELD_NUMBER: _ClassVar[int]
        TIME_OR_AREA_FIELD_NUMBER: _ClassVar[int]
        duration: Duration
        mode: WashCfg.BackwashFreq.Mode
        time_or_area: _common_pb2.Numerical
        def __init__(self, mode: _Optional[_Union[WashCfg.BackwashFreq.Mode, str]] = ..., duration: _Optional[_Union[Duration, _Mapping]] = ..., time_or_area: _Optional[_Union[_common_pb2.Numerical, _Mapping]] = ...) -> None: ...
    CFG_FIELD_NUMBER: _ClassVar[int]
    CLOSE: WashCfg.Cfg
    STANDARD: WashCfg.Cfg
    WASH_DURATION_FIELD_NUMBER: _ClassVar[int]
    WASH_FREQ_FIELD_NUMBER: _ClassVar[int]
    cfg: WashCfg.Cfg
    wash_duration: Duration
    wash_freq: WashCfg.BackwashFreq
    def __init__(self, wash_freq: _Optional[_Union[WashCfg.BackwashFreq, _Mapping]] = ..., wash_duration: _Optional[_Union[Duration, _Mapping]] = ..., cfg: _Optional[_Union[WashCfg.Cfg, str]] = ...) -> None: ...
