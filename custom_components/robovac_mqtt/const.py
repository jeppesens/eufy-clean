from __future__ import annotations

from enum import Enum
from typing import Final

from .proto.cloud.clean_param_pb2 import CleanExtent, CleanType, MopMode
from .proto.cloud.station_pb2 import StationResponse

DOMAIN: Final = "robovac_mqtt"

# DPS protocol families, as reported in the device list's ``apiType``.
API_TYPE_NOVEL: Final = "novel"
API_TYPE_SCALAR: Final = "scalar"
API_TYPE_LEGACY: Final = "legacy"

VACS: Final = "vacs"
DEVICES: Final = "devices"

CONF_MAP_MAX_PX: Final = "map_max_px"
# NEAREST-rendered room fill, so extra pixels are real detail; ~2.5x the PNG
# bytes of 512, base64'd into the config entry on every render.
DEFAULT_MAP_MAX_PX: Final = 1024

CONF_ROBOT_STYLE: Final = "robot_style"
DEFAULT_ROBOT_STYLE: Final = "googly"

CONF_TRAIL_COLOR: Final = "trail_color"
# Canonical trail colour: api/map_stream.py render default and options-flow seed.
DEFAULT_TRAIL_COLOR: Final = (255, 140, 0)

CONF_NOTIFY_DESKTOP: Final = "notify_desktop"
DEFAULT_NOTIFY_DESKTOP: Final = True
CONF_NOTIFY_MOBILE_SERVICE: Final = "notify_mobile_service"
DEFAULT_NOTIFY_MOBILE_SERVICE: Final = ""

# Optional local-Tuya transport. Stored shape: options[CONF_LOCAL_DEVICES]
#   [device_id] = {"host": "1.2.3.4", "version": 3.3, "rooms": {1: "Lounge"}}
CONF_LOCAL_DEVICES: Final = "local_devices"
CONF_LOCAL_HOST: Final = "host"
CONF_LOCAL_VERSION: Final = "version"
CONF_ROOM_NAMES: Final = "rooms"
# Manual override for the map id used in room/zone clean commands. Some
# devices (T2080A / S1 Pro) report their *cloud* map id (e.g. 2154) on the
# UniversalData DPS while the firmware only accepts the *local* map id
# (e.g. 1) in SelectRoomsClean / SET_ROOMS_CUSTOM — commands referencing the
# cloud id are ACKed but rejected (ModeCtrlResponse result=FAILED).
CONF_MAP_ID: Final = "map_id"
# Per-map variant of CONF_MAP_ID: maps the map id the device reports to the
# local map id to send, for robots with more than one map or a re-created map.
CONF_MAP_IDS: Final = "map_ids"

EUFY_API_BASE_URL: Final = "https://api.eufylife.com"
EUFY_HOME_API_BASE_URL: Final = "https://home-api.eufylife.com"
EUFY_AIOT_API_BASE_URL: Final = "https://aiot-clean-api-pr.eufylife.com"

EUFY_API_LOGIN: Final = f"{EUFY_HOME_API_BASE_URL}/v1/user/email/login"
# v2 unified-app login (eufy-app client credentials)
EUFY_API_LOGIN_V2: Final = f"{EUFY_HOME_API_BASE_URL}/v1/user/v2/email/login"
EUFY_API_USER_INFO: Final = f"{EUFY_API_BASE_URL}/v1/user/user_center_info"
EUFY_API_DEVICE_LIST: Final = (
    f"{EUFY_AIOT_API_BASE_URL}/app/devicerelation/get_device_list"
)
EUFY_API_DEVICE_V2: Final = f"{EUFY_API_BASE_URL}/v1/device/v2"
# Home-api device list fallback
EUFY_API_DEVICE_LIST_HOME: Final = f"{EUFY_HOME_API_BASE_URL}/v1/device/"

# Tuya productId -> Eufy model code: Tuya Cloud productIds have no Eufy v2 entry,
# so findModel() cannot match them (see EufyLogin._resolve_tuya_model).
TUYA_PRODUCT_MODELS: Final[dict[str, str]] = {
}
EUFY_API_MQTT_INFO: Final = (
    f"{EUFY_AIOT_API_BASE_URL}/app/devicemanage/get_user_mqtt_info"
)

# A SUBACK return code at or above this means the broker refused the
# subscription: 0x80 in MQTT 3.1.1, and every MQTT 5 failure reason code.
MQTT_SUBACK_FAILURE: Final = 0x80


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

# Station tank levels (DPS 173 StationResponse.WaterLevel)
STATION_WATER_LEVEL_NAMES = {
    StationResponse.EMPTY: "Empty",
    StationResponse.VERY_LOW: "Very low",
    StationResponse.LOW: "Low",
    StationResponse.MEDIUM: "Medium",
    StationResponse.HIGH: "High",
}


# DPS 154 clean extent
CLEANING_INTENSITY_NAMES = {
    0: "Normal",
    1: "Narrow",
    2: "Quick",
}

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


# Passes per room or zone the app offers; the services validate this range.
MIN_CLEAN_TIMES = 1
MAX_CLEAN_TIMES = 3
# Whole-house passes (AutoClean.clean_times) for START_AUTO_CLEAN. The Eufy app
# offers x1 and x2; start_auto clamps clean_times to this range.
AUTO_CLEAN_TIMES_MIN = MIN_CLEAN_TIMES
AUTO_CLEAN_TIMES_MAX = 2


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
    # Translated from proto/cloud/error_code_list_standard.proto:
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


CLEAN_TYPE_MAP = {
    # Keys are lowercase with spaces (see _normalize_clean_mode in commands.py).
    "vacuum": CleanType.SWEEP_ONLY,
    "mop": CleanType.MOP_ONLY,
    "vacuum mop": CleanType.SWEEP_AND_MOP,
    "vacuum and mop": CleanType.SWEEP_AND_MOP,
    "sweep and mop": CleanType.SWEEP_AND_MOP,
    "mopping after sweeping": CleanType.SWEEP_THEN_MOP,
}

CLEAN_EXTENT_MAP = {
    "fast": CleanExtent.QUICK,
    "standard": CleanExtent.NORMAL,
    "deep": CleanExtent.NARROW,
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

# Known DPS keys intentionally not parsed; raw values still land in raw_dps.
KNOWN_UNPROCESSED_DPS: frozenset[str] = frozenset(
    {
        DPS_MAP["DIRECTION"],  # 155 - RemoteCtrl echo
        DPS_MAP["MULTI_MAP_SW"],  # 156 - multi-map toggle (also in DPS 176)
        DPS_MAP["MAP_EDIT"],  # 164 - MapEditResponse ack
        DPS_MAP[
            "MAP_STREAM"
        ],  # 166 - debug/metadata on T2351 (map data is local P2P only)
        DPS_MAP["MAP_EDIT_REQUEST"],  # 170 - MapEditRequest echo
        # Unknown DPS keys:
        "150",
        "151",
        "159",
        "171",
        "174",
        "175",
        "178",  # unknown protobuf, timestamp/event log
    }
)

# Undocumented telemetry channel (no named entry in DPS_MAP)
DPS_ROBOT_TELEMETRY = "179"

# DPS 162 voice catalog: set_id → (label, base64 LanguageRequest). The payloads
# pin firmware-v22 voice-pack URLs and MD5s; a firmware move breaks them.
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


# Scalar (Tuya-style) DPS: plain ints/JSON on the Tuya DPS numbers over Anker
# MQTT, no protobuf. Detected from value shapes (api/cloud.py:checkApiType).
SCALAR_DPS = {
    "STATE": "15",  # Tuya STATUS, int
    "DETANGLE": "153",  # write 1 = start roller-brush detangle (read=0 in /res)
    # Work-mode command, also reported as a sub-state (see SCALAR_WORK_MODE_*).
    "WORK_MODE": "5",
    "PAUSE": "122",  # write 1=pause, 2=resume (also a /res motion flag: 1=stationary)
    "SUCTION": "102",  # Tuya FAN_SPEED: 0=Quiet 1=Standard 2=Turbo 3=Max
    "FIND_ROBOT": "103",  # Tuya LOCATE
    "BATTERY": "104",  # Tuya BATTERY_LEVEL: 0-100 %
    "DND": "107",  # Tuya DO_NOT_DISTURB: JSON {"en":bool,"start_t","end_t"}
    "CLEAN_TIME": "109",  # seconds
    "CLEAN_AREA": "110",  # m²
    "VOLUME": "111",  # voice volume 0-10 (=0-100% in 10% steps)
    "BOOST_IQ": "118",  # Tuya BOOST_IQ
    "AUTO_RETURN": "135",  # Tuya auto_return
    "CHILD_LOCK": "139",
    "ACTIVITY_LOG": "142",
    "SCHEDULE": "151",  # JSON {"l":[{e,t,r,s,f,id}]}
    "CLEAN_PATTERN": "154",  # 1=Arranged 2=Random, int not protobuf
    "ACCESSORIES": "150",  # JSON usage counters
    # 106 is canonical, but 177 also carries a code; read both, non-zero wins.
    "ERROR_CODE": "106",
    "ERROR_CODE_ALT": "177",
}

# DPS 15 state int -> activity string, same vocabulary as the novel parser.
SCALAR_STATE_NAMES = {
    0: "idle",
    1: "idle",
    2: "cleaning",
    4: "returning",
    5: "docked",  # charging
    6: "docked",  # charge complete
    7: "paused",
}

# BoostIQ is a separate switch (DPS 118) here, not a fifth speed.
SCALAR_SUCTION_LEVELS = [s.value for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED[:4]]

# DPS 154 clean path pattern
SCALAR_CLEAN_PATTERN_NAMES = {1: "Arranged", 2: "Random"}

SCALAR_WORK_MODE_START = 1
SCALAR_WORK_MODE_GO_HOME = 3

# Dock statuses that mean an operation is running; anything else resets to Idle.
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

# Legacy (Tuya Cloud) DPS keys: older G-, C- and S-series devices.
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
    "CONSUMABLES": "116",  # base64 JSON, hours used; keys from profiles.py specs
    # Write-only "mapData" request; renews the live pose/trail publish window,
    # which otherwise decays mid-clean.
    "MAP_KEEP_ALIVE": "121",
    "PAUSE_START": "122",  # explicit pause control: Nosweep / Pause / Continue
    "MAP_OPERATIONS": "124",
}

# Read-only stats: Tuya schema ``code`` -> fallback DPS number used when no schema
# was retrieved. DPS numbers are per-product, so a known schema resolves by code.
LEGACY_STAT_DPS_BY_CODE = {
    "ClearTime": "109",       # seconds
    "ClearArea": "110",       # m²
    "ClearTotalTime": "119",  # seconds
    "ClearTotalArea": "120",  # m²
    "consumables": LEGACY_DPS_MAP["CONSUMABLES"],
}

# Active-map id: base64 JSON carrying "cid"/"defaultID". Its schema code is the
# generic "waitRawDP", so it is matched by number and guarded by content.
LEGACY_MAP_ID_DPS = "125"

# Legacy DPS 15 status -> activity. "CC_" = return-to-charge mid-job, then resume.
LEGACY_WORK_STATUS_MAP = {
    "Running": "cleaning",
    "Cleaning": "cleaning",
    "cleaning": "cleaning",
    "Spot": "cleaning",
    "spot": "cleaning",
    "Goto": "cleaning",
    "goto": "cleaning",
    "Locating": "cleaning",
    "locating": "cleaning",
    "Charging": "docked",
    "charging": "docked",
    "CC_Charging": "docked",
    "Collecting": "docked",
    "RollAutoCleaning": "docked",
    "standby": "idle",
    "Standby": "idle",
    "Sleeping": "idle",
    "sleeping": "idle",
    "Sleep": "idle",
    "sleep": "idle",
    "Recharge": "returning",
    "recharge": "returning",
    "CC_Recharge": "returning",
    "Completed": "docked",
    "completed": "docked",
    "Fault": "error",
    "fault": "error",
    "Go Home": "returning",
    "Go_Home": "returning",
    "go_home": "returning",
}

# Legacy status strings that mean "on the dock, taking charge".
LEGACY_CHARGING_STATUSES = frozenset({"charging", "completed", "cc_charging"})

# Display names; a status string absent here is shown as-is.
LEGACY_TASK_STATUS_NAMES = {
    "RollAutoCleaning": "Cleaning Brush",
    "Collecting": "Emptying dust",
    "CC_Recharge": "Returning to Resume",
    "CC_Charging": "Charging to Resume",
    "Goto": "Going to Point",
    "Locating": "Locating",
    "standby": "Standby",
    "completed": "Completed",
}

# Legacy fan speeds, sent and received as plain strings.
LEGACY_CLEAN_SPEEDS = ["No_suction", "Standard", "Quiet", "Turbo", "Boost_IQ", "Max"]

# Per-room vocabularies for the DPS 124 ``customRooms`` document — not the DPS
# 102/105 enums, which carry an extra "off" member. Wire value = index + 1.
LEGACY_ROOM_FAN_LEVELS = ("Quiet", "Standard", "Turbo", "Max")
LEGACY_ROOM_WATER_LEVELS = ("Low", "Mid", "High")
# A customRooms write is replace-all, so every room in the document needs a value.
LEGACY_ROOM_DEFAULT_FAN = LEGACY_ROOM_FAN_LEVELS[1]
LEGACY_ROOM_DEFAULT_WATER = LEGACY_ROOM_WATER_LEVELS[1]
# Schedule (timer) DPS 124 documents, as the eufy app writes them: suction by
# name (Quiet..Boost_IQ), water by the per-room level (key) in the timer's own
# spelling.
LEGACY_SCHEDULE_FAN_LEVELS = tuple(s.value for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED)
LEGACY_SCHEDULE_WATER_MODES = {
    **dict(zip(LEGACY_ROOM_WATER_LEVELS, ("Low", "medium", "High"))),
    "Dry": "Dry",
}

LEGACY_WORK_MODES = {
    "auto": "Auto",
    "Nosweep": "No Sweep",
    "SmallRoom": "Small Room",
    "room": "Room",
    "zone": "Zone",
    "Edge": "Edge",
    "Spot": "Spot",
}

# Public app-level Tuya keys from upstream martijnpoppen/eufy-clean, not secrets.
TUYA_CLIENT_ID = "yx5v9uc3ef9wg3v9atje"
TUYA_SECRET = "s8x78u7xwymasd9kqa7a73pjhxqsedaj"
TUYA_SECRET2 = "cepev5pfnhua4dkqkdpmnrdxx378mpjr"
TUYA_CERT_SIGN = "A"
TUYA_API_ET_VERSION = "0.0.1"
TUYA_REGIONS = {
    "EU": "https://a1.tuyaeu.com/api.json",
    "US": "https://a1.tuyaus.com/api.json",
}

# Monday first: scalar DPS 151 keys days "1".."7" (Mon..Sun) and indexes this
# tuple; legacy Tuya `loops` is a Sunday-first bitmask (legacy_parser._LOOPS_DAYS).
WEEKDAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
)
WEEKDAY_ABBREVIATIONS = tuple(name[:3] for name in WEEKDAY_NAMES)

# Tuya Thing SDK credentials (et=3 transport)
TUYA_THING_CLIENT_ID = "w8x4ppqkdxvqnd73ahj9"
TUYA_THING_CHKEY = "7cbfe6d8"
TUYA_THING_SALT = (
    b"com.oceanwing.battery.cam_16:6C:23:45:57:B7:76:CA:D8:AC:94:C9:79:37:9E:48:DF:"
    b"38:7D:4D:8F:96:A3:43:DF:40:FC:D9:05:BF:F6:86_dn9erpyp7nmeuvah8ktghqsgpay87maa_"
    b"pt585qhmt75hwcynchnps9dnxh9suhwd"
)
