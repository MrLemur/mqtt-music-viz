"""Device and DeviceManager definitions."""
from dataclasses import dataclass, field
from threading import Lock
from typing import List, Dict
import json


@dataclass
class FreqRange:
    """Represents a frequency range in Hz for device reactivity.
    
    Attributes:
        min: Minimum frequency in Hz
        max: Maximum frequency in Hz
    """
    min: float
    max: float


@dataclass
class Device:
    """Represents a controllable MQTT device for music visualisation.
    
    Attributes:
        id: Unique device identifier
        name: Human-readable device name
        topic: MQTT topic for publishing commands
        device_type: Device protocol type ('zigbee', 'tasmota', etc.)
        enabled: Whether device is active
        mode: Operating mode ('reactive' or 'flash')
        flash_colour: RGB colour for flash mode (e.g., '255,0,0')
        flash_random: Use random colour instead of flash_colour
        freq_ranges: List of frequency ranges device reacts to
    """
    id: str
    name: str
    topic: str
    device_type: str
    enabled: bool = True
    mode: str = "reactive"
    flash_colour: str | None = None
    flash_random: bool = False
    freq_ranges: List[FreqRange] = field(default_factory=list)

    def should_react_to_frequency(self, freq: float) -> bool:
        """Check if device should react to given frequency.
        
        Args:
            freq: Frequency in Hz to check
        
        Returns:
            True if frequency falls within any configured range
        """
        for r in self.freq_ranges:
            if r.min <= freq <= r.max:
                return True
        return False


class DeviceManager:
    """Thread-safe manager for device collection.
    
    Provides CRUD operations for devices with automatic locking
    to ensure thread safety during concurrent access.
    """
    
    def __init__(self) -> None:
        """Initialize device manager with empty collection."""
        self._devices: List[Device] = []
        self._lock = Lock()

    def add_device(self, device: Device) -> None:
        with self._lock:
            self._devices.append(device)

    def update_device(self, device_id: str, **kwargs) -> None:
        with self._lock:
            for i, d in enumerate(self._devices):
                if d.id == device_id:
                    for k, v in kwargs.items():
                        setattr(d, k, v)
                    self._devices[i] = d
                    return

    def get_active_devices(self) -> List[Device]:
        return [d for d in self._devices if d.enabled]
    
    def get_all(self) -> List[Device]:
        """Get all devices."""
        with self._lock:
            return self._devices.copy()
    
    def get_by_id(self, device_id: str) -> Device | None:
        """Get device by ID."""
        with self._lock:
            return next((d for d in self._devices if d.id == device_id), None)
    
    def delete(self, device_id: str) -> bool:
        """Remove device by ID."""
        with self._lock:
            self._devices = [d for d in self._devices if d.id != device_id]
            return True


def frequency_in_ranges(freq: float, ranges: List[Dict[str, float]]) -> bool:
    """Check if frequency falls within any of the device's ranges."""
    for r in ranges:
        if r['min'] <= freq <= r['max']:
            return True
    return False


def get_device_config(device_type: str, colour: str, brightness: int = 255, turn_off: bool = False) -> str:
    """Generate MQTT payload for device based on type and colour."""
    brightness_value = 255
    try:
        brightness_value = int(brightness)
    except (TypeError, ValueError):
        brightness_value = 255
    brightness_value = max(1, min(255, brightness_value))

    if device_type == "tasmota":
        tasmota_dimmer = max(1, min(100, round(brightness_value / 255 * 100)))
        if turn_off:
            return "NoDelay;Power1 OFF"
        elif colour == "white":
            return (
                "NoDelay;Fade 0;NoDelay;Speed 1;NoDelay;Power1 ON;"
                f"NoDelay;Dimmer {tasmota_dimmer};NoDelay;CT 500"
            )
        else:
            return (
                "NoDelay;Fade 0;NoDelay;Speed 1;"
                f"NoDelay;Dimmer {tasmota_dimmer};NoDelay;Color2 {colour}"
            )
    
    elif device_type == "zigbee":
        if turn_off:
            return json.dumps({"state": "OFF", "transition": 0.0001})
        elif colour == "white":
            return json.dumps({
                "state": "ON",
                "brightness": brightness_value,
                "transition": 0.0001,
                "color_temp": "500"
            })
        else:
            return json.dumps({
                "state": "ON",
                "brightness": brightness_value,
                "transition": 0.0001,
                "color": {"rgb": colour},
            })
    
    return json.dumps({"state": "OFF", "transition": 0.0001})  # fallback


# Frequency range presets
FREQ_PRESETS = {
    'sub_bass': {'min': 20, 'max': 60, 'name': 'Sub Bass'},
    'bass': {'min': 60, 'max': 250, 'name': 'Bass'},
    'low_mid': {'min': 250, 'max': 500, 'name': 'Low Midrange'},
    'mid': {'min': 500, 'max': 2000, 'name': 'Midrange'},
    'high_mid': {'min': 2000, 'max': 4000, 'name': 'High Midrange'},
    'presence': {'min': 4000, 'max': 6000, 'name': 'Presence'},
    'brilliance': {'min': 6000, 'max': 20000, 'name': 'Brilliance'},
    'full': {'min': 20, 'max': 20000, 'name': 'Full Spectrum'},
}
