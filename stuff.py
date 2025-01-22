import asyncio
import os

from main import EufyClean


async def setup():
    eufy_clean = EufyClean(os.getenv('EUFY_USERNAME'), os.getenv('EUFY_PASSWORD'))
    await eufy_clean.init()
    devices = await eufy_clean.getAllDevices()
    print(devices)

    device_id = next((d['deviceId'] for d in devices if d), None)
    if not device_id:
        return
    device = await eufy_clean.initDevice({'deviceId': device_id})
    await device.connect()
    print(device)
    # await device.set_clean_param({'cleanType': 'SWEEP_ONLY'})
    # await device.scene_clean(0)
    # await device.play()
    # await device.go_home()

asyncio.run(setup())

if __name__ == '__main__':
    import dotenv
    dotenv.load_dotenv()
