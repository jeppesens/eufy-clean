from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class WorkStatus(_message.Message):
    __slots__ = ["breakpoint", "charging", "cleaning", "cruisiing", "current_scene", "go_home", "go_wash", "mapping", "mode", "relocating", "roller_brush_cleaning", "smart_follow", "state", "station", "trigger", "upgrading"]
    class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    class Breakpoint(_message.Message):
        __slots__ = ["state"]
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        DOING: WorkStatus.Breakpoint.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        state: WorkStatus.Breakpoint.State
        def __init__(self, state: _Optional[_Union[WorkStatus.Breakpoint.State, str]] = ...) -> None: ...
    class Charging(_message.Message):
        __slots__ = ["state"]
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        ABNORMAL: WorkStatus.Charging.State
        DOING: WorkStatus.Charging.State
        DONE: WorkStatus.Charging.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        state: WorkStatus.Charging.State
        def __init__(self, state: _Optional[_Union[WorkStatus.Charging.State, str]] = ...) -> None: ...
    class Cleaning(_message.Message):
        __slots__ = ["mode", "scheduled_task", "state"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class RunState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        CLEANING: WorkStatus.Cleaning.Mode
        DOING: WorkStatus.Cleaning.RunState
        GOTO_POS: WorkStatus.Cleaning.Mode
        MODE_FIELD_NUMBER: _ClassVar[int]
        PAUSED: WorkStatus.Cleaning.RunState
        POOP_CLEANING: WorkStatus.Cleaning.Mode
        RELOCATING: WorkStatus.Cleaning.Mode
        SCHEDULED_TASK_FIELD_NUMBER: _ClassVar[int]
        STATE_FIELD_NUMBER: _ClassVar[int]
        mode: WorkStatus.Cleaning.Mode
        scheduled_task: bool
        state: WorkStatus.Cleaning.RunState
        def __init__(self, state: _Optional[_Union[WorkStatus.Cleaning.RunState, str]] = ..., mode: _Optional[_Union[WorkStatus.Cleaning.Mode, str]] = ..., scheduled_task: bool = ...) -> None: ...
    class Cruisiing(_message.Message):
        __slots__ = ["mode", "state"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class RunState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        CRUISIING: WorkStatus.Cruisiing.Mode
        DOING: WorkStatus.Cruisiing.RunState
        MODE_FIELD_NUMBER: _ClassVar[int]
        PAUSED: WorkStatus.Cruisiing.RunState
        RELOCATING: WorkStatus.Cruisiing.Mode
        STATE_FIELD_NUMBER: _ClassVar[int]
        mode: WorkStatus.Cruisiing.Mode
        state: WorkStatus.Cruisiing.RunState
        def __init__(self, state: _Optional[_Union[WorkStatus.Cruisiing.RunState, str]] = ..., mode: _Optional[_Union[WorkStatus.Cruisiing.Mode, str]] = ...) -> None: ...
    class GoHome(_message.Message):
        __slots__ = ["mode", "state"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class RunState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        COLLECT_DUST: WorkStatus.GoHome.Mode
        COMPLETE_TASK: WorkStatus.GoHome.Mode
        DOING: WorkStatus.GoHome.RunState
        MODE_FIELD_NUMBER: _ClassVar[int]
        OTHRERS: WorkStatus.GoHome.Mode
        PAUSED: WorkStatus.GoHome.RunState
        STATE_FIELD_NUMBER: _ClassVar[int]
        mode: WorkStatus.GoHome.Mode
        state: WorkStatus.GoHome.RunState
        def __init__(self, state: _Optional[_Union[WorkStatus.GoHome.RunState, str]] = ..., mode: _Optional[_Union[WorkStatus.GoHome.Mode, str]] = ...) -> None: ...
    class GoWash(_message.Message):
        __slots__ = ["mode", "state"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class RunState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        DOING: WorkStatus.GoWash.RunState
        DRYING: WorkStatus.GoWash.Mode
        MODE_FIELD_NUMBER: _ClassVar[int]
        NAVIGATION: WorkStatus.GoWash.Mode
        PAUSED: WorkStatus.GoWash.RunState
        STATE_FIELD_NUMBER: _ClassVar[int]
        WASHING: WorkStatus.GoWash.Mode
        mode: WorkStatus.GoWash.Mode
        state: WorkStatus.GoWash.RunState
        def __init__(self, state: _Optional[_Union[WorkStatus.GoWash.RunState, str]] = ..., mode: _Optional[_Union[WorkStatus.GoWash.Mode, str]] = ...) -> None: ...
    class Mapping(_message.Message):
        __slots__ = ["mode", "state"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class RunState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        DOING: WorkStatus.Mapping.RunState
        MAPPING: WorkStatus.Mapping.Mode
        MODE_FIELD_NUMBER: _ClassVar[int]
        PAUSED: WorkStatus.Mapping.RunState
        RELOCATING: WorkStatus.Mapping.Mode
        STATE_FIELD_NUMBER: _ClassVar[int]
        mode: WorkStatus.Mapping.Mode
        state: WorkStatus.Mapping.RunState
        def __init__(self, state: _Optional[_Union[WorkStatus.Mapping.RunState, str]] = ..., mode: _Optional[_Union[WorkStatus.Mapping.Mode, str]] = ...) -> None: ...
    class Mode(_message.Message):
        __slots__ = ["value"]
        class Value(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        AUTO: WorkStatus.Mode.Value
        FAST_MAPPING: WorkStatus.Mode.Value
        GLOBAL_CRUISE: WorkStatus.Mode.Value
        POINT_CRUISE: WorkStatus.Mode.Value
        SCENE: WorkStatus.Mode.Value
        SELECT_ROOM: WorkStatus.Mode.Value
        SELECT_ZONE: WorkStatus.Mode.Value
        SMART_FOLLOW: WorkStatus.Mode.Value
        SPOT: WorkStatus.Mode.Value
        VALUE_FIELD_NUMBER: _ClassVar[int]
        ZONES_CRUISE: WorkStatus.Mode.Value
        value: WorkStatus.Mode.Value
        def __init__(self, value: _Optional[_Union[WorkStatus.Mode.Value, str]] = ...) -> None: ...
    class Relocating(_message.Message):
        __slots__ = ["state"]
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        DOING: WorkStatus.Relocating.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        state: WorkStatus.Relocating.State
        def __init__(self, state: _Optional[_Union[WorkStatus.Relocating.State, str]] = ...) -> None: ...
    class RollerBrushCleaning(_message.Message):
        __slots__ = ["state"]
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        DOING: WorkStatus.RollerBrushCleaning.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        state: WorkStatus.RollerBrushCleaning.State
        def __init__(self, state: _Optional[_Union[WorkStatus.RollerBrushCleaning.State, str]] = ...) -> None: ...
    class Scene(_message.Message):
        __slots__ = ["elapsed_time", "estimate_time", "id", "name", "task_mode"]
        class TaskMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        AUTO: WorkStatus.Scene.TaskMode
        ELAPSED_TIME_FIELD_NUMBER: _ClassVar[int]
        ESTIMATE_TIME_FIELD_NUMBER: _ClassVar[int]
        ID_FIELD_NUMBER: _ClassVar[int]
        NAME_FIELD_NUMBER: _ClassVar[int]
        SELECT_ROOM: WorkStatus.Scene.TaskMode
        SELECT_ZONE: WorkStatus.Scene.TaskMode
        TASK_MODE_FIELD_NUMBER: _ClassVar[int]
        elapsed_time: int
        estimate_time: int
        id: int
        name: str
        task_mode: WorkStatus.Scene.TaskMode
        def __init__(self, id: _Optional[int] = ..., elapsed_time: _Optional[int] = ..., estimate_time: _Optional[int] = ..., name: _Optional[str] = ..., task_mode: _Optional[_Union[WorkStatus.Scene.TaskMode, str]] = ...) -> None: ...
    class SmartFollow(_message.Message):
        __slots__ = ["area", "elapsed_time", "mode", "state"]
        class Mode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        AREA_FIELD_NUMBER: _ClassVar[int]
        DOING: WorkStatus.SmartFollow.State
        ELAPSED_TIME_FIELD_NUMBER: _ClassVar[int]
        FOLLOWING: WorkStatus.SmartFollow.Mode
        MODE_FIELD_NUMBER: _ClassVar[int]
        SEARCHING: WorkStatus.SmartFollow.Mode
        STATE_FIELD_NUMBER: _ClassVar[int]
        area: int
        elapsed_time: int
        mode: WorkStatus.SmartFollow.Mode
        state: WorkStatus.SmartFollow.State
        def __init__(self, state: _Optional[_Union[WorkStatus.SmartFollow.State, str]] = ..., mode: _Optional[_Union[WorkStatus.SmartFollow.Mode, str]] = ..., elapsed_time: _Optional[int] = ..., area: _Optional[int] = ...) -> None: ...
    class Station(_message.Message):
        __slots__ = ["dust_collection_system", "washing_drying_system", "water_injection_system", "water_tank_state"]
        class DustCollectionSystem(_message.Message):
            __slots__ = ["state"]
            class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
                __slots__ = []
            EMPTYING: WorkStatus.Station.DustCollectionSystem.State
            STATE_FIELD_NUMBER: _ClassVar[int]
            state: WorkStatus.Station.DustCollectionSystem.State
            def __init__(self, state: _Optional[_Union[WorkStatus.Station.DustCollectionSystem.State, str]] = ...) -> None: ...
        class WashingDryingSystem(_message.Message):
            __slots__ = ["state"]
            class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
                __slots__ = []
            DRYING: WorkStatus.Station.WashingDryingSystem.State
            STATE_FIELD_NUMBER: _ClassVar[int]
            WASHING: WorkStatus.Station.WashingDryingSystem.State
            state: WorkStatus.Station.WashingDryingSystem.State
            def __init__(self, state: _Optional[_Union[WorkStatus.Station.WashingDryingSystem.State, str]] = ...) -> None: ...
        class WaterInjectionSystem(_message.Message):
            __slots__ = ["state"]
            class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
                __slots__ = []
            ADDING: WorkStatus.Station.WaterInjectionSystem.State
            EMPTYING: WorkStatus.Station.WaterInjectionSystem.State
            STATE_FIELD_NUMBER: _ClassVar[int]
            state: WorkStatus.Station.WaterInjectionSystem.State
            def __init__(self, state: _Optional[_Union[WorkStatus.Station.WaterInjectionSystem.State, str]] = ...) -> None: ...
        class WaterTankState(_message.Message):
            __slots__ = ["clear_water_adding", "waste_water_recycling"]
            CLEAR_WATER_ADDING_FIELD_NUMBER: _ClassVar[int]
            WASTE_WATER_RECYCLING_FIELD_NUMBER: _ClassVar[int]
            clear_water_adding: bool
            waste_water_recycling: bool
            def __init__(self, clear_water_adding: bool = ..., waste_water_recycling: bool = ...) -> None: ...
        DUST_COLLECTION_SYSTEM_FIELD_NUMBER: _ClassVar[int]
        WASHING_DRYING_SYSTEM_FIELD_NUMBER: _ClassVar[int]
        WATER_INJECTION_SYSTEM_FIELD_NUMBER: _ClassVar[int]
        WATER_TANK_STATE_FIELD_NUMBER: _ClassVar[int]
        dust_collection_system: WorkStatus.Station.DustCollectionSystem
        washing_drying_system: WorkStatus.Station.WashingDryingSystem
        water_injection_system: WorkStatus.Station.WaterInjectionSystem
        water_tank_state: WorkStatus.Station.WaterTankState
        def __init__(self, water_injection_system: _Optional[_Union[WorkStatus.Station.WaterInjectionSystem, _Mapping]] = ..., dust_collection_system: _Optional[_Union[WorkStatus.Station.DustCollectionSystem, _Mapping]] = ..., washing_drying_system: _Optional[_Union[WorkStatus.Station.WashingDryingSystem, _Mapping]] = ..., water_tank_state: _Optional[_Union[WorkStatus.Station.WaterTankState, _Mapping]] = ...) -> None: ...
    class Trigger(_message.Message):
        __slots__ = ["source"]
        class Source(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        APP: WorkStatus.Trigger.Source
        KEY: WorkStatus.Trigger.Source
        REMOTE_CTRL: WorkStatus.Trigger.Source
        ROBOT: WorkStatus.Trigger.Source
        SOURCE_FIELD_NUMBER: _ClassVar[int]
        TIMING: WorkStatus.Trigger.Source
        UNKNOWN: WorkStatus.Trigger.Source
        source: WorkStatus.Trigger.Source
        def __init__(self, source: _Optional[_Union[WorkStatus.Trigger.Source, str]] = ...) -> None: ...
    class Upgrading(_message.Message):
        __slots__ = ["state"]
        class State(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
            __slots__ = []
        DOING: WorkStatus.Upgrading.State
        DONE: WorkStatus.Upgrading.State
        STATE_FIELD_NUMBER: _ClassVar[int]
        state: WorkStatus.Upgrading.State
        def __init__(self, state: _Optional[_Union[WorkStatus.Upgrading.State, str]] = ...) -> None: ...
    BREAKPOINT_FIELD_NUMBER: _ClassVar[int]
    CHARGING: WorkStatus.State
    CHARGING_FIELD_NUMBER: _ClassVar[int]
    CLEANING: WorkStatus.State
    CLEANING_FIELD_NUMBER: _ClassVar[int]
    CRUISIING: WorkStatus.State
    CRUISIING_FIELD_NUMBER: _ClassVar[int]
    CURRENT_SCENE_FIELD_NUMBER: _ClassVar[int]
    FAST_MAPPING: WorkStatus.State
    FAULT: WorkStatus.State
    GO_HOME: WorkStatus.State
    GO_HOME_FIELD_NUMBER: _ClassVar[int]
    GO_WASH_FIELD_NUMBER: _ClassVar[int]
    MAPPING_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    RELOCATING_FIELD_NUMBER: _ClassVar[int]
    REMOTE_CTRL: WorkStatus.State
    ROLLER_BRUSH_CLEANING_FIELD_NUMBER: _ClassVar[int]
    SLEEP: WorkStatus.State
    SMART_FOLLOW_FIELD_NUMBER: _ClassVar[int]
    STANDBY: WorkStatus.State
    STATE_FIELD_NUMBER: _ClassVar[int]
    STATION_FIELD_NUMBER: _ClassVar[int]
    TRIGGER_FIELD_NUMBER: _ClassVar[int]
    UPGRADING_FIELD_NUMBER: _ClassVar[int]
    breakpoint: WorkStatus.Breakpoint
    charging: WorkStatus.Charging
    cleaning: WorkStatus.Cleaning
    cruisiing: WorkStatus.Cruisiing
    current_scene: WorkStatus.Scene
    go_home: WorkStatus.GoHome
    go_wash: WorkStatus.GoWash
    mapping: WorkStatus.Mapping
    mode: WorkStatus.Mode
    relocating: WorkStatus.Relocating
    roller_brush_cleaning: WorkStatus.RollerBrushCleaning
    smart_follow: WorkStatus.SmartFollow
    state: WorkStatus.State
    station: WorkStatus.Station
    trigger: WorkStatus.Trigger
    upgrading: WorkStatus.Upgrading
    def __init__(self, mode: _Optional[_Union[WorkStatus.Mode, _Mapping]] = ..., state: _Optional[_Union[WorkStatus.State, str]] = ..., charging: _Optional[_Union[WorkStatus.Charging, _Mapping]] = ..., upgrading: _Optional[_Union[WorkStatus.Upgrading, _Mapping]] = ..., mapping: _Optional[_Union[WorkStatus.Mapping, _Mapping]] = ..., cleaning: _Optional[_Union[WorkStatus.Cleaning, _Mapping]] = ..., go_wash: _Optional[_Union[WorkStatus.GoWash, _Mapping]] = ..., go_home: _Optional[_Union[WorkStatus.GoHome, _Mapping]] = ..., cruisiing: _Optional[_Union[WorkStatus.Cruisiing, _Mapping]] = ..., relocating: _Optional[_Union[WorkStatus.Relocating, _Mapping]] = ..., breakpoint: _Optional[_Union[WorkStatus.Breakpoint, _Mapping]] = ..., roller_brush_cleaning: _Optional[_Union[WorkStatus.RollerBrushCleaning, _Mapping]] = ..., smart_follow: _Optional[_Union[WorkStatus.SmartFollow, _Mapping]] = ..., station: _Optional[_Union[WorkStatus.Station, _Mapping]] = ..., current_scene: _Optional[_Union[WorkStatus.Scene, _Mapping]] = ..., trigger: _Optional[_Union[WorkStatus.Trigger, _Mapping]] = ...) -> None: ...
