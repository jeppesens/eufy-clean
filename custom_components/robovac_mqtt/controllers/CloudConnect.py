from typing import Any

from .Login import EufyLogin
from .SharedConnect import SharedConnect


class CloudConnect(SharedConnect):
    def __init__(self, config: dict[str, Any], eufy_clean_api: EufyLogin):
        super().__init__(config)

        self.device_id: str = config['deviceId']
        self.device_model: str = config['deviceModel']
        self.config = config

        self.auto_update = config.get('autoUpdate', 0)
        self.eufy_clean_api = eufy_clean_api

    async def connect(self):
        await self.update_device(True)

    async def update_device(self, check_api_type=False):
        try:
            device = await self.eufy_clean_api.get_cloud_device(self.device_id)

            if check_api_type:
                await self.check_api_type(device.get('dps'))

            await self.map_data(device.get('dps'))
        except Exception as error:
            print(error)

    async def send_command(self, data: dict):
        try:
            await self.eufy_clean_api.send_cloud_command(self.device_id, data)
        except Exception as error:
            print(error)
