# Eufy-Clean
## Overview
This Eufy Clean repo provides an interface to interact with Eufy cleaning devices. It includes functionalities to login, pair new devices, and manage cleaning operations through cloud and MQTT connections.
It is originally based on [eufy-clean](https://github.com/martijnpoppen/eufy-clean) by [martijnpoppen](https://github.com/martijnpoppen) but has been rewritten to use Python and adding support for Home Assistant.

## FAQ
- This repo only has support for MQTT enabled Eufy Vacuums, which means you need to have a device that supports MQTT. E.g the Robovac X10 Pro Omni.
- This code was ported and tested on a Robovac X10 Pro Omni, but it should work on other models as well 🤞🏼
- This code is written by me for me, feel free to use it and open issues, and PRs. I will try to help as much as I can, but I can't guarantee anything.


## Usage

### Home Assistant
If you want to use this code with Home Assistant, you should be able to install it with HACS by adding this repo.

To clean scenes, you can use the following service call:
```yaml
action: vacuum.send_command
metadata: {}
data:
    command: scene_clean
    params:
        scene: 5
target:
    entity_id: vacuum.robovac_x10_pro_omni
```
worth noting that the `scene` parameter is the scene number, which I have just guessed based on the app.
Seems like there is 3 default scenes end then your scenes start from 4 and increments one in the order you created them.

To clean a specific room, you can use the following service call:
```yaml
action: vacuum.send_command
target:
  entity_id: vacuum.robovac_x10_pro_omni
data:
  command: room_clean
  params:
    rooms:
      - 3
      - 4
```
So which IDs are your rooms? Seems like when mapping it goes to the next room to the left, so leaving the room with the base station and going to the left it will be 1, then 2, and so on. And your basestation is located in the last room. I mapped the ids by using `vacuum.room_clean` service and looking at the app. Is there a better way? I hope so, but I don't know it.

### Example
If you want to use this code without using Home Assistant, you can use the `EufyClean` class directly. Here's a simple example of how to use it:

```py
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
    device = await eufy_clean.init_device(device_id)
    await device.connect()
    print(device)
    status = await device.get_work_status()
    print(status)
    battery_level = await device.get_battery_level()
    print(battery_level)
    await device.go_home()
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
```

## Development
There is things left to do here, like adding more commands and testing on other devices. If you want to help, feel free to open a PR.
- Clean rooms
- Track consumables, water, dustbin, and filter etc
- Track errors
- Map management
- Many more...

## Contact
For any questions or issues, please open an issue on the GitHub repository.

---
<br>
<b>Happy Cleaning! 🧹✨</b>
