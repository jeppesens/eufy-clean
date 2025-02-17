import asyncio
import os

from custom_components.robovac_mqtt.EufyClean import EufyClean


async def setup():
    eufy_clean = EufyClean(os.getenv('EUFY_USERNAME'), os.getenv('EUFY_PASSWORD'))
    await eufy_clean.init()
    devices = await eufy_clean.get_devices()
    print(devices)

    device_id = next((d['deviceId'] for d in devices if d), None)
    if not device_id:
        return
    vacuum = await eufy_clean.init_device(device_id)
    await vacuum.connect()
    print(vacuum)
    status = await vacuum.get_work_status()
    print(status)
    battery_level = await vacuum.get_battery_level()
    print(battery_level)
    params = await vacuum.get_clean_params_response()
    print(params)
    x = eufy_clean.eufyCleanApi.tuya_api.list_homes()
    print(x)
    y = eufy_clean.eufyCleanApi.tuya_api.get_device_list()

    for device in y:
        print(device)
        z = eufy_clean.eufyCleanApi.tuya_api.get_device(device['devId'])
        print(z)

    # dining room - 1
    # tv room - 2
    # entrance - 3
    # playroom - 4
    # kitchen - 6
    # downstairs bathroom - 7
    await vacuum.room_clean([7])
    status = await vacuum.get_work_status()
    await vacuum.go_home()
    print(status)

    # await vacuum.go_home()
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
    # await device.scene_clean(4)
    # await device.play()
    # await device.go_home()
    speed = await vacuum.get_clean_speed()
    print(speed)
    status = await vacuum.get_work_status()
    mode = await vacuum.get_work_mode()
    print(status, mode)


if __name__ == '__main__':
    import dotenv
    dotenv.load_dotenv()
    asyncio.run(setup())
