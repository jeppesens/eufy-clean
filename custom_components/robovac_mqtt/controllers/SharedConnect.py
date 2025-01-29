import logging
from typing import Any

from homeassistant.components.vacuum import VacuumActivity

from ..constants.state import (EUFY_CLEAN_CLEAN_SPEED, EUFY_CLEAN_CONTROL,
                               EUFY_CLEAN_NOVEL_CLEAN_SPEED)
from ..proto.cloud.clean_param_pb2 import (CleanExtent, CleanParamRequest,
                                           CleanParamResponse, CleanType,
                                           MopMode)
from ..proto.cloud.control_pb2 import ModeCtrlRequest, ModeCtrlResponse
from ..proto.cloud.error_code_pb2 import ErrorCode
from ..proto.cloud.work_status_pb2 import WorkStatus
from ..utils import decode, encode
from .Base import Base

_LOGGER = logging.getLogger(__name__)


class SharedConnect(Base):
    def __init__(self, config) -> None:
        super().__init__()
        self.debug_log = config.get('debug', False)
        self.device_id = config['deviceId']
        self.device_model = config.get('deviceModel', '')
        self.config = {}

    async def check_api_type(self, dps: dict[str, Any]):
        if any(k in dps for k in self.robovac_data.values()):
            print('Novel API detected')
        else:
            _LOGGER.error('Error checking API type')

    async def map_data(self, dps):
        for key, value in dps.items():
            mapped_keys = [k for k, v in self.dps_map.items() if v == key]
            for mapped_key in mapped_keys:
                self.robovac_data[mapped_key] = value

        if self.debug_log:
            _LOGGER.debug('mappedData', self.robovac_data)

        await self.get_control_response()

    async def get_robovac_data(self):
        return self.robovac_data

    async def get_clean_speed(self):
        if isinstance(self.robovac_data.get('CLEAN_SPEED'), (int, list)) and len(self.robovac_data['CLEAN_SPEED']) == 1:
            clean_speeds = list(EUFY_CLEAN_NOVEL_CLEAN_SPEED.values())
            return clean_speeds[int(self.robovac_data['CLEAN_SPEED'])].lower()
        return self.robovac_data.get('CLEAN_SPEED', 'standard').lower()

    async def get_control_response(self) -> ModeCtrlResponse | None:
        try:
            value = await decode(ModeCtrlResponse, self.robovac_data['PLAY_PAUSE'])
            print('152 - control response', value)
            return value or ModeCtrlResponse()
        except Exception as error:
            _LOGGER.error(error, exc_info=error)
            return ModeCtrlResponse()

    async def get_play_pause(self) -> bool:
        return bool(self.robovac_data['PLAY_PAUSE'])

    async def get_work_mode(self) -> str:
        try:
            value = await decode(WorkStatus, self.robovac_data['WORK_MODE'])
            mode = value.mode
            if not mode:
                return 'auto'
            else:
                _LOGGER.debug(f"Work mode: {mode}")

            # return mode.lower() if mode else 'auto'
        except Exception:
            return 'auto'

    async def get_work_status(self) -> str:
        try:
            value = await decode(WorkStatus, self.robovac_data['WORK_STATUS'])

            """
                STANDBY = 0
                SLEEP = 1
                FAULT = 2
                CHARGING = 3
                FAST_MAPPING = 4
                CLEANING = 5
                REMOTE_CTRL = 6
                GO_HOME = 7
                CRUISIING = 8
            """
            match value.state:
                case 0:
                    return VacuumActivity.IDLE
                case 1:
                    return VacuumActivity.IDLE
                case 2:
                    return VacuumActivity.ERROR
                case 3:
                    return VacuumActivity.DOCKED
                case 4:
                    return VacuumActivity.RETURNING  # this could be better...
                case 5:
                    if 'DRYING' in str(value.go_wash):
                        # drying up after a cleaning session
                        return VacuumActivity.DOCKED
                    return VacuumActivity.CLEANING
                case 6:
                    return VacuumActivity.CLEANING
                case 7:
                    return VacuumActivity.RETURNING
                case 8:
                    return VacuumActivity.CLEANING
                case _:
                    state_val = value.State.DESCRIPTOR.values_by_number[value.state]
                    _LOGGER.warning(f"Unknown state: {state_val.name}")
                    return VacuumActivity.IDLE
        except Exception:
            return VacuumActivity.ERROR

    async def get_clean_params_request(self):
        try:
            value = await decode(CleanParamRequest, self.robovac_data.get('CLEANING_PARAMETERS'))
            return value or CleanParamRequest()
        except Exception:
            return CleanParamRequest()

    async def get_clean_params_response(self):
        try:
            value = await decode(CleanParamResponse, self.robovac_data.get('CLEANING_PARAMETERS'))
            return value or {}
        except Exception:
            return {}

    async def get_find_robot(self) -> bool:
        return bool(self.robovac_data['FIND_ROBOT'])

    async def get_battery_level(self):
        return int(self.robovac_data['BATTERY_LEVEL'])

    async def get_error_code(self):
        try:
            value = await decode(ErrorCode, self.robovac_data['ERROR_CODE'])
            if value.get('warn'):
                return value['warn'][0]
            return 0
        except Exception as error:
            _LOGGER.error(error)

    async def set_clean_speed(self, clean_speed: EUFY_CLEAN_CLEAN_SPEED):
        try:
            set_clean_speed = list(EUFY_CLEAN_NOVEL_CLEAN_SPEED.values()).index(clean_speed.lower())
            print('Setting clean speed to:', set_clean_speed, list(EUFY_CLEAN_NOVEL_CLEAN_SPEED.values()), clean_speed)
            return await self.send_command({self.dps_map['CLEAN_SPEED']: set_clean_speed})
        except Exception as error:
            _LOGGER.error(error)

    async def auto_clean(self):
        value = await encode(ModeCtrlRequest, {'auto_clean': {'clean_times': 1}})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def scene_clean(self, id: int):
        increment = 3
        value = await encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_SCENE_CLEAN, 'scene_clean': {'scene_id': id + increment}})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def play(self):
        value = await encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.RESUME_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def pause(self):
        value = await encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.PAUSE_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def stop(self):
        value = await encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.STOP_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def go_home(self):
        value = await encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_GOHOME})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def spot_clean(self):
        value = await encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_SPOT_CLEAN})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def room_clean(self):
        value = await encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_SELECT_ROOMS_CLEAN})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def set_clean_param(self, config: dict[str, Any]):

        is_mop = False
        if ct := config.get('clean_type'):
            if ct not in CleanType.Value.keys():
                raise ValueError(f'Invalid clean type: {ct}, allowed values: {CleanType.Value.keys()}')
            if ct in ['SWEEP_AND_MOP', 'MOP_ONLY']:
                is_mop = True
            clean_type = {'value': CleanType.Value.DESCRIPTOR.values_by_name['SWEEP_AND_MOP'].number}
        else:
            clean_type = {}

        if ce := config.get('clean_extent'):
            if ce not in CleanExtent.Value.keys():
                raise ValueError(f'Invalid clean extent: {ce}, allowed values: {CleanExtent.keys()}')
            clean_extent = {'value': CleanExtent.Value.DESCRIPTOR.values_by_name[ce].number}
        else:
            clean_extent = {}

        if is_mop and (mm := config.get('mop_mode')):
            if mm not in MopMode.Level.keys():
                raise ValueError(f'Invalid mop mode: {mm}, allowed values: {MopMode.Level.keys()}')
            mop_mode = {'level': MopMode.Level.DESCRIPTOR.values_by_name[mm].number}
        else:
            mop_mode = {}
        if not is_mop and mop_mode:
            raise ValueError('Mop mode is not allowed for non-mop commands')

        request_params = {
            'clean_param': {
                'clean_type': clean_type,
                'clean_extent': clean_extent,
                'mop_mode': mop_mode,
                'smart_mode_sw': {},
                'clean_times': 1
            }
        }
        print('setCleanParam - requestParams', request_params)
        value = await encode(CleanParamRequest, request_params)
        await self.send_command({self.dps_map['CLEANING_PARAMETERS']: value})

    def format_status(self):
        print('formatted status:', self.robovac_data)

    async def send_command(self, data):
        raise NotImplementedError('Method not implemented.')
