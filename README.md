# mqtt-music-viz

A Python application that synchronises MQTT-controlled devices (Zigbee2MQTT, WLED, Tasmota) with music in real-time using audio beat detection and frequency analysis.

## Features

- **Real-time beat detection** using Aubio (with fallback when unavailable)
- **Frequency-based device triggering** - assign devices to specific frequency ranges
- **Multiple modes**: Reactive (colour changes) and Flash (strobe effect)
- **Web interface** for device management and visualisation
- **WebSocket updates** for real-time device state display
- **MQTT auto-reconnection** with exponential backoff
- **Modular architecture** with separate audio, MQTT, and device management

## Requirements

- Python 3.8+
- MQTT broker (e.g., Mosquitto)
- Audio input device (microphone or system audio)
- Compatible smart lights (Zigbee via Zigbee2MQTT, Tasmota, WLED)

## Installation

### Using uv (recommended)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/MrLemur/mqtt-music-viz.git
cd mqtt-music-viz

# Install dependencies
uv sync
```

### Using pip

```bash
# Clone the repository
git clone https://github.com/MrLemur/mqtt-music-viz.git
cd mqtt-music-viz

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

### Option 1: YAML Configuration (recommended)

Create a `config.yaml` file:

```yaml
mqtt:
  host: "10.0.100.153"
  port: 1883
  username: "your_mqtt_user" # optional
  password: "your_mqtt_pass" # optional

audio:
  buffer_size: 2048
  sample_rate: 44100
  channels: 1
  min_volume: 0.005
  beat_threshold: 0.01
```

### Option 2: Environment Variables

Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
# Edit .env with your settings
```

Environment variables override YAML configuration.

## Running

### Using uv

```bash
uv run python app.py
```

### Using Python directly

```bash
python app.py
```

The web interface will be available at `http://localhost:8888`

## Usage

### Web Interface

1. Open `http://localhost:8888` in your browser
2. Click "Add Device" to configure MQTT devices
3. Set device properties:
   - **Name**: Display name for the device
   - **Topic**: MQTT topic (e.g., `zigbee2mqtt/Living Room Light/set`)
   - **Type**: Device protocol (`zigbee` or `tasmota`)
   - **Mode**: `reactive` (colour changes) or `flash` (strobe)
   - **Frequency Ranges**: Which frequencies trigger this device
4. Click "Start" to begin visualisation

### Frequency Range Presets

- **Sub Bass**: 20-60 Hz
- **Bass**: 60-250 Hz
- **Low Midrange**: 250-500 Hz
- **Midrange**: 500-2000 Hz
- **High Midrange**: 2000-4000 Hz
- **Presence**: 4000-6000 Hz
- **Brilliance**: 6000-20000 Hz
- **Full Spectrum**: 20-20000 Hz

### Tips

- Use **Bass** ranges for kick drums and low frequencies
- Use **Midrange** for vocals and melody
- Use **Brilliance** for cymbals and high-frequency instruments
- **Flash mode** works well for strobe effects on beat detection
- **Reactive mode** provides smooth colour transitions

## Zigbee2MQTT Configuration

Ensure your Zigbee2MQTT setup is configured correctly:

1. Devices must be paired with Zigbee2MQTT
2. MQTT broker must be accessible on your network
3. Device topics follow the pattern: `zigbee2mqtt/<device_name>/set`

Example Zigbee2MQTT device topic:

```
zigbee2mqtt/TV Light 1/set
```

## Troubleshooting

### Audio Issues

- **No beat detection**: Install Aubio for better detection: `pip install aubio`
- **No audio input**: Check your system audio settings and permissions
- **Low sensitivity**: Adjust `min_volume` and `beat_threshold` in configuration

### MQTT Issues

- **Connection fails**: Verify MQTT broker is running and accessible
- **Devices not responding**: Check device topics match Zigbee2MQTT configuration
- **Reconnection loops**: Ensure correct MQTT credentials

### Performance

- **High CPU usage**: Increase `buffer_size` or reduce number of active devices
- **Delayed response**: Decrease `min_publish_interval` in runtime config
- **Too sensitive**: Increase `beat_threshold` value

## Development

### Project Structure

```
mqtt-music-viz/
├── app.py                  # Application entry point
├── config.py               # Configuration loader
├── core/                   # Core modules
│   ├── audio.py           # Audio processing and beat detection
│   ├── mqtt.py            # MQTT connection management
│   ├── devices.py         # Device models and management
│   └── colours.py         # Colour palette utilities
├── api/                    # REST API and WebSocket
│   ├── routes.py          # REST endpoints
│   └── websocket.py       # WebSocket handlers
├── static/                 # Frontend assets
│   ├── css/
│   └── js/
└── templates/              # HTML templates
    └── index.html
```

### Running Tests

```bash
# Run tests (when available)
uv run pytest

# Type checking
uv run mypy .

# Code formatting
uv run black .
```

## License

MIT License - see LICENSE file for details

## Contributing

Pull requests welcome! Please ensure:

- Code follows existing style (British English, type hints)
- Add tests for new features
- Update documentation as needed

## Credits

- Uses [Aubio](https://aubio.org/) for beat detection
- Built with Flask and Flask-SocketIO
- MQTT via [paho-mqtt](https://github.com/eclipse/paho.mqtt.python)
