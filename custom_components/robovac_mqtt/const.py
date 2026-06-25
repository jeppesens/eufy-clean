from __future__ import annotations

from enum import Enum
from typing import Final

from .proto.cloud.clean_param_pb2 import CleanExtent, CleanType, MopMode

DOMAIN: Final = "robovac_mqtt"
VACS: Final = "vacs"
DEVICES: Final = "devices"

# Options keys
CONF_MAP_MAX_PX: Final = "map_max_px"
DEFAULT_MAP_MAX_PX: Final = 512

CONF_ROBOT_STYLE: Final = "robot_style"
DEFAULT_ROBOT_STYLE: Final = "googly"

CONF_NOTIFY_DESKTOP: Final = "notify_desktop"
DEFAULT_NOTIFY_DESKTOP: Final = True
CONF_NOTIFY_MOBILE_SERVICE: Final = "notify_mobile_service"
DEFAULT_NOTIFY_MOBILE_SERVICE: Final = ""

# Config-entry options keys for the optional local-Tuya transport and
# per-device overrides. Stored shape:
#   options[CONF_LOCAL_DEVICES] = {
#       device_id: {
#           "host": "1.2.3.4",          # CONF_LOCAL_HOST
#           "version": 3.3,             # CONF_LOCAL_VERSION
#           "rooms": {1: "Lounge"},     # CONF_ROOM_NAMES (parsed from textarea)
#       }
#   }
CONF_LOCAL_DEVICES: Final = "local_devices"
CONF_LOCAL_HOST: Final = "host"
CONF_LOCAL_VERSION: Final = "version"
CONF_ROOM_NAMES: Final = "rooms"

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
    "T2080A": "Robovac S1 Pro",
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

EUFY_CLEAN_S_SERIES = ["T2119", "T2080", "T2080A"]


class TriggerSource(int, Enum):
    UNKNOWN = 0
    APP = 1
    KEY = 2
    TIMING = 3
    ROBOT = 4
    REMOTE_CTRL = 5


TRIGGER_SOURCE_NAMES = {
    TriggerSource.UNKNOWN: "unknown",
    TriggerSource.APP: "app",
    TriggerSource.KEY: "button",
    TriggerSource.TIMING: "schedule",
    TriggerSource.ROBOT: "robot",
    TriggerSource.REMOTE_CTRL: "remote_control",
}


class CleaningMode(int, Enum):
    SWEEP_ONLY = 0
    MOP_ONLY = 1
    SWEEP_AND_MOP = 2
    SWEEP_THEN_MOP = 3


class MopWaterLevel(int, Enum):
    LOW = 0
    MIDDLE = 1
    HIGH = 2


# Reverse mappings for parser - convert proto values to human-readable names
CLEANING_MODE_NAMES = {
    CleaningMode.SWEEP_ONLY: "Vacuum",
    CleaningMode.MOP_ONLY: "Mop",
    CleaningMode.SWEEP_AND_MOP: "Vacuum and mop",
    CleaningMode.SWEEP_THEN_MOP: "Mopping after sweeping",
}

MOP_WATER_LEVEL_NAMES = {
    MopWaterLevel.LOW: "Low",
    MopWaterLevel.MIDDLE: "Medium",
    MopWaterLevel.HIGH: "High",
}


# Additional DPS 154 mappings for enhanced functionality
CLEANING_INTENSITY_NAMES = {
    0: "Normal",
    1: "Narrow",
    2: "Quick",
}

# Derived from the enum-based dicts above to avoid duplication
EUFY_CLEAN_CLEANING_MODES = list(CLEANING_MODE_NAMES.values())
EUFY_CLEAN_WATER_LEVELS = list(MOP_WATER_LEVEL_NAMES.values())
EUFY_CLEAN_CLEANING_INTENSITIES = list(CLEANING_INTENSITY_NAMES.values())

CARPET_STRATEGY_NAMES = {
    0: "Auto Raise",
    1: "Avoid",
    2: "Ignore",
}

CORNER_CLEANING_NAMES = {
    0: "Normal",
    1: "Deep",
}

FAN_SUCTION_NAMES = {
    0: "Quiet",
    1: "Standard",
    2: "Turbo",
    3: "Max",
    4: "Boost_IQ",
}


WORK_MODE_NAMES = {
    0: "Auto",
    1: "Room",
    2: "Zone",
    3: "Spot",
    4: "Fast Mapping",
    5: "Global Cruise",
    6: "Zones Cruise",
    7: "Point Cruise",
    8: "Scene",
    9: "Smart Follow",
}


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
    EUFY_CLEAN_CLEAN_SPEED.BOOST_IQ,
]


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
    # Keys are normalized to lowercase with spaces (underscores converted to spaces
    # by _normalize_clean_mode in commands.py).
    "vacuum": CleanType.SWEEP_ONLY,
    "mop": CleanType.MOP_ONLY,
    "vacuum mop": CleanType.SWEEP_AND_MOP,
    "vacuum and mop": CleanType.SWEEP_AND_MOP,
    "sweep and mop": CleanType.SWEEP_AND_MOP,
    "mopping after sweeping": CleanType.SWEEP_THEN_MOP,
}

CLEAN_EXTENT_MAP = {
    # Legacy keys
    "fast": CleanExtent.QUICK,
    "standard": CleanExtent.NORMAL,
    "deep": CleanExtent.NARROW,
    # New standardized keys matching UI and Matter vocabulary
    "quick": CleanExtent.QUICK,
    "normal": CleanExtent.NORMAL,
    "narrow": CleanExtent.NARROW,
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
    "VOICE_LANGUAGE": "162",
    "VOLUME": "161",
    "MAP_EDIT_REQUEST": "170",
    "MULTI_MAP_MANAGE": "172",
    "MAP_MANAGE": "169",
    "UNDISTURBED": "157",
}

# DPS keys that are known but intentionally not parsed.
# Values are already stored in raw_dps for diagnostics.
KNOWN_UNPROCESSED_DPS: frozenset[str] = frozenset(
    {
        DPS_MAP["DIRECTION"],  # 155 - RemoteCtrl echo
        DPS_MAP["MULTI_MAP_SW"],  # 156 - multi-map toggle (also in DPS 176)
        DPS_MAP["MAP_EDIT"],  # 164 - MapEditResponse ack
        DPS_MAP[
            "MAP_STREAM"
        ],  # 166 - debug/metadata on T2351 (map data is local P2P only)
        # Note: DPS 169 (MAP_MANAGE) is now parsed as DeviceInfo
        DPS_MAP["MAP_EDIT_REQUEST"],  # 170 - MapEditRequest echo
        # Unknown DPS keys observed in the wild:
        "150",  # Unknown, value: None
        "151",  # Unknown, value: True
        "159",  # Unknown, value: True
        "171",  # Unknown, value: None
        "174",  # Unknown, value: None
        "175",  # Unknown, value: None
        "178",  # Unknown protobuf, timestamp/event log
    }
)

# DPS 179 key (no named entry in DPS_MAP — undocumented telemetry channel)
DPS_ROBOT_TELEMETRY = "179"

# DPS 162 voice/language catalog: set_id → (display_label, raw_b64_request)
# raw_b64_request is the exact LanguageRequest proto payload captured from the
# Eufy app's /req MQTT messages (firmware v22). If a firmware update changes
# voice pack URLs the device will reject the MD5 check — re-capture then.
VOICE_CATALOG: dict[int, tuple[str, str]] = {
    1200: ("Chinese (Simplified)", "hAEKgQEIsAkSVGh0dHBzOi8vZDNwa2JnazAxb291aGwuY2xvdWRmcm9udC5uZXQvdm9pY2UvcHJvZC8xNzc0MjMwOTIxMjA1Nzc2X3poX2NuLTEyMDAtdjIyLnppcBogNjY3NmIyMzYxZWIzMWM0NTQyODhjYTc3YjZjNTg5ZjAgFijUgEc="),
    1201: ("English (Female)", "iwEKiAEIsQkSW2h0dHBzOi8vZDNwa2JnazAxb291aGwuY2xvdWRmcm9udC5uZXQvdm9pY2UvcHJvZC8xNzc0MjMwOTk4MzUxODc3X2VuX3VzX2ZlbWFsZS0xMjAxLXYyMi56aXAaIGE2ZTY5OGUxZDRmNWQ2ZDExOWY1YTEwMTEzZTQ0NmVjIBYowvtX"),
    1202: ("English (Male)", "iQEKhgEIsgkSWWh0dHBzOi8vZDNwa2JnazAxb291aGwuY2xvdWRmcm9udC5uZXQvdm9pY2UvcHJvZC8xNzc0MjMxMDQzODE2NDY1X2VuX3VzX21hbGUtMTIwMi12MjIuemlwGiBjNzcwNmRkN2U1NTFkZjUwNjQ4MjNlNWQ4MGVjN2IzMCAWKN67Vg=="),
    1203: ("German", "gAEKfgizCRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzEwODQ0NzE4NTJfZGUtMTIwMy12MjIuemlwGiAyYmJjZWYzNzczNjJjOWFkNjY4MjY4YzI1MWM3NWI1NiAWKJa7bA=="),
    1204: ("Japanese", "gAEKfgi0CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzExNTU5OTYyNDNfamEtMTIwNC12MjIuemlwGiBiNmVmOGUzM2ZjMTgwOGU1OWQyZDRjN2UxOWM3MTBhOSAWKP6IcA=="),
    1205: ("Spanish", "gAEKfgi1CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzEyNDU4OTEyODJfZXMtMTIwNS12MjIuemlwGiAwNzM1ZTYzY2NhYjcwNTZlYjJlNDQ4ZGY2YzM5ZGRkMyAWKIbuZA=="),
    1206: ("Italian", "gAEKfgi2CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzEyODY3ODQ3MTZfaXQtMTIwNi12MjIuemlwGiBhODgwNDBlNjZmNGRmNGU2N2RjNTk1MTNiZjVhMGNhYiAWKNaqVw=="),
    1207: ("French", "gAEKfgi3CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzEzNTcyMjIwOTBfZnItMTIwNy12MjIuemlwGiAzNzNhZDEyODA1NGZkYmM5NzEwMWQwNTJmZjNjN2IyZCAWKI65XQ=="),
    1208: ("Portuguese (Brazil)", "gAEKfgi4CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzEzOTk4NTMxNDFfcHQtMTIwOC12MjIuemlwGiBkYTI3ZjEyMGRlMTkyNjE5ZTc1YjdmODdhYzgwNmM3ZCAWKN6UaQ=="),
    1209: ("Turkish", "gAEKfgi5CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzE0NDc2MTMyMDlfdHItMTIwOS12MjIuemlwGiAxOTE1ZDEzNmIwZTM1ODlmNDYzZjVhZjBmZWMyYmI1MSAWKP7kXQ=="),
    1210: ("Russian", "gAEKfgi6CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzE0OTY0NDgzMTBfcnUtMTIxMC12MjIuemlwGiA5ODkyNWQ5MTFjYWVmNDQ4ZTg2ZmE3ZWYwMjZmMjJhNCAWKO7/ag=="),
    1211: ("Arabic", "gAEKfgi7CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzE1NTUwMDE0NDhfYXItMTIxMS12MjIuemlwGiBmMTcyMTYwYTRmMmMzODFkMDJkYzY4OWJjMzZkNTdjNyAWKN6cbg=="),
    1212: ("Korean", "gAEKfgi8CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzI2MjIyNDA5NjFfa28tMTIxMi12MjIuemlwGiBjZTQ0NDIzYTMzZjhjYzhkNzUxMGM0NGU1OWExODMzYSAWKJ7MZg=="),
    1213: ("Dutch", "gAEKfgi9CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzI2NTEzMDg4NTVfbmwtMTIxMy12MjIuemlwGiBjODNiN2JmOWNkMmYzM2U3OTFkMzRkZmZiOWExMzc5MyAWKP6SYg=="),
    1214: ("Polish", "gAEKfgi+CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzI2OTU1NDY3ODFfcGwtMTIxNC12MjIuemlwGiBhNTA0OWFhZjJmMmFiMTc4MWZlOGU3NjAxMTRiZDQ5NSAWKJbobA=="),
    1215: ("Thai", "gAEKfgi/CRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzI4Mzc1MzMzNzNfdGgtMTIxNS12MjIuemlwGiAwZWMwZjIwZWQwMzNmOGM3YTRmMDMyOWJmYzY5Y2Q0OCAWKM6QVA=="),
    1216: ("Vietnamese", "gAEKfgjACRJRaHR0cHM6Ly9kM3BrYmdrMDFvb3VobC5jbG91ZGZyb250Lm5ldC92b2ljZS9wcm9kLzE3NzQyMzI5MzYzMTU1NzZfdm4tMTIxNi12MjIuemlwGiBkY2I4YmIyZGM0YzJlNjk5ZDA5M2NhYzMzNzYwZDgxOSAWKL77VA=="),
}


# --- Scalar (Tuya-style) DPS protocol ---------------------------------------
# Some Eufy models (verified: T2210 "G50") do NOT use the Anker length-prefixed
# protobuf DPS blobs. Instead they expose state as plain integers / JSON on the
# Tuya DPS numbers, and send NO protobuf WorkStatus. The protocol is detected at
# runtime from value shapes (see api/cloud.py:checkApiType) — not from a model
# list — so any cloud-only Tuya-schema device is handled generically.
# This is a sibling of the Tuya-Cloud "legacy" path (jeppesens PR #110), but here
# the transport is Anker MQTT and the values are ints (not strings).
# See docs/g50_capture/FINDINGS.md for the reverse-engineering evidence and the
# canonical Tuya DPS names (damacus/robovac).
SCALAR_DPS = {
    "STATE": "15",  # activity status (int Tuya STATUS)
    "DETANGLE": "153",  # write 1 = start roller-brush detangle (read=0 in /res)
    # DPS 5 is the work-mode command AND a reported sub-state. Captured from the
    # app's /req: writing 5=1 starts an auto clean, 5=3 returns to the dock.
    "WORK_MODE": "5",
    "PAUSE": "122",  # write 1=pause, 2=resume (also a /res motion flag: 1=stationary)
    "SUCTION": "102",  # Tuya FAN_SPEED: 0=Quiet 1=Standard 2=Turbo 3=Max
    "FIND_ROBOT": "103",  # Tuya LOCATE: 0/1
    "BATTERY": "104",  # Tuya BATTERY_LEVEL: 0-100 %
    "DND": "107",  # Tuya DO_NOT_DISTURB: JSON {"en":bool,"start_t","end_t"}
    "CLEAN_TIME": "109",  # cleaning time in SECONDS (verified: 300=5min, 780=13min)
    "CLEAN_AREA": "110",  # cleaning area in m² (verified: 4=43ft², 3=32ft²)
    "VOLUME": "111",  # voice volume 0-10 (=0-100% in 10% steps)
    "BOOST_IQ": "118",  # Tuya BOOST_IQ: 0/1
    "AUTO_RETURN": "135",  # "Auto-Return Cleaning" toggle: 0/1 (Tuya auto_return)
    "CHILD_LOCK": "139",  # child lock: 0/1
    "ACTIVITY_LOG": "142",  # activity-log upload toggle: 0/1
    "SCHEDULE": "151",  # JSON {"l":[{e,t,r,s,f,id}]}
    "CLEAN_PATTERN": "154",  # 1=Arranged 2=Random (int, NOT protobuf here)
    "ACCESSORIES": "150",  # JSON usage counters
    # Error code: canonical Tuya ERROR_CODE is 106; the G50 capture also showed a
    # scalar on 177. We read both (non-zero wins) since which carries a live fault
    # is unconfirmed.
    "ERROR_CODE": "106",
    "ERROR_CODE_ALT": "177",
}

# DPS 15 (scalar state int) -> activity string (same vocabulary the novel parser
# produces, so the vacuum/binary_sensor entities consume it unchanged).
SCALAR_STATE_NAMES = {
    0: "idle",
    1: "idle",
    2: "cleaning",
    4: "returning",
    5: "docked",  # on dock, actively charging
    6: "docked",  # on dock, charge complete (battery full)
    7: "paused",
}

# Scalar suction reuses the first four EUFY_CLEAN_NOVEL_CLEAN_SPEED entries
# (Quiet/Standard/Turbo/Max); BoostIQ is a separate switch (DPS 118), not a 5th speed.
SCALAR_SUCTION_LEVELS = [s.value for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED[:4]]

# DPS 154 (scalar clean path pattern)
SCALAR_CLEAN_PATTERN_NAMES = {1: "Arranged", 2: "Random"}

# Scalar movement command values (DPS 5 work-mode), captured from the app /req.
SCALAR_WORK_MODE_START = 1  # {"5": 1} -> start auto clean
SCALAR_WORK_MODE_GO_HOME = 3  # {"5": 3} -> return to dock

# Scalar accessory max life in HOURS. DPS 150 reports usage counters in MINUTES;
# % remaining = 1 - used_min / (max_h * 60). Calibrated against the G50 app's
# reported remaining-hours/percentages (see docs/g50_capture/FINDINGS.md). These
# differ from the X-series ACCESSORY_MAX_LIFE values below.
SCALAR_ACCESSORY_MAX_LIFE = {
    "filter_usage": 200,
    "main_brush_usage": 360,  # rolling brush
    "side_brush_usage": 250,
    "sensor_usage": 35,
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

# ---------------------------------------------------------------------------
# Legacy (Tuya Cloud) device support
# ---------------------------------------------------------------------------

# Legacy DPS keys used by older Tuya-based devices (G-series, C-series, S-series)
LEGACY_DPS_MAP = {
    "PLAY_PAUSE": "2",
    "DIRECTION": "3",
    "WORK_MODE": "5",
    "WORK_STATUS": "15",
    "GO_HOME": "101",
    "CLEAN_SPEED": "102",
    "FIND_ROBOT": "103",
    "BATTERY_LEVEL": "104",
    "ERROR_CODE": "106",
}

# Reverse lookup: DPS number string -> key name
LEGACY_DPS_MAP_BY_VALUE = {v: k for k, v in LEGACY_DPS_MAP.items()}

# Legacy work status string -> activity mapping
LEGACY_WORK_STATUS_MAP = {
    "Running": "cleaning",
    "Cleaning": "cleaning",
    "cleaning": "cleaning",
    "Spot": "cleaning",
    "spot": "cleaning",
    "Charging": "docked",
    "charging": "docked",
    "standby": "idle",
    "Standby": "idle",
    "Sleeping": "idle",
    "sleeping": "idle",
    "Sleep": "idle",
    "sleep": "idle",
    "Recharge": "returning",
    "recharge": "returning",
    "Completed": "docked",
    "completed": "docked",
    "Fault": "error",
    "fault": "error",
    "Go Home": "returning",
    "Go_Home": "returning",
    "go_home": "returning",
}

# Legacy fan speed strings (sent/received as plain strings)
LEGACY_CLEAN_SPEEDS = ["No_suction", "Standard", "Quiet", "Turbo", "Boost_IQ", "Max"]

# Legacy work mode string -> display name
LEGACY_WORK_MODES = {
    "auto": "Auto",
    "Nosweep": "No Sweep",
    "SmallRoom": "Small Room",
    "room": "Room",
    "zone": "Zone",
    "Edge": "Edge",
    "Spot": "Spot",
}

# Tuya Cloud API credentials (from upstream martijnpoppen/eufy-clean)
# Public Tuya app credentials embedded in the upstream Eufy Clean JS SDK
# (martijnpoppen/eufy-clean). These are NOT user secrets — they are static
# app-level keys shared by all Eufy/Tuya integrations.
TUYA_CLIENT_ID = "yx5v9uc3ef9wg3v9atje"
TUYA_SECRET = "s8x78u7xwymasd9kqa7a73pjhxqsedaj"
TUYA_SECRET2 = "cepev5pfnhua4dkqkdpmnrdxx378mpjr"
TUYA_CERT_SIGN = "A"
TUYA_API_ET_VERSION = "0.0.1"
TUYA_REGIONS = {
    "EU": "https://a1.tuyaeu.com/api.json",
    "US": "https://a1.tuyaus.com/api.json",
}
