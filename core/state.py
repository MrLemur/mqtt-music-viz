"""Global application state manager."""
import logging
from threading import Lock
from time import time
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from flask import current_app

from core.audio import AudioProcessor
from core.mqtt import MQTTManager
from core.colours import COLOUR_PALETTE, random_colour
from core.devices import get_device_config

logger = logging.getLogger(__name__)


class AppState:
    """Manages global application state including audio, MQTT, and devices."""
    
    def __init__(self):
        self.audio_processor: Optional[AudioProcessor] = None
        self.mqtt_manager: Optional[MQTTManager] = None
        self.devices = []
        self.config = {
            'debug': False,
            'min_publish_interval': 0.1,
            'beat_threshold': 0.01,
            'min_volume': 0.005,
            'flash_duration': 0.3,
        }
        self.stats = {
            'beats_detected': 0,
            'messages_sent': 0,
            'last_beat_time': 0,
            'running': False,
            'current_frequency': 0,
        }
        self._lock = Lock()
        self._last_publish_time = {}  # device_id -> timestamp
        self._last_colours = {}  # device_id -> colour
        self._flash_states = {}  # device_id -> {'flash_time': timestamp, 'is_on': bool}
        self._socketio = None
        self._executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="device_worker")
    
    def set_socketio(self, socketio):
        """Set the SocketIO instance for real-time updates."""
        self._socketio = socketio
    
    def initialize(self, app_config, mqtt_manager):
        """Initialize with Flask app config and MQTT manager."""
        with self._lock:
            # Store original config for rebuilding
            self._app_config_template = app_config
            
            # Load devices from config
            self.devices = [
                {
                    'id': d.id,
                    'name': d.name,
                    'topic': d.topic,
                    'type': d.type,
                    'enabled': d.enabled,
                    'mode': d.mode,
                    'flash_colour': d.flash_colour,
                    'flash_random': d.flash_random,
                    'freq_ranges': d.freq_ranges,
                }
                for d in app_config.devices
            ]
            
            # Load app settings
            self.config.update({
                'debug': app_config.app.debug,
                'min_publish_interval': app_config.app.min_publish_interval,
                'flash_duration': app_config.app.flash_duration,
                'beat_threshold': app_config.audio.beat_threshold,
                'min_volume': app_config.audio.min_volume,
            })
            
            # Create audio processor
            self.audio_processor = AudioProcessor(
                buffer_size=app_config.audio.buffer_size,
                sample_rate=app_config.audio.sample_rate,
                channels=app_config.audio.channels,
                min_volume=app_config.audio.min_volume,
                beat_threshold=app_config.audio.beat_threshold,
            )
            
            # Store MQTT manager
            self.mqtt_manager = mqtt_manager
            
            logger.info(f"AppState initialized with {len(self.devices)} devices")
    
    def get_config_for_save(self):
        """Build an AppConfig object from current state for saving to YAML."""
        from config import AppConfig, MQTTConfig, AudioConfig, AppSettings, DeviceConfig
        
        if not hasattr(self, '_app_config_template'):
            raise RuntimeError("AppState not initialized")
        
        # Use original MQTT/Audio settings (these don't change at runtime)
        mqtt_config = self._app_config_template.mqtt
        
        # Audio config from audio processor if available
        if self.audio_processor:
            audio_config = AudioConfig(
                buffer_size=self.audio_processor.buffer_size,
                sample_rate=self.audio_processor.sample_rate,
                channels=self.audio_processor.channels,
                min_volume=self.config.get('min_volume', 0.005),
                beat_threshold=self.config.get('beat_threshold', 0.01),
            )
        else:
            audio_config = self._app_config_template.audio
        
        # App settings from current config
        app_settings = AppSettings(
            debug=self.config.get('debug', False),
            min_publish_interval=self.config.get('min_publish_interval', 0.1),
            flash_duration=self.config.get('flash_duration', 0.3),
        )
        
        # Devices from current state
        devices = [
            DeviceConfig(
                id=d['id'],
                name=d['name'],
                topic=d['topic'],
                type=d.get('type', 'zigbee'),
                enabled=d.get('enabled', True),
                mode=d.get('mode', 'reactive'),
                flash_colour=d.get('flash_colour', '255,0,0'),
                flash_random=d.get('flash_random', False),
                freq_ranges=d.get('freq_ranges', [{'min': 20, 'max': 20000}])
            )
            for d in self.devices
        ]
        
        return AppConfig(mqtt=mqtt_config, audio=audio_config, app=app_settings, devices=devices)
    
    def start(self):
        """Start audio processing."""
        if not self.audio_processor:
            raise RuntimeError("AppState not initialized")
        
        if self.audio_processor.is_running:
            logger.warning("Audio processor already running")
            return False
        
        def on_beat(is_beat, frequency, volume):
            self._handle_beat(frequency, volume)
        
        self.audio_processor.start(on_beat)
        self.stats['running'] = True
        self._emit_log('info', 'Audio processing started')
        logger.info("System started")
        
        # Save running state to file
        self._save_running_state(True)
        return True
    
    def stop(self):
        """Stop audio processing and reset devices to white."""
        if not self.audio_processor:
            return False
        
        if not self.audio_processor.is_running:
            return False
        
        self.audio_processor.stop()
        self.stats['running'] = False
        
        # Set all enabled devices to white
        with self._lock:
            for device in self.devices:
                if device['enabled'] and self.mqtt_manager:
                    payload = get_device_config(device['type'], 'white')
                    self.mqtt_manager.publish_device_state(device['topic'], payload)
        
        self._emit_log('info', 'System stopped, lights set to white')
        logger.info("System stopped")
        
        # Save running state to file
        self._save_running_state(False)
        return True
    
    def _save_running_state(self, running: bool):
        """Save running state to temporary file."""
        try:
            import json
            with open('.running_state', 'w') as f:
                json.dump({'running': running}, f)
        except Exception as e:
            logger.warning(f"Failed to save running state: {e}")
    
    def _load_running_state(self) -> bool:
        """Load running state from temporary file."""
        try:
            import json
            import os
            if os.path.exists('.running_state'):
                with open('.running_state', 'r') as f:
                    data = json.load(f)
                    return data.get('running', False)
        except Exception as e:
            logger.warning(f"Failed to load running state: {e}")
        return False
    
    def auto_restart_if_was_running(self):
        """Automatically start if the system was running before restart."""
        if self._load_running_state():
            logger.info("System was running before restart - auto-starting...")
            self.start()
    
    def _handle_beat(self, frequency: float, volume: float):
        """Handle beat detection event."""
        current_time = time()
        self.stats['beats_detected'] += 1
        self.stats['last_beat_time'] = current_time
        self.stats['current_frequency'] = float(frequency)
        
        self._emit_log('debug', f'Beat detected at {frequency:.0f}Hz')
        
        # Check flash timeouts
        self._check_flash_timeouts(current_time)
        
        # Get active devices (snapshot to avoid holding lock)
        with self._lock:
            active_devices = [d.copy() for d in self.devices if d['enabled']]
        
        # Process all devices in parallel
        if active_devices:
            futures = []
            for device in active_devices:
                future = self._executor.submit(
                    self._process_device_beat,
                    device, frequency, volume, current_time
                )
                futures.append(future)
            
            # Wait for all device processing to complete (non-blocking for audio thread)
            # Note: We don't wait here to keep audio callback fast
            # Devices will update asynchronously
    
    def _check_flash_timeouts(self, current_time: float):
        """Turn off lights that have been flashing for too long."""
        for device_id, state in list(self._flash_states.items()):
            if state['is_on'] and (current_time - state['flash_time']) > self.config['flash_duration']:
                with self._lock:
                    device = next((d for d in self.devices if d['id'] == device_id), None)
                    if device and self.mqtt_manager:
                        payload = get_device_config(device['type'], '', turn_off=True)
                        self.mqtt_manager.publish_device_state(device['topic'], payload)
                        self._flash_states[device_id]['is_on'] = False
                        
                        if self._socketio:
                            self._socketio.emit('device_state', {
                                'device_id': device_id,
                                'state': 'off'
                            })
    
    def _process_device_beat(self, device, frequency: float, volume: float, current_time: float):
        """Process beat for a single device."""
        device_id = device['id']
        
        # Check if frequency is in device's ranges
        if not self._frequency_in_ranges(frequency, device['freq_ranges']):
            return
        
        # Rate limiting
        if device_id not in self._last_publish_time:
            self._last_publish_time[device_id] = 0
        
        if current_time - self._last_publish_time[device_id] < self.config['min_publish_interval']:
            return
        
        # Handle device mode
        if device['mode'] == 'flash':
            self._handle_flash_mode(device, frequency, volume, current_time)
        else:
            self._handle_reactive_mode(device, frequency, volume, current_time)
        
        self.stats['messages_sent'] += 1
        self._last_publish_time[device_id] = current_time
    
    def _handle_flash_mode(self, device, frequency: float, volume: float, current_time: float):
        """Handle flash mode device."""
        device_id = device['id']
        
        # Use random colour if enabled, otherwise use flash_colour
        if device.get('flash_random', False):
            colour_obj = random_colour(exclude_value=self._last_colours.get(device_id))
            colour = colour_obj['rgb']
            colour_name = colour_obj['name']
            self._last_colours[device_id] = colour
        else:
            colour = device.get('flash_colour', '255,255,255')
            colour_name = 'FLASH'
        
        if self.mqtt_manager:
            payload = get_device_config(device['type'], colour)
            self.mqtt_manager.publish_device_state(device['topic'], payload)
        
        self._flash_states[device_id] = {
            'flash_time': current_time,
            'is_on': True
        }
        
        self._emit_log('info', f'{device["name"]}: {colour_name} (freq: {frequency:.0f}Hz)')
        
        if self._socketio:
            self._socketio.emit('device_state', {
                'device_id': device_id,
                'device_name': device['name'],
                'state': 'flash',
                'colour': colour,
                'hex': self._rgb_to_hex(colour),
                'pitch': float(frequency),
                'volume': float(volume)
            })
    
    def _handle_reactive_mode(self, device, frequency: float, volume: float, current_time: float):
        """Handle reactive mode device."""
        device_id = device['id']
        
        # Get random colour, avoiding last colour
        colour = random_colour(exclude_value=self._last_colours.get(device_id))
        
        self._emit_log('info', f'{device["name"]}: {colour["name"]} (freq: {frequency:.0f}Hz)')
        
        if self.mqtt_manager:
            payload = get_device_config(device['type'], colour['rgb'])
            self.mqtt_manager.publish_device_state(device['topic'], payload)
        
        if self._socketio:
            self._socketio.emit('device_state', {
                'device_id': device_id,
                'device_name': device['name'],
                'state': 'on',
                'colour': colour['rgb'],
                'hex': colour['hex'],
                'name': colour['name'],
                'pitch': float(frequency),
                'volume': float(volume)
            })
        
        self._last_colours[device_id] = colour['rgb']
    
    def _frequency_in_ranges(self, freq: float, ranges) -> bool:
        """Check if frequency is within any range."""
        for r in ranges:
            if r['min'] <= freq <= r['max']:
                return True
        return False
    
    def _rgb_to_hex(self, rgb_str: str) -> str:
        """Convert 'R,G,B' to '#RRGGBB'."""
        parts = [int(p.strip()) for p in rgb_str.split(',')]
        return f"#{parts[0]:02x}{parts[1]:02x}{parts[2]:02x}"
    
    def _emit_log(self, level: str, message: str, data=None):
        """Emit log to WebSocket and console."""
        if level == 'debug' and not self.config['debug']:
            return
        
        log_func = getattr(logger, level, logger.info)
        log_func(message)
        
        if self._socketio:
            self._socketio.emit('log', {
                'level': level,
                'message': message,
                'data': data,
                'timestamp': time()
            })


# Global state instance
_state = AppState()


def get_state() -> AppState:
    """Get the global application state."""
    return _state
