import base64
import logging

from constants.devices import EUFY_CLEAN_X_SERIES
from constants.state import (EUFY_CLEAN_CONTROL, EUFY_CLEAN_NOVEL_CLEAN_SPEED,
                             EUFY_CLEAN_WORK_MODE)
from lib.utils import decode, encode, get_multi_data, get_proto_file

from proto.cloud.control_pb2 import ModeCtrlRequest, ModeCtrlResponse

from .Base import Base


class SharedConnect(Base):
    def __init__(self, config):
        super().__init__()
        self.novel_api = False
        self.robovac_data = {}
        self.debug_log = config.get('debug', False)
        self.device_id = config['deviceId']
        self.device_model = config.get('deviceModel', '')
        self.config = {}

    async def check_api_type(self, dps):
        try:
            if not self.novel_api and any(k in dps for k in self.novel_dps_map.values()):
                print('Novel API detected')
                await self.set_api_types(True)
            else:
                print('Legacy API detected')
                await self.set_api_types(False)
        except Exception as error:
            logging.error('Error checking API type', error)

    async def set_api_types(self, novel_api):
        self.novel_api = novel_api
        self.dps_map = self.novel_dps_map if self.novel_api else self.legacy_dps_map
        self.robovac_data = self.dps_map.copy()

    async def map_data(self, dps):
        for key, value in dps.items():
            mapped_keys = [k for k, v in self.dps_map.items() if v == key]
            for mapped_key in mapped_keys:
                self.robovac_data[mapped_key] = value

        if self.debug_log:
            logging.debug('mappedData', self.robovac_data)

        await self.get_control_response()

    async def get_robovac_data(self):
        return self.robovac_data

    async def get_clean_speed(self):
        if isinstance(self.robovac_data.get('CLEAN_SPEED'), (int, list)) and len(self.robovac_data['CLEAN_SPEED']) == 1:
            clean_speeds = list(EUFY_CLEAN_NOVEL_CLEAN_SPEED.values())
            return clean_speeds[int(self.robovac_data['CLEAN_SPEED'])].lower()
        return self.robovac_data.get('CLEAN_SPEED', 'standard').lower()

    async def get_control_response(self):
        try:
            if self.novel_api:
                m = ModeCtrlResponse()
                v = base64.b64decode(self.robovac_data['PLAY_PAUSE'])
                m.MergeFromString(v)
                # m.ParseFromString(v)
                print('152 - control response', m)
                return m
                m.ParseFromString(self.robovac_data['PLAY_PAUSE'])
                value = await decode('./proto/cloud/control.proto', 'ModeCtrlResponse', self.robovac_data['PLAY_PAUSE'])
                print('152 - control response', value)
                return value or {}
            return None
        except Exception as error:
            logging.error(error, exc_info=error)
            return {}

    async def get_play_pause(self):
        return bool(self.robovac_data['PLAY_PAUSE'])

    async def get_work_mode(self):
        try:
            if self.novel_api:
                values = await get_multi_data('./proto/cloud/work_status.proto', 'WorkStatus', self.robovac_data['WORK_MODE'])
                mode = next((v for v in values if v['key'] == 'Mode'), None)
                return mode['value'].lower() if mode else 'auto'
            return self.robovac_data.get('WORK_MODE', 'auto').lower()
        except Exception:
            return 'auto'

    async def get_work_status(self):
        try:
            if self.novel_api:
                value = await decode('./proto/cloud/work_status.proto', 'WorkStatus', self.robovac_data['WORK_STATUS'])
                return value.get('state', 'charging').lower()
            return self.robovac_data.get('WORK_STATUS', 'charging').lower()
        except Exception:
            return 'charging'

    async def get_clean_params_request(self):
        try:
            if self.novel_api:
                value = await decode('./proto/cloud/clean_param.proto', 'CleanParamRequest', self.robovac_data.get('CLEANING_PARAMETERS'))
                return value or {}
            return self.robovac_data['WORK_STATUS']
        except Exception:
            return {}

    async def get_clean_params_response(self):
        try:
            if self.novel_api:
                value = await decode('./proto/cloud/clean_param.proto', 'CleanParamResponse', self.robovac_data.get('CLEANING_PARAMETERS'))
                return value or {}
            return None
        except Exception:
            return {}

    async def get_find_robot(self):
        return bool(self.robovac_data['FIND_ROBOT'])

    async def get_battery_level(self):
        return int(self.robovac_data['BATTERY_LEVEL'])

    async def get_error_code(self):
        try:
            if self.novel_api:
                value = await decode('./proto/cloud/error_code.proto', 'ErrorCode', self.robovac_data['ERROR_CODE'])
                if value.get('warn'):
                    return value['warn'][0]
                return 0
            return self.robovac_data['ERROR_CODE']
        except Exception as error:
            logging.error(error)

    async def set_clean_speed(self, clean_speed):
        try:
            if self.novel_api:
                set_clean_speed = list(EUFY_CLEAN_NOVEL_CLEAN_SPEED.values()).index(clean_speed.lower())
                print('Setting clean speed to:', set_clean_speed, list(EUFY_CLEAN_NOVEL_CLEAN_SPEED.values()), clean_speed)
                return await self.send_command({self.dps_map['CLEAN_SPEED']: set_clean_speed})
            print('Setting clean speed to:', clean_speed)
            return await self.send_command({self.dps_map['CLEAN_SPEED']: clean_speed})
        except Exception as error:
            logging.error(error)

    async def auto_clean(self):
        value = True
        if self.novel_api:
            value = await encode('proto/cloud/control.proto', 'ModeCtrlRequest', {'autoClean': {'cleanTimes': 1}})
            return await self.send_command({self.dps_map['PLAY_PAUSE']: value})
        await self.send_command({self.dps_map['WORK_MODE']: EUFY_CLEAN_WORK_MODE.AUTO})
        return await self.play()

    async def scene_clean(self, id):
        await self.stop()
        value = True
        increment = 3
        if self.novel_api:
            value = await encode('proto/cloud/control.proto', 'ModeCtrlRequest', {'method': EUFY_CLEAN_CONTROL.START_SCENE_CLEAN, 'sceneClean': {'sceneId': id + increment}})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def play(self):
        value = True
        if self.novel_api:
            value = await encode('proto/cloud/control.proto', 'ModeCtrlRequest', {'method': EUFY_CLEAN_CONTROL.RESUME_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def pause(self):
        value = False
        if self.novel_api:
            value = await encode('proto/cloud/control.proto', 'ModeCtrlRequest', {'method': EUFY_CLEAN_CONTROL.PAUSE_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def stop(self):
        value = False
        if self.novel_api:
            value = await encode('proto/cloud/control.proto', 'ModeCtrlRequest', {'method': EUFY_CLEAN_CONTROL.STOP_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def go_home(self):
        if self.novel_api:
            value = await encode('proto/cloud/control.proto', 'ModeCtrlRequest', {'method': EUFY_CLEAN_CONTROL.START_GOHOME})
            return await self.send_command({self.dps_map['PLAY_PAUSE']: value})
        return await self.send_command({self.dps_map['GO_HOME']: True})

    async def spot_clean(self):
        if self.novel_api:
            value = await encode('proto/cloud/control.proto', 'ModeCtrlRequest', {'method': EUFY_CLEAN_CONTROL.START_SPOT_CLEAN})
            return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def room_clean(self):
        if self.novel_api:
            value = await encode('proto/cloud/control.proto', 'ModeCtrlRequest', {'method': EUFY_CLEAN_CONTROL.START_SELECT_ROOMS_CLEAN})
            return await self.send_command({self.dps_map['PLAY_PAUSE']: value})
        if self.device_model in EUFY_CLEAN_X_SERIES:
            await self.send_command({self.dps_map['WORK_MODE']: EUFY_CLEAN_WORK_MODE.SMALL_ROOM})
            return await self.play()
        await self.send_command({self.dps_map['WORK_MODE']: EUFY_CLEAN_WORK_MODE.ROOM})
        return await self.play()

    async def set_clean_param(self, config):
        if not self.novel_api:
            return
        clean_param_proto = await get_proto_file('proto/cloud/clean_param.proto')
        clean_params = {
            'cleanType': clean_param_proto.lookup_type('CleanType').Value,
            'cleanExtent': clean_param_proto.lookup_type('CleanExtent').Value,
            'mopMode': clean_param_proto.lookup_type('MopMode').Level,
        }
        is_mop = config['cleanType'] in ['SWEEP_AND_MOP', 'MOP_ONLY']
        request_params = {
            'cleanParam': {
                **({'cleanType': {'value': clean_params['cleanType'][config['cleanType']]}} if config.get('cleanType') else {'cleanType': {}}),
                **({'cleanExtent': {'value': clean_params['cleanExtent'][config['cleanExtent']]}} if config.get('cleanExtent') else {'cleanExtent': {}}),
                **({'mopMode': {'level': clean_params['mopMode'][config['mopMode']]}} if config.get('mopMode') and is_mop else {'mopMode': {}}),
                'smartModeSw': {},
                'cleanTimes': 1
            }
        }
        print('setCleanParam - requestParams', request_params)
        value = await encode('proto/cloud/clean_param.proto', 'CleanParamRequest', request_params)
        await self.send_command({self.dps_map['CLEANING_PARAMETERS']: value})

    def format_status(self):
        print('formatted status:', self.robovac_data)

    async def send_command(self, data):
        raise NotImplementedError('Method not implemented.')
