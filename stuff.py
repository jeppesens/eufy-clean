import asyncio
import os

from custom_components.robovac_mqtt.main import EufyClean


async def setup():
    eufy_clean = EufyClean(os.getenv('EUFY_USERNAME'), os.getenv('EUFY_PASSWORD'))
    await eufy_clean.init()
    devices = await eufy_clean.get_devices()
    print(devices)

    device_id = next((d['deviceId'] for d in devices if d), None)
    if not device_id:
        return
    device = await eufy_clean.init_device(device_id)
    await device.connect()
    print(device)
    status = await device.get_work_status()
    print(status)
    battery_level = await device.get_battery_level()
    print(battery_level)
    # await device.set_clean_param({'clean_type': 'SWEEP_ONLY'})
    """
    // full home daily clean: 1
    home: 1,
    // full home deep clean: 2
    // Post-Meal Clean: 3
    morning: 4,
    afternoon: 5,
    weekly: 6,
    """
    await device.scene_clean(4)
    # await device.play()
    # await device.go_home()
    status = await device.get_work_status()
    mode = await device.get_work_mode()
    print(status, mode)


if __name__ == '__main__':
    import dotenv
    dotenv.load_dotenv()
    asyncio.run(setup())
