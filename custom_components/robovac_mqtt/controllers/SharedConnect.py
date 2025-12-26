import asyncio
import logging
from typing import Any, Callable
import base64

from homeassistant.components.vacuum import VacuumActivity

from ..constants.devices import EUFY_CLEAN_DEVICES
from ..constants.state import (EUFY_CLEAN_CLEAN_SPEED, EUFY_CLEAN_CONTROL,
                               EUFY_CLEAN_NOVEL_CLEAN_SPEED)
from ..proto.cloud.clean_param_pb2 import (CleanExtent, CleanParamRequest,
                                           CleanParamResponse, CleanType,
                                           MopMode)
from ..proto.cloud.control_pb2 import (ModeCtrlRequest, ModeCtrlResponse,
                                       SelectRoomsClean)
from ..proto.cloud.station_pb2 import (
    StationRequest, ManualActionCmd, StationResponse, AutoActionCfg,
    WashCfg, DryCfg, CollectDustCfg, CollectDustCfgV2
)
from ..proto.cloud.error_code_pb2 import ErrorCode
from ..proto.cloud.work_status_pb2 import WorkStatus
from ..proto.cloud.scene_pb2 import SceneResponse
from ..proto.cloud.universal_data_pb2 import UniversalDataResponse
from ..proto.cloud.stream_pb2 import RoomParams
from ..utils import decode, encode, encode_message
from .Base import Base

_LOGGER = logging.getLogger(__name__)

class SharedConnect(Base):
    def __init__(self, config) -> None:
        super().__init__()
        self.debug_log = config.get('debug', False)
        self.device_id = config['deviceId']
        self.device_model = config.get('deviceModel', '')
        self.device_model_desc = EUFY_CLEAN_DEVICES.get(self.device_model, '') or self.device_model
        self.config = {}
        self._update_listeners = []
        self.rooms = []
        self.map_id = None
        self.releases = None
        self.map_save_sw = False

    _update_listeners: list[Callable[[], None]]

    async def _map_data(self, dps):
        for key, value in dps.items():
            mapped_keys = [k for k, v in self.dps_map.items() if v == key]
            for mapped_key in mapped_keys:
                self.robovac_data[mapped_key] = value

        if self.debug_log:
            _LOGGER.debug('mappedData %r', self.robovac_data)

        # dump mapping / raw payloads for debugging
        try:
            _LOGGER.debug("dps_map -> %r", self.dps_map)
            for k, v in self.robovac_data.items():
                if isinstance(v, (bytes, bytearray)):
                    _LOGGER.debug("robovac_data[%s] type=%s len=%d hex=%s", k, type(v).__name__, len(v), v.hex())
                elif isinstance(v, str):
                    # show repr and hex of underlying bytes (latin-1 keeps 1:1 mapping)
                    try:
                        hexed = v.encode('latin-1').hex()
                    except Exception:
                        hexed = repr(v)
                    _LOGGER.debug("robovac_data[%s] type=str repr=%r hex=%s", k, v, hexed)
                else:
                    _LOGGER.debug("robovac_data[%s] type=%s repr=%r", k, type(v).__name__, v)
        except Exception:
            _LOGGER.exception("Failed to dump robovac_data debug info")

        await self.get_control_response()
        for listener in self._update_listeners:
            try:
                _LOGGER.debug("Calling listener %s", getattr(listener, "__name__", repr(listener)))
                if asyncio.iscoroutinefunction(listener):
                    await listener()
                else:
                    listener()
            except Exception as error:
                _LOGGER.error("Listener error: %s", error)


    def add_listener(self, listener: Callable[[], None]):
        """Fixed: Changed type annotation to match actual usage"""
        self._update_listeners.append(listener)

    async def get_robovac_data(self):
        return self.robovac_data

    async def get_clean_speed(self):
        """Fixed: Better handling of different data types for clean speed"""
        clean_speed_raw = self.robovac_data.get('CLEAN_SPEED')
        
        if clean_speed_raw is None:
            return 'standard'
        
        try:
            # Handle list with single element
            if isinstance(clean_speed_raw, list) and len(clean_speed_raw) > 0:
                speed = int(clean_speed_raw[0])  # Fixed: use [0] instead of treating list as int
                if 0 <= speed < len(EUFY_CLEAN_NOVEL_CLEAN_SPEED):
                    return EUFY_CLEAN_NOVEL_CLEAN_SPEED[speed].lower()
            
            # Handle integer directly
            elif isinstance(clean_speed_raw, int):
                if 0 <= clean_speed_raw < len(EUFY_CLEAN_NOVEL_CLEAN_SPEED):
                    return EUFY_CLEAN_NOVEL_CLEAN_SPEED[clean_speed_raw].lower()
            
            # Handle string that's a digit
            elif isinstance(clean_speed_raw, str) and clean_speed_raw.isdigit():
                speed = int(clean_speed_raw)
                if 0 <= speed < len(EUFY_CLEAN_NOVEL_CLEAN_SPEED):
                    return EUFY_CLEAN_NOVEL_CLEAN_SPEED[speed].lower()
            
            # Handle string that's already a speed name
            elif isinstance(clean_speed_raw, str):
                return clean_speed_raw.lower()
            
        except (IndexError, ValueError, TypeError) as e:
            _LOGGER.warning(f"Error processing clean speed {clean_speed_raw}: {e}")
        
        # Default fallback
        return 'standard'

    async def get_control_response(self) -> ModeCtrlResponse | None:
        try:
            raw = self.robovac_data.get('PLAY_PAUSE')
            if raw is None:
                _LOGGER.debug("get_control_response: PLAY_PAUSE missing from robovac_data")
                return ModeCtrlResponse()
            value = decode(ModeCtrlResponse, raw)
            _LOGGER.debug("152 - control response: %r", value)
            return value or ModeCtrlResponse()
        except Exception as error:
             _LOGGER.error(error, exc_info=error)
             return ModeCtrlResponse()
                
    async def get_play_pause(self) -> bool:
        return bool(self.robovac_data['PLAY_PAUSE'])

    async def get_work_mode(self) -> str:
        try:
            value = decode(WorkStatus, self.robovac_data['WORK_MODE'])
            mode = value.mode
            if not mode:
                return 'auto'
            else:
                _LOGGER.debug(f"Work mode: {mode}")
                return mode.lower() if mode else 'auto'  # Fixed: actually return the mode
        except Exception:
            return 'auto'

    async def get_work_status(self) -> str:
        try:
            value = decode(WorkStatus, self.robovac_data['WORK_STATUS'])

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
                    # Fixed: Handle case where state is not in the known values
                    if hasattr(value, 'State') and hasattr(value.State, 'DESCRIPTOR'):
                        state_val = value.State.DESCRIPTOR.values_by_number.get(value.state)
                        if state_val:
                            _LOGGER.warning(f"Unknown state: {state_val.name}")
                        else:
                            _LOGGER.warning(f"Unknown state number: {value.state}")
                    else:
                        _LOGGER.warning(f"Unknown state: {value.state}")
                    return VacuumActivity.IDLE
        except Exception as e:
            _LOGGER.error(f"Error getting work status: {e}")
            return VacuumActivity.ERROR

    async def get_clean_params_request(self):
        try:
            value = decode(CleanParamRequest, self.robovac_data.get('CLEANING_PARAMETERS'))
            return value
        except Exception as e:
            _LOGGER.error('Error getting clean params', exc_info=e)
            return CleanParamRequest()

    async def get_clean_params_response(self):
        try:
            value = decode(CleanParamResponse, self.robovac_data.get('CLEANING_PARAMETERS'))
            return value or {}
        except Exception:
            return {}

    async def get_find_robot(self) -> bool:
        return bool(self.robovac_data['FIND_ROBOT'])

    async def get_battery_level(self):
        return int(self.robovac_data['BATTERY_LEVEL'])
    
    async def get_dock_status(self) -> str:
        try:
            value = decode(StationResponse, self.robovac_data['STATION_STATUS'])
            _LOGGER.debug("173 - dock status: %r", value)
            ## These are separate booleans rather than being part of the state enum ¯\_(ツ)_/¯
            if value.status.collecting_dust:
                return "Emptying dust"
            if value.status.clear_water_adding:
                return "Adding clean water"
            if value.status.waste_water_recycling:            
                return "Recycling waste water"
            if value.status.disinfectant_making:            
                return "Making disinfectant"
            if value.status.cutting_hair:            
                return "Cutting hair"

            state = value.status.state
            state_name = StationResponse.StationStatus.State.Name(state)
            state_string = state_name.strip().lower().replace('_', ' ')
            return state_string[:1].upper() + state_string[1:]
        except Exception as e:
            _LOGGER.error(f"Error getting dock status: {e}")
            return None

    async def get_water_level(self) -> int:
        try:
            value = decode(StationResponse, self.robovac_data['STATION_STATUS'])
            _LOGGER.debug("173 - dock status: %r", value)
            return value.clean_water.value
        except Exception as e:
            _LOGGER.error(f"Error getting dock water level: {e}")
            return None
    
    async def get_error_code(self):
        try:
            value = decode(ErrorCode, self.robovac_data['ERROR_CODE'])
            if value.get('warn'):
                return value['warn'][0]
            return 0
        except Exception as error:
            _LOGGER.error(error)

    async def get_auto_action_cfg(self):
        try:
            value = decode(StationResponse, self.robovac_data['STATION_STATUS'])
            return value.auto_cfg_status
        except Exception as e:
            _LOGGER.error(f"Error getting auto action cfg: {e}")
            return None

    async def set_auto_action_cfg(self, cfg: dict):
        try:
            value = encode(StationRequest, {'auto_cfg': cfg})
            return await self.send_command({self.dps_map['GO_HOME']: value})
        except Exception as e:
            _LOGGER.error(f"Error setting auto action cfg: {e}")
            raise

    async def get_scene_list(self) -> list[dict[str, Any]]:
        """Get list of available cleaning scenes from DPS 180."""
        try:
            # DPS 180 contains SceneResponse protobuf
            scene_data = self.robovac_data.get('SCENE_INFO')
            if not scene_data:
                _LOGGER.warning("No scene data available (DPS 180)")
                return []
            
            # Try decoding with has_length=True (like other DPS data)
            _LOGGER.debug(f"Attempting to decode scene data (length: {len(scene_data)})")
            scene_response = decode(SceneResponse, scene_data, has_length=True)
            
            if not scene_response or not scene_response.infos:
                _LOGGER.debug("SceneResponse decoded but no infos found")
                return []
            
            _LOGGER.debug(f"SceneResponse has {len(scene_response.infos)} scene infos")
            scenes = []
            for scene_info in scene_response.infos:
                # Only include valid scenes with names (mirroring official app)
                if scene_info.name and scene_info.valid:
                    scenes.append({
                        'id': scene_info.id.value if scene_info.HasField('id') else 0,
                        'name': scene_info.name,
                        'type': scene_info.type,
                    })
            
            _LOGGER.debug(f"Found {len(scenes)} valid scenes from DPS 180")
            return scenes
        except Exception as e:
            _LOGGER.error(f"Error getting scene list: {e}", exc_info=True)
            return []

    async def get_map_info(self) -> dict[str, Any] | None:
        """Get list of available maps and rooms from DPS 165."""
        try:
            map_data = self.robovac_data.get('MAP_DATA')
            if not map_data:
                return None
            
            _LOGGER.debug(f"Attempting to decode map data from DPS 165 (length: {len(map_data)})")
            
            # UniversalDataResponse check (UniversalDataResponse has RoomTable cur_map_room)
            try:
                universal_data = decode(UniversalDataResponse, map_data, has_length=True)
                if universal_data and universal_data.cur_map_room.map_id:
                     rooms = [{'id': r.id, 'name': r.name} for r in universal_data.cur_map_room.data]
                     _LOGGER.debug("Successfully decoded DPS 165 as UniversalDataResponse: map_id=%d, rooms=%r", 
                                  universal_data.cur_map_room.map_id, rooms)
                     self.map_id = universal_data.cur_map_room.map_id
                     self.rooms = rooms
                     return {
                         'map_id': self.map_id,
                         'rooms': self.rooms
                     }
            except Exception:
                _LOGGER.debug("Failed to decode DPS 165 as UniversalDataResponse")

            # RoomParams check (RoomParams has repeated Room rooms)
            try:
                room_params = decode(RoomParams, map_data, has_length=True)
                if room_params and room_params.map_id:
                    rooms = [{'id': r.id, 'name': r.name} for r in room_params.rooms]
                    _LOGGER.debug("Successfully decoded DPS 165 as RoomParams: map_id=%d, releases=%d, rooms=%r", 
                                  room_params.map_id, room_params.releases, rooms)
                    self.map_id = room_params.map_id
                    self.releases = room_params.releases
                    self.rooms = rooms
                    return {
                        'map_id': self.map_id,
                        'releases': self.releases,
                        'rooms': self.rooms
                    }
            except Exception:
                 _LOGGER.debug("Failed to decode DPS 165 as RoomParams")

            return None
        except Exception as e:
            _LOGGER.error(f"Error getting map info: {e}", exc_info=True)
            return None

    async def get_active_map_id(self) -> int | None:
        """Get the ID of the currently active map."""
        await self.get_map_info()
        return self.map_id


    async def set_clean_speed(self, clean_speed: EUFY_CLEAN_CLEAN_SPEED):
        try:
            set_clean_speed = [s.lower() for s in EUFY_CLEAN_NOVEL_CLEAN_SPEED].index(clean_speed.lower())
            _LOGGER.debug("Setting clean speed to: %r %r %r", set_clean_speed, EUFY_CLEAN_NOVEL_CLEAN_SPEED, clean_speed)
            return await self.send_command({self.dps_map['CLEAN_SPEED']: set_clean_speed})
        except Exception as error:
            _LOGGER.error(error)

    async def auto_clean(self):
        value = encode(ModeCtrlRequest, {'auto_clean': {'clean_times': 1}})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def scene_clean(self, id: int):
        increment = 3
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_SCENE_CLEAN, 'scene_clean': {'scene_id': id + increment}})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def play(self):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.RESUME_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def pause(self):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.PAUSE_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def stop(self):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.STOP_TASK})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def go_home(self):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_GOHOME})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def go_dry(self):
        value = encode(StationRequest, {'manual_cmd': {'go_dry': True}})
        return await self.send_command({self.dps_map['GO_HOME']: value})
    
    async def stop_dry_mop(self):
        value = encode(StationRequest, {'manual_cmd': {'go_dry': False}})
        return await self.send_command({self.dps_map['GO_HOME']: value})

    async def go_selfcleaning(self):
        value = encode(StationRequest, {'manual_cmd': {'go_selfcleaning': True}})
        return await self.send_command({self.dps_map['GO_HOME']: value})

    async def collect_dust(self):
        value = encode(StationRequest, {'manual_cmd': {'go_collect_dust': True}})
        return await self.send_command({self.dps_map['GO_HOME']: value})

    async def spot_clean(self):
        value = encode(ModeCtrlRequest, {'method': EUFY_CLEAN_CONTROL.START_SPOT_CLEAN})
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def room_clean(self, room_ids: list[int], map_id: int = 3):
        _LOGGER.debug(f'Room clean: {room_ids}, map_id: {map_id}')
        rooms_clean = SelectRoomsClean(
            rooms=[SelectRoomsClean.Room(id=id, order=i + 1) for i, id in enumerate(room_ids)],
            mode=SelectRoomsClean.Mode.DESCRIPTOR.values_by_name['GENERAL'].number,
            clean_times=1,
            map_id=map_id,
        )
        value = encode_message(ModeCtrlRequest(method=EUFY_CLEAN_CONTROL.START_SELECT_ROOMS_CLEAN, select_rooms_clean=rooms_clean))
        return await self.send_command({self.dps_map['PLAY_PAUSE']: value})

    async def set_clean_param(self, config: dict[str, Any]):
        is_mop = False
        if ct := config.get('clean_type'):
            if ct not in CleanType.Value.keys():
                raise ValueError(f'Invalid clean type: {ct}, allowed values: {CleanType.Value.keys()}')
            if ct in ['SWEEP_AND_MOP', 'MOP_ONLY']:
                is_mop = True
            clean_type = {'value': CleanType.Value.DESCRIPTOR.values_by_name[ct].number}
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
        _LOGGER.debug('setCleanParam - requestParams', request_params)
        value = encode(CleanParamRequest, request_params)
        await self.send_command({self.dps_map['CLEANING_PARAMETERS']: value})

    async def send_command(self, data) -> None:
        raise NotImplementedError('Method not implemented.')