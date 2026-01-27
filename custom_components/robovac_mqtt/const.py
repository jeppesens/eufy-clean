from __future__ import annotations

from enum import Enum
from typing import Final

from .proto.cloud.clean_param_pb2 import CleanExtent, CleanType, MopMode

DOMAIN: Final = "robovac_mqtt"
VACS: Final = "vacs"
DEVICES: Final = "devices"

# Eufy API URLs
EUFY_API_BASE_URL: Final = "https://api.eufylife.com"
EUFY_HOME_API_BASE_URL: Final = "https://home-api.eufylife.com"
EUFY_AIOT_API_BASE_URL: Final = "https://aiot-clean-api-pr.eufylife.com"

EUFY_API_LOGIN: Final = f"{EUFY_HOME_API_BASE_URL}/v1/user/email/login"
EUFY_API_USER_INFO: Final = f"{EUFY_API_BASE_URL}/v1/user/user_center_info"
EUFY_API_DEVICE_LIST: Final = (
    f"{EUFY_AIOT_API_BASE_URL}/app/devicerelation/get_device_list"
)
EUFY_API_DEVICE_V2: Final = f"{EUFY_API_BASE_URL}/v1/device/v2"
EUFY_API_MQTT_INFO: Final = (
    f"{EUFY_AIOT_API_BASE_URL}/app/devicemanage/get_user_mqtt_info"
)


EUFY_CLEAN_DEVICES = {
    "T1250": "RoboVac 35C",
    "T2103": "RoboVac 11C",
    "T2117": "RoboVac 35C",
    "T2118": "RoboVac 30C",
    "T2119": "RoboVac 11S",
    "T2120": "RoboVac 15C MAX",
    "T2123": "RoboVac 25C",
    "T2128": "RoboVac 15C MAX",
    "T2130": "RoboVac 30C MAX",
    "T2132": "RoboVac 25C",
    "T2150": "RoboVac G10 Hybrid",
    "T2181": "RoboVac LR30 Hybrid+",
    "T2182": "RoboVac LR35 Hybrid+",
    "T2190": "RoboVac L70 Hybrid",
    "T2192": "RoboVac LR20",
    "T2193": "RoboVac LR30 Hybrid",
    "T2194": "RoboVac LR35 Hybrid",
    "T2210": "Robovac G50",
    "T2250": "Robovac G30",
    "T2251": "RoboVac G30",
    "T2252": "RoboVac G30 Verge",
    "T2253": "RoboVac G30 Hybrid",
    "T2254": "RoboVac G35",
    "T2255": "Robovac G40",
    "T2256": "RoboVac G40 Hybrid",
    "T2257": "RoboVac G20",
    "T2258": "RoboVac G20 Hybrid",
    "T2259": "RoboVac G32",
    "T2261": "RoboVac X8 Hybrid",
    "T2262": "RoboVac X8",
    "T2266": "Robovac X8 Pro",
    "T2267": "RoboVac L60",
    "T2268": "Robovac L60 Hybrid",
    "T2270": "RoboVac G35+",
    "T2272": "Robovac G30+ SES",
    "T2273": "RoboVac G40 Hybrid+",
    "T2276": "Robovac X8 Pro SES",
    "T2277": "Robovac L60 SES",
    "T2278": "Robovac L60 Hybrid SES",
    "T2280": "Robovac Omni C20",
    "T2292": "Robovac AE C10",
    "T2320": "Robovac X9 Pro",
    "T2351": "Robovac X10 Pro Omni",
    "T2080": "Robovac S1",
}

EUFY_CLEAN_X_SERIES = ["T2262", "T2261", "T2266", "T2276", "T2320", "T2351"]

EUFY_CLEAN_G_SERIES = [
    "T2210",
    "T2250",
    "T2251",
    "T2252",
    "T2253",
    "T2254",
    "T2255",
    "T2256",
    "T2257",
    "T2258",
    "T2259",
    "T2270",
    "T2272",
    "T2273",
    "T2277",
]

EUFY_CLEAN_L_SERIES = ["T2190", "T2267", "T2268", "T2278"]

EUFY_CLEAN_C_SERIES = [
    "T1250",
    "T2117",
    "T2118",
    "T2128",
    "T2130",
    "T2132",
    "T2120",
    "T2280",
    "T2292",
]

EUFY_CLEAN_S_SERIES = ["T2119", "T2080"]


class EUFY_CLEAN_GET_STATE(str, Enum):
    sleeping = "stopped"
    standby = "docked"
    recharge = "docked"
    running = "cleaning"
    cleaning = "cleaning"
    spot = "spot_cleaning"
    completed = "docked"
    charging = "charging"
    sleep = "stopped"
    go_home = "docked"
    fault = "stopped"


class EUFY_CLEAN_VACUUMCLEANER_STATE(str, Enum):
    STOPPED = "stopped"
    CLEANING = "cleaning"
    SPOT_CLEANING = "spot_cleaning"
    DOCKED = "docked"
    CHARGING = "charging"


class EUFY_CLEAN_CLEAN_SPEED(str, Enum):
    NO_SUCTION = "No_suction"
    STANDARD = "Standard"
    QUIET = "Quiet"
    TURBO = "Turbo"
    BOOST_IQ = "Boost_IQ"
    MAX = "Max"


EUFY_CLEAN_NOVEL_CLEAN_SPEED = [
    EUFY_CLEAN_CLEAN_SPEED.QUIET,
    EUFY_CLEAN_CLEAN_SPEED.STANDARD,
    EUFY_CLEAN_CLEAN_SPEED.TURBO,
    EUFY_CLEAN_CLEAN_SPEED.MAX,
]

EUFY_CLEAN_LEGACY_CLEAN_SPEED = [
    EUFY_CLEAN_CLEAN_SPEED.NO_SUCTION,
    EUFY_CLEAN_CLEAN_SPEED.BOOST_IQ,
]


class EUFY_CLEAN_GET_CLEAN_SPEED(str, Enum):
    no_suction = "No Suction"
    standard = "Standard"
    quiet = "Quiet"
    turbo = "Turbo"
    boost_iq = "Boost IQ"
    max = "Max"


class EUFY_CLEAN_WORK_STATUS(str, Enum):
    # Cleaning
    RUNNING = "Running"
    # In the dock, charging
    CHARGING = "Charging"
    # Not in the dock, paused
    STAND_BY = "standby"
    # Not in the dock - goes into this state after being paused for a while
    SLEEPING = "Sleeping"
    # Going home because battery is depleted
    RECHARGE_NEEDED = "Recharge"
    RECHARGE = "Recharge"
    # In the dock, full charged
    COMPLETED = "Completed"
    STANDBY = "Standby"
    SLEEP = "Sleep"
    FAULT = "Fault"
    FAST_MAPPING = "Fast Mapping"
    CLEANING = "Cleaning"
    REMOTE_CTRL = "Remote Ctrl"
    GO_HOME = "Go Home"
    CRUISIING = "Cruising"


class EUFY_CLEAN_WORK_MODE(str, Enum):
    AUTO = "auto"
    NO_SWEEP = "Nosweep"
    SMALL_ROOM = "SmallRoom"
    ROOM = "room"
    ZONE = "zone"
    EDGE = "Edge"
    SPOT = "Spot"


class EUFY_CLEAN_CONTROL(int, Enum):
    START_AUTO_CLEAN = 0
    START_SELECT_ROOMS_CLEAN = 1
    START_SELECT_ZONES_CLEAN = 2
    START_SPOT_CLEAN = 3
    START_GOTO_CLEAN = 4
    START_RC_CLEAN = 5
    START_GOHOME = 6
    START_SCHEDULE_AUTO_CLEAN = 7
    START_SCHEDULE_ROOMS_CLEAN = 8
    START_FAST_MAPPING = 9
    START_GOWASH = 10
    STOP_TASK = 12
    PAUSE_TASK = 13
    RESUME_TASK = 14
    STOP_GOHOME = 15
    STOP_RC_CLEAN = 16
    STOP_GOWASH = 17
    STOP_SMART_FOLLOW = 18
    START_GLOBAL_CRUISE = 20
    START_POINT_CRUISE = 21
    START_ZONES_CRUISE = 22
    START_SCHEDULE_CRUISE = 23
    START_SCENE_CLEAN = 24
    START_MAPPING_THEN_CLEAN = 25


EUFY_CLEAN_ERROR_CODES = {
    0: "NONE",
    1: "CRASH BUFFER STUCK",
    2: "WHEEL STUCK",
    3: "SIDE BRUSH STUCK",
    4: "ROLLING BRUSH STUCK",
    5: "HOST TRAPPED CLEAR OBST",
    6: "MACHINE TRAPPED MOVE",
    7: "WHEEL OVERHANGING",
    8: "POWER LOW SHUTDOWN",
    13: "HOST TILTED",
    14: "NO DUST BOX",
    17: "FORBIDDEN AREA DETECTED",
    18: "LASER COVER STUCK",
    19: "LASER SENSOR STUCK",
    20: "LASER BLOCKED",
    21: "DOCK FAILED",
    26: "POWER APPOINT START FAIL",
    31: "SUCTION PORT OBSTRUCTION",
    32: "WIPE HOLDER MOTOR STUCK",
    33: "WIPING BRACKET MOTOR STUCK",
    39: "POSITIONING FAIL CLEAN END",
    40: "MOP CLOTH DISLODGED",
    41: "AIRDRYER HEATER ABNORMAL",
    50: "MACHINE ON CARPET",
    51: "CAMERA BLOCK",
    52: "UNABLE LEAVE STATION",
    55: "EXPLORING STATION FAIL",
    70: "CLEAN DUST COLLECTOR",
    71: "WALL SENSOR FAIL",
    72: "ROBOVAC LOW WATER",
    73: "DIRTY TANK FULL",
    74: "CLEAN WATER LOW",
    75: "WATER TANK ABSENT",
    76: "CAMERA ABNORMAL",
    77: "3D TOF ABNORMAL",
    78: "ULTRASONIC ABNORMAL",
    79: "CLEAN TRAY NOT INSTALLED",
    80: "ROBOVAC COMM FAIL",
    81: "SEWAGE TANK LEAK",
    82: "CLEAN TRAY NEEDS CLEAN",
    83: "POOR CHARGING CONTACT",
    101: "BATTERY ABNORMAL",
    102: "WHEEL MODULE ABNORMAL",
    103: "SIDE BRUSH ABNORMAL",
    104: "FAN ABNORMAL",
    105: "ROLLER BRUSH MOTOR ABNORMAL",
    106: "HOST PUMP ABNORMAL",
    107: "LASER SENSOR ABNORMAL",
    111: "ROTATION MOTOR ABNORMAL",
    112: "LIFT MOTOR ABNORMAL",
    113: "WATER SPRAY ABNORMAL",
    114: "WATER PUMP ABNORMAL",
    117: "ULTRASONIC ABNORMAL",
    119: "WIFI BLUETOOTH ABNORMAL",
    6010: "STATION CLEAN WATER TANK NOT CONNECTED",
    6011: "STATION LOW CLEAN WATER",
    6025: "STATION FULL DIRTY WATER OR DIRTY WATER TANK NOT CONNECTED",
    6030: "STATION CLEANING TRAY NOT INSTALLED",
    6113: "STATION NO DUST BAG INSTALLED",
    7031: "STATION RETURN FAILED CLEAR AREA",
    # The following errors were extracted and translated from the Chinese strings
    # in custom_components/robovac_mqtt/proto/cloud/error_code_list_standard.proto
    1010: "LEFT WHEEL OPEN CIRCUIT",
    1011: "LEFT WHEEL SHORT CIRCUIT",
    1012: "LEFT WHEEL ABNORMAL",
    1013: "LEFT WHEEL OVERCURRENT",
    1020: "RIGHT WHEEL OPEN CIRCUIT",
    1021: "RIGHT WHEEL SHORT CIRCUIT",
    1022: "RIGHT WHEEL ABNORMAL",
    1023: "RIGHT WHEEL OVERCURRENT",
    1030: "BOTH WHEELS OPEN CIRCUIT",
    1031: "BOTH WHEELS SHORT CIRCUIT",
    1032: "BOTH WHEELS ABNORMAL",
    1033: "BOTH WHEELS OVERCURRENT",
    2010: "FAN OPEN CIRCUIT",
    2011: "FAN SHORT CIRCUIT",
    2012: "FAN ABNORMAL",
    2013: "FAN RPM ABNORMAL",
    2020: "LEFT FAN OPEN CIRCUIT",
    2021: "LEFT FAN SHORT CIRCUIT",
    2022: "LEFT FAN ABNORMAL",
    2023: "LEFT FAN RPM ABNORMAL",
    2024: "RIGHT FAN OPEN CIRCUIT",
    2025: "RIGHT FAN SHORT CIRCUIT",
    2026: "RIGHT FAN ABNORMAL",
    2027: "RIGHT FAN RPM ABNORMAL",
    2110: "ROLLER BRUSH OPEN CIRCUIT",
    2111: "ROLLER BRUSH SHORT CIRCUIT",
    2112: "ROLLER BRUSH OVERCURRENT",
    2113: "ROLLER BRUSH ABNORMAL",
    2120: "FRONT ROLLER BRUSH OPEN CIRCUIT",
    2121: "FRONT ROLLER BRUSH SHORT CIRCUIT",
    2122: "FRONT ROLLER BRUSH OVERCURRENT",
    2123: "REAR ROLLER BRUSH OPEN CIRCUIT",
    2124: "REAR ROLLER BRUSH SHORT CIRCUIT",
    2125: "REAR ROLLER BRUSH OVERCURRENT",
    2210: "SIDE BRUSH OPEN CIRCUIT",
    2211: "SIDE BRUSH SHORT CIRCUIT",
    2212: "SIDE BRUSH ABNORMAL",
    2213: "SIDE BRUSH OVERCURRENT",
    2220: "LEFT SIDE BRUSH OPEN CIRCUIT",
    2221: "LEFT SIDE BRUSH SHORT CIRCUIT",
    2222: "LEFT SIDE BRUSH ABNORMAL",
    2223: "LEFT SIDE BRUSH OVERCURRENT",
    2224: "RIGHT SIDE BRUSH OPEN CIRCUIT",
    2225: "RIGHT SIDE BRUSH SHORT CIRCUIT",
    2226: "RIGHT SIDE BRUSH ABNORMAL",
    2227: "RIGHT SIDE BRUSH OVERCURRENT",
    2310: "DUSTBIN OR FILTER MISSING",
    2311: "DUSTBIN FULL (10H REMINDER)",
    3010: "WATER PUMP OPEN CIRCUIT",
    3011: "WATER PUMP SHORT CIRCUIT",
    3012: "WATER PUMP ABNORMAL",
    3013: "WATER TANK EMPTY",
    3020: "WATER TANK REMOVED",
    3110: "LEFT MOP MISSING",
    3111: "RIGHT MOP MISSING",
    3120: "ROTATION MOTOR OPEN CIRCUIT",
    3121: "ROTATION MOTOR SHORT CIRCUIT",
    3122: "ROTATION MOTOR ABNORMAL",
    3123: "ROTATION MOTOR STUCK",
    3130: "LIFT MOTOR OPEN CIRCUIT",
    3131: "LIFT MOTOR SHORT CIRCUIT",
    3132: "LIFT MOTOR ABNORMAL",
    3133: "LIFT MOTOR STUCK",
    4010: "RADAR COMMUNICATION ERROR",
    4011: "RADAR BLOCKED",
    4012: "RADAR RPM ABNORMAL",
    4020: "GYROSCOPE ABNORMAL",
    4030: "TOF SENSOR ERROR",
    4031: "TOF SENSOR BLOCKED",
    4040: "CAMERA SENSOR ERROR",
    4041: "CAMERA BLOCKED",
    4090: "WALL SENSOR ERROR",
    4091: "WALL SENSOR BLOCKED",
    4111: "LEFT BUMPER STUCK",
    4112: "RIGHT BUMPER STUCK",
    4120: "ULTRASONIC ERROR (CLEANING)",
    4121: "ULTRASONIC ERROR (IDLE)",
    4130: "LIDAR COVER STUCK",
    5010: "BATTERY OPEN CIRCUIT",
    5011: "BATTERY SHORT CIRCUIT",
    5012: "CHARGING CURRENT TOO LOW",
    5013: "DISCHARGE CURRENT TOO HIGH",
    5014: "DOCKING STATION POWER OFF",
    5015: "LOW BATTERY (NO SCHEDULED CLEAN)",
    5016: "CHARGING CURRENT TOO HIGH",
    5017: "CHARGING VOLTAGE ABNORMAL",
    5018: "BATTERY TEMP ABNORMAL",
    5021: "DISCHARGE TEMP HIGH",
    5022: "DISCHARGE TEMP LOW",
    5023: "CHARGE TEMP HIGH",
    5024: "CHARGE TEMP LOW",
    5110: "WIFI ERROR",
    5111: "BLUETOOTH ERROR",
    5112: "IR COMMUNICATION ERROR",
    6012: "STATION CLEAN WATER PUMP OPEN",
    6013: "STATION CLEAN WATER PUMP SHORT",
    6014: "STATION VALVE SHORT",
    6020: "STATION DIRTY TANK MISSING",
    6021: "STATION DIRTY TANK FULL",
    6022: "STATION DIRTY PUMP OPEN",
    6023: "STATION DIRTY PUMP SHORT",
    6024: "STATION DIRTY TANK LEAK",
    6031: "STATION TRAY FULL",
    6032: "STATION TRAY MISSING/FULL",
    6040: "STATION DRYER OPEN",
    6041: "STATION DRYER SHORT",
    6042: "STATION HEATER OPEN",
    6043: "STATION NTC OPEN",
    6110: "STATION VOLTAGE ERROR",
    6111: "STATION DUST LEAK",
    6112: "STATION DUST AP DUCT BLOCKED",
    6114: "STATION FAN OVERHEAT",
    6115: "STATION BAROMETER ERROR",
    6117: "LOW BATTERY (NO AUTO EMPTY)",
    6118: "LOW BATTERY (NO SELF CLEAN)",
    6300: "HAIR CUTTING IN PROGRESS",
    6301: "LOW BATTERY (NO HAIR CUTTING)",
    6310: "POWER FAILURE",
    6311: "HAIR CUTTING MODULE STUCK",
    7000: "SMALL SPACE TIMEOUT",
    7001: "MACHINE SUSPENDED",
    7002: "MACHINE PICKED UP",
    7003: "DROP SENSOR TRIGGERED",
    7004: "MACHINE STUCK",
    7010: "ENTERED NO-GO ZONE",
    7011: "ENTERED CARPET",
    7020: "GLOBAL POSITIONING FAILED",
    7021: "POSITIONING FAILED",
    7033: "STATION EXPLORATION FAILED",
    7034: "CANNOT FIND START POINT",
    7035: "DOCKING FAILED (NO POWER)",
    7036: "DOCKING FAILED (WHEEL STUCK)",
    7037: "DOCKING FAILED (IR REFLECTION)",
    7040: "UNDOCKING FAILED",
    7050: "UNREACHABLE TARGET",
    7051: "SCHEDULE FAILED",
    7052: "PATH PLANNING FAILED",
    7053: "MACHINE TILTED",
    7054: "FOLLOW TARGET LOST",
    7055: "STATION NOT FOUND",
}


# Mapping for Custom Room Parameters

CLEAN_TYPE_MAP = {
    "vacuum": CleanType.SWEEP_ONLY,
    "mop": CleanType.MOP_ONLY,
    "vacuum_mop": CleanType.SWEEP_AND_MOP,
    "vacuum_and_mop": CleanType.SWEEP_AND_MOP,
    "sweep_and_mop": CleanType.SWEEP_AND_MOP,
}

CLEAN_EXTENT_MAP = {
    "fast": CleanExtent.QUICK,
    "standard": CleanExtent.NORMAL,
    "deep": CleanExtent.NARROW,
}

MOP_CORNER_MAP = {
    True: MopMode.DEEP,
    False: MopMode.NORMAL,
}

MOP_LEVEL_MAP = {
    "low": MopMode.LOW,
    "middle": MopMode.MIDDLE,
    "standard": MopMode.MIDDLE,
    "medium": MopMode.MIDDLE,
    "high": MopMode.HIGH,
}


DPS_MAP = {
    "PLAY_PAUSE": "152",
    "DIRECTION": "155",
    "WORK_MODE": "153",
    "WORK_STATUS": "153",
    "CLEANING_PARAMETERS": "154",
    "CLEANING_STATISTICS": "167",
    "ACCESSORIES_STATUS": "168",
    "GO_HOME": "173",
    "CLEAN_SPEED": "158",
    "FIND_ROBOT": "160",
    "BATTERY_LEVEL": "163",
    "STATION_STATUS": "173",
    "ERROR_CODE": "177",
    "SCENE_INFO": "180",
    "MAP_DATA": "165",
    "MAP_EDIT": "164",
    "MULTI_MAP_SW": "156",
    "MAP_STREAM": "166",
    "UNSETTING": "176",
    "MAP_EDIT_REQUEST": "170",
    "MAP_MANAGE": "169",
}


ACCESSORY_MAX_LIFE = {
    "filter_usage": 360,
    "main_brush_usage": 360,
    "side_brush_usage": 180,
    "sensor_usage": 60,  # Maintain/clean interval
    "scrape_usage": 30,  # Cleaning Tray maintain/clean interval
    "mop_usage": 180,
}

# Dock statuses that indicate active dock operations
# Used to determine when to reset to Idle
DOCK_ACTIVITY_STATES = (
    "Washing",
    "Drying",
    "Emptying dust",
    "Adding clean water",
    "Recycling waste water",
    "Making disinfectant",
    "Cutting hair",
)


# Modes that imply APP trigger source
EUFY_CLEAN_APP_TRIGGER_MODES = {
    1,  # SELECT_ROOM
    2,  # SELECT_ZONE
    3,  # SPOT
    4,  # FAST_MAPPING
    5,  # GLOBAL_CRUISE
    6,  # ZONES_CRUISE
    7,  # POINT_CRUISE
    8,  # SCENE
    9,  # SMART_FOLLOW
}

DRY_DURATION_MAP = {"SHORT": "2h", "MEDIUM": "3h", "LONG": "4h"}
