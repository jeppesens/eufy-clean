---
applyTo: '**'
---
Coding standards, domain knowledge, and preferences that AI should follow.


# Eufy-Clean Copilot Instructions

## Project Overview
Eufy-Clean is a Python-based interface for interacting with Eufy cleaning devices (robot vacuums), particularly those that support MQTT connections. The project provides:

1. A Home Assistant integration (custom component) for controlling Eufy vacuums
2. A standalone Python library for controlling Eufy devices outside of Home Assistant
3. Support for login, device discovery, and various cleaning operations

This project was originally based on [eufy-clean](https://github.com/martijnpoppen/eufy-clean) by martijnpoppen but has been rewritten in Python with Home Assistant support.

## Project Structure

### Key Components

- `/custom_components/robovac_mqtt/` - The Home Assistant custom component
  - `EufyClean.py` - Main class for initializing the API and discovering devices
  - `EufyApi.py` - Handles API communication with Eufy Cloud
  - `vacuum.py` - Home Assistant vacuum entity implementation
  - `controllers/` - Contains the core control logic:
    - `Login.py` - Handles authentication with Eufy services
    - `MqttConnect.py` - Manages MQTT connections to control devices
    - `SharedConnect.py` - Common code for device connections
  - `constants/` - Enum definitions and constants
  - `proto/` - Protobuf definitions for API communication

### Installation and Setup

The project can be used in two ways:

1. **Home Assistant Integration**: Install via HACS by adding this repository
2. **Standalone Python Library**: Import `EufyClean` from the package

For either method, you'll need valid Eufy account credentials (username and password).

## Development Guidelines

### Environment Setup

1. Python 3.12 is required (see pyproject.toml)
2. Dependencies are managed with Poetry
3. For development/testing purposes, a Docker Compose file is provided to run Home Assistant locally

```bash
# Install dependencies with Poetry
poetry install

# Run the example script (requires environment variables)
export EUFY_USERNAME=your_username
export EUFY_PASSWORD=your_password
poetry run python example.py

# For Home Assistant development, use Docker:
docker-compose up -d
```

### Working with the Code

#### Authentication Flow

1. The `EufyLogin` class handles login through Eufy's cloud API
2. Once authenticated, the code can discover MQTT devices
3. For each device, an MQTT connection is established for control

#### MQTT Communication

- MQTT is used for real-time control and status updates
- The system uses TLS certificates for secure communication
- Messages are exchanged using protobuf definitions

#### Home Assistant Integration

- The integration follows Home Assistant's component architecture
- It creates vacuum entities with appropriate features and services
- Configuration is done through Home Assistant's config flow

### Common Functionalities

1. **Device Discovery**: `EufyClean.get_devices()`
2. **Device Control**:
   - `MqttConnect.go_home()` - Return to charging dock
   - `MqttConnect.play()` - Start cleaning
   - `MqttConnect.pause()` - Pause cleaning
   - `MqttConnect.scene_clean(scene_id)` - Run a predefined cleaning scene
   - `MqttConnect.room_clean(room_ids)` - Clean specific rooms

### Testing

When making changes:
1. Test functionality with the example.py script first
2. For Home Assistant integration changes, test using the Docker setup
3. Verify MQTT communication is working correctly

### Troubleshooting Tips

1. **MQTT Connection Issues**: Check certificates, network connectivity
2. **Authentication Failures**: Verify credentials, check for API changes
3. **Room/Scene IDs**: These are numerically identified; refer to README.md and example.py for guidance

## Special Considerations

### Room and Scene Mapping

- Room IDs are determined by the physical layout, typically numbered from left to right starting from the room with the base station
- Scene IDs start from predefined values:
  - Full home daily clean: 1
  - Full home deep clean: 2
  - Post-Meal Clean: 3
  - User-defined scenes start from 4

### Device Compatibility

This integration primarily supports MQTT-enabled Eufy vacuums, such as the Robovac X10 Pro Omni. While it may work with other models, compatibility is not guaranteed.

### Security Notes

- The code stores sensitive information (certificates, keys) temporarily for MQTT connections
- Credentials should be handled securely, preferably using environment variables or Home Assistant's secrets management

## External Resources

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/)
- [Eufy Cloud API Documentation](https://github.com/jeppesens/eufy-clean/issues) (unofficial, refer to issues)
- [MQTT Protocol Documentation](https://mqtt.org/mqtt-specification/)

## Contributing Guidelines

1. Follow Python best practices and PEP 8 style guide
2. Include proper documentation for new features
3. Write unit tests for new functionalities
4. Add documentation to the README.md for any new features or changes