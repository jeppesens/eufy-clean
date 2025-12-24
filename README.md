# Eufy-Clean (Home Assistant Custom Component)

## Overview
This repository is a maintained fork of [eufy-clean](https://github.com/jeppesens/eufy-clean) by [jeppesens](https://github.com/jeppesens), which was originally based on [eufy-clean](https://github.com/martijnpoppen/eufy-clean) by martijnpoppen.

This project provides an interface to interact with Eufy cleaning devices via MQTT, with a specific focus on maintaining a robust **Home Assistant Custom Component**. It allows you to control cleaning scenes, specific rooms, and manage station configurations (wash frequency, auto-empty, etc.) directly from your smart home dashboard.

## FAQ
- This repo only has support for MQTT enabled Eufy Vacuums, which means you need to have a device that supports MQTT. E.g the Robovac X10 Pro Omni.
- This code was ported and tested on a Robovac X10 Pro Omni, but it should work on other models as well 🤞🏼
- This is a personal project maintained for Home Assistant users. Contributions are welcome!

## Usage

### Installation via HACS
1.  Open HACS in Home Assistant.
2.  Add this repository as a custom repository.
3.  Install "Eufy Robovac MQTT".
4.  Restart Home Assistant.

### Configuration
1.  Go to Settings -> Devices & Services.
2.  Click "Add Integration".
3.  Search for "Eufy Robovac MQTT" and follow the setup flow.
4.  Login with your Eufy App credentials.

### Cleaning Scenes
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
*Note: The `scene` parameter corresponds to scene numbers. Default scenes are typically 1-3, with custom scenes starting from 4.*

### Cleaning Specific Rooms
To clean a specific room, you can use the following service call:
```yaml
action: vacuum.send_command
target:
  entity_id: vacuum.robovac_x10_pro_omni
data:
  command: room_clean
  map_id: 4
  params:
    rooms:
      - 3
      - 4
```
So which IDs are your rooms? Seems like when mapping it goes to the next room to the left, so leaving the room with the base station and going to the left it will be 1, then 2, and so on. And your basestation is located in the last room. I mapped the ids by using `vacuum.room_clean` service and looking at the app. Is there a better way? I hope so, but I don't know it.

> [!TIP]
> If you need get an issue like "Unable to identify position" most likely, there's not a bug in this repo, but you have had many maps, and your default map is higher. Keep trying, 20 is not an abnormally high number!

## Development
This project is maintained as a Home Assistant component. Issues and PRs should be relevant to the integration's functionality within Home Assistant.

### Pending Features
- Clean room(s) with custom cleaning mode
- Track consumables (dustbin, filter, etc.)
- Track errors
- Map management
- Locate device
- Current position

### Local Development & Testing
Included in this repository is a `docker-compose.yml` file to facilitate local testing of the integration.

1.  Ensure you have Docker and Docker Compose installed.
2.  Run `docker compose up` in the root directory.
3.  This will start a local Home Assistant instance accessible at `http://localhost:8123`.
4.  The `custom_components/robovac_mqtt` directory is mounted into the container, making the custom component available in Home Assistant.
5.  You will have to follow the steps mentioned in ### configuration to add your device to home assistant the first time you start the container. After that, you can stop the container and restart it whenever you want to make changes to the custom component.

## Contact
For any questions or issues, please open an issue on the GitHub repository.

---
<br>
<b>Happy Cleaning! 🧹✨</b>
