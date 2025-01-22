from enum import Enum


class EUFY_CLEAN_GET_STATE(str, Enum):
    sleeping = 'stopped'
    standby = 'docked'
    recharge = 'docked'
    running = 'cleaning'
    cleaning = 'cleaning'
    spot = 'spot_cleaning'
    completed = 'docked'
    charging = 'charging'
    sleep = 'stopped'
    go_home = 'docked'
    fault = 'stopped'


class EUFY_CLEAN_VACUUMCLEANER_STATE(str, Enum):
    STOPPED = 'stopped'
    CLEANING = 'cleaning'
    SPOT_CLEANING = 'spot_cleaning'
    DOCKED = 'docked'
    CHARGING = 'charging'


class EUFY_CLEAN_CLEAN_SPEED(str, Enum):
    NO_SUCTION = 'No_suction'
    STANDARD = 'Standard'
    QUIET = 'Quiet'
    TURBO = 'Turbo'
    BOOST_IQ = 'Boost_IQ'
    MAX = 'Max'


EUFY_CLEAN_NOVEL_CLEAN_SPEED = [
    EUFY_CLEAN_CLEAN_SPEED.QUIET,
    EUFY_CLEAN_CLEAN_SPEED.STANDARD,
    EUFY_CLEAN_CLEAN_SPEED.TURBO,
    EUFY_CLEAN_CLEAN_SPEED.MAX,
]

EUFY_CLEAN_LEGACY_CLEAN_SPEED = [
    EUFY_CLEAN_CLEAN_SPEED.NO_SUCTION,
    EUFY_CLEAN_CLEAN_SPEED.BOOST_IQ
]


class EUFY_CLEAN_GET_CLEAN_SPEED(str, Enum):
    no_suction = 'No Suction'
    standard = 'Standard'
    quiet = 'Quiet'
    turbo = 'Turbo'
    boost_iq = 'Boost IQ'
    max = 'Max'


class EUFY_CLEAN_WORK_STATUS(str, Enum):
    # Cleaning
    RUNNING = 'Running'
    # In the dock, charging
    CHARGING = 'Charging'
    # Not in the dock, paused
    STAND_BY = 'standby'
    # Not in the dock - goes into this state after being paused for a while
    SLEEPING = 'Sleeping'
    # Going home because battery is depleted
    RECHARGE_NEEDED = 'Recharge'
    RECHARGE = 'Recharge'
    # In the dock, full charged
    COMPLETED = 'Completed'
    STANDBY = 'Standby'
    SLEEP = 'Sleep'
    FAULT = 'Fault'
    FAST_MAPPING = 'Fast Mapping'
    CLEANING = 'Cleaning'
    REMOTE_CTRL = 'Remote Ctrl'
    GO_HOME = 'Go Home'
    CRUISIING = 'Cruising'


class EUFY_CLEAN_WORK_MODE(str, Enum):
    AUTO = 'auto'
    NO_SWEEP = 'Nosweep'
    SMALL_ROOM = 'SmallRoom'
    ROOM = 'room'
    ZONE = 'zone'
    EDGE = 'Edge'
    SPOT = 'Spot'


class EUFY_CLEAN_CONTROL(str, Enum):
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
    0: 'NONE',
    1: 'CRASH BUFFER STUCK',
    2: 'WHEEL STUCK',
    3: 'SIDE BRUSH STUCK',
    4: 'ROLLING BRUSH STUCK',
    5: 'HOST TRAPPED CLEAR OBST',
    6: 'MACHINE TRAPPED MOVE',
    7: 'WHEEL OVERHANGING',
    8: 'POWER LOW SHUTDOWN',
    13: 'HOST TILTED',
    14: 'NO DUST BOX',
    17: 'FORBIDDEN AREA DETECTED',
    18: 'LASER COVER STUCK',
    19: 'LASER SENSOR STUCK',
    20: 'LASER BLOCKED',
    21: 'DOCK FAILED',
    26: 'POWER APPOINT START FAIL',
    31: 'SUCTION PORT OBSTRUCTION',
    32: 'WIPE HOLDER MOTOR STUCK',
    33: 'WIPING BRACKET MOTOR STUCK',
    39: 'POSITIONING FAIL CLEAN END',
    40: 'MOP CLOTH DISLODGED',
    41: 'AIRDRYER HEATER ABNORMAL',
    50: 'MACHINE ON CARPET',
    51: 'CAMERA BLOCK',
    52: 'UNABLE LEAVE STATION',
    55: 'EXPLORING STATION FAIL',
    70: 'CLEAN DUST COLLECTOR',
    71: 'WALL SENSOR FAIL',
    72: 'ROBOVAC LOW WATER',
    73: 'DIRTY TANK FULL',
    74: 'CLEAN WATER LOW',
    75: 'WATER TANK ABSENT',
    76: 'CAMERA ABNORMAL',
    77: '3D TOF ABNORMAL',
    78: 'ULTRASONIC ABNORMAL',
    79: 'CLEAN TRAY NOT INSTALLED',
    80: 'ROBOVAC COMM FAIL',
    81: 'SEWAGE TANK LEAK',
    82: 'CLEAN TRAY NEEDS CLEAN',
    83: 'POOR CHARGING CONTACT',
    101: 'BATTERY ABNORMAL',
    102: 'WHEEL MODULE ABNORMAL',
    103: 'SIDE BRUSH ABNORMAL',
    104: 'FAN ABNORMAL',
    105: 'ROLLER BRUSH MOTOR ABNORMAL',
    106: 'HOST PUMP ABNORMAL',
    107: 'LASER SENSOR ABNORMAL',
    111: 'ROTATION MOTOR ABNORMAL',
    112: 'LIFT MOTOR ABNORMAL',
    113: 'WATER SPRAY ABNORMAL',
    114: 'WATER PUMP ABNORMAL',
    117: 'ULTRASONIC ABNORMAL',
    119: 'WIFI BLUETOOTH ABNORMAL',
}
