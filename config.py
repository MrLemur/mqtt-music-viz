"""Configuration loader for mqtt-music-viz.

Loads settings from `config.yaml` (if present) and environment variables as
fallbacks. Provides simple dataclasses for typed access and validation.
"""
from dataclasses import dataclass
import os
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - handled at runtime
    yaml = None


def _load_yaml(path: str) -> dict[str, Any]:
    if not yaml:
        raise RuntimeError("PyYAML is required to load YAML config; install 'pyyaml'.")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class MQTTConfig:
    host: str = "10.0.100.153"
    port: int = 1883
    username: str | None = None
    password: str | None = None


@dataclass
class AudioConfig:
    buffer_size: int = 2048
    sample_rate: int = 44100
    channels: int = 1
    min_volume: float = 0.005
    beat_threshold: float = 0.01


@dataclass
class AppSettings:
    debug: bool = False
    min_publish_interval: float = 0.1
    flash_duration: float = 0.3


@dataclass
class DeviceConfig:
    id: str
    name: str
    topic: str
    type: str = "zigbee"
    enabled: bool = True
    mode: str = "reactive"
    flash_colour: str = "255,0,0"
    flash_random: bool = False
    freq_ranges: list[dict[str, int]] = None

    def __post_init__(self):
        if self.freq_ranges is None:
            self.freq_ranges = [{"min": 20, "max": 20000}]


@dataclass
class AppConfig:
    mqtt: MQTTConfig
    audio: AudioConfig
    app: AppSettings
    devices: list[DeviceConfig]


def load_config(path: str = "config.yaml") -> AppConfig:
    data = _load_yaml(path)

    mqtt_data = data.get("mqtt", {})
    audio_data = data.get("audio", {})
    app_data = data.get("app", {})
    devices_data = data.get("devices", [])

    # Environment fallbacks
    mqtt = MQTTConfig(
        host=os.getenv("MQTT_HOST", mqtt_data.get("host", MQTTConfig.host)),
        port=int(os.getenv("MQTT_PORT", mqtt_data.get("port", MQTTConfig.port))),
        username=os.getenv("MQTT_USERNAME", mqtt_data.get("username", MQTTConfig.username)),
        password=os.getenv("MQTT_PASSWORD", mqtt_data.get("password", MQTTConfig.password)),
    )

    audio = AudioConfig(
        buffer_size=int(os.getenv("AUDIO_BUFFER_SIZE", audio_data.get("buffer_size", AudioConfig.buffer_size))),
        sample_rate=int(os.getenv("AUDIO_SAMPLE_RATE", audio_data.get("sample_rate", AudioConfig.sample_rate))),
        channels=int(os.getenv("AUDIO_CHANNELS", audio_data.get("channels", AudioConfig.channels))),
        min_volume=float(os.getenv("AUDIO_MIN_VOLUME", audio_data.get("min_volume", AudioConfig.min_volume))),
        beat_threshold=float(os.getenv("AUDIO_BEAT_THRESHOLD", audio_data.get("beat_threshold", AudioConfig.beat_threshold))),
    )

    app = AppSettings(
        debug=app_data.get("debug", AppSettings.debug),
        min_publish_interval=float(app_data.get("min_publish_interval", AppSettings.min_publish_interval)),
        flash_duration=float(app_data.get("flash_duration", AppSettings.flash_duration)),
    )

    devices = [
        DeviceConfig(
            id=d["id"],
            name=d["name"],
            topic=d["topic"],
            type=d.get("type", "zigbee"),
            enabled=d.get("enabled", True),
            mode=d.get("mode", "reactive"),
            flash_colour=d.get("flash_colour", "255,0,0"),
            flash_random=d.get("flash_random", False),
            freq_ranges=d.get("freq_ranges", [{"min": 20, "max": 20000}])
        )
        for d in devices_data
    ]

    _validate(mqtt, audio)

    return AppConfig(mqtt=mqtt, audio=audio, app=app, devices=devices)


def save_config(config: AppConfig, path: str = "config.yaml") -> None:
    """Save configuration to YAML file.
    
    Args:
        config: AppConfig instance to save
        path: Path to YAML file (default: config.yaml)
    """
    if not yaml:
        raise RuntimeError("PyYAML is required to save YAML config; install 'pyyaml'.")
    
    data = {
        "mqtt": {
            "host": config.mqtt.host,
            "port": config.mqtt.port,
            "username": config.mqtt.username,
            "password": config.mqtt.password,
        },
        "audio": {
            "buffer_size": config.audio.buffer_size,
            "sample_rate": config.audio.sample_rate,
            "channels": config.audio.channels,
            "min_volume": config.audio.min_volume,
            "beat_threshold": config.audio.beat_threshold,
        },
        "app": {
            "debug": config.app.debug,
            "min_publish_interval": config.app.min_publish_interval,
            "flash_duration": config.app.flash_duration,
        },
        "devices": [
            {
                "id": d.id,
                "name": d.name,
                "topic": d.topic,
                "type": d.type,
                "enabled": d.enabled,
                "mode": d.mode,
                "flash_colour": d.flash_colour,
                "freq_ranges": d.freq_ranges,
            }
            for d in config.devices
        ]
    }
    
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _validate(mqtt: MQTTConfig, audio: AudioConfig) -> None:
    if not mqtt.host:
        raise ValueError("MQTT host must be set in config or MQTT_HOST environment variable")
    if mqtt.port <= 0 or mqtt.port > 65535:
        raise ValueError("MQTT port must be a valid TCP port number")
    if audio.buffer_size <= 0:
        raise ValueError("Audio buffer_size must be a positive integer")
    if audio.sample_rate <= 0:
        raise ValueError("Audio sample_rate must be a positive integer")


if __name__ == "__main__":
    # simple smoke test
    cfg = load_config()
    print(cfg)
