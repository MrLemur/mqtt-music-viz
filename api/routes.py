"""REST API endpoints for device and configuration management."""
import logging
from time import time
from flask import current_app, jsonify, request, render_template
from . import bp
from core.devices import FREQ_PRESETS
from core.state import get_state
from config import save_devices_config

logger = logging.getLogger(__name__)


def _normalize_brightness(value, default=155) -> int:
    try:
        brightness = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(255, brightness))


def _normalize_flash_cooldown(value, default=0.0) -> float:
    try:
        cooldown = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, cooldown)


@bp.route("/", methods=["GET"])
def index():
    """Serve main UI page."""
    return render_template("index.html")


@bp.route("/api/devices", methods=["GET"])
def get_devices():
    """Get all devices."""
    state = get_state()
    return jsonify(state.devices)


@bp.route("/api/devices", methods=["POST"])
def create_device():
    """Create a new device with validation."""
    try:
        data = request.get_json() or {}
        
        # Validation
        if not data.get('name') or not data.get('topic'):
            return jsonify({"error": "name and topic are required"}), 400
        
        device = {
            'id': data.get('id', f"device_{int(time())}"),
            'name': data['name'],
            'topic': data['topic'],
            'type': data.get('type', 'zigbee'),
            'enabled': data.get('enabled', True),
            'brightness': _normalize_brightness(data.get('brightness', 155)),
            'mode': data.get('mode', 'reactive'),
            'flash_colour': data.get('flash_colour', data.get('flash_color', '255,255,255')),
            'flash_random': data.get('flash_random', False),
            'flash_cooldown': _normalize_flash_cooldown(data.get('flash_cooldown', 0.0)),
            'freq_ranges': data.get('freq_ranges', [{'min': 20, 'max': 20000}]),
        }
        
        # Add to state manager
        state = get_state()
        state.devices.append(device)
        save_devices_config(state.devices)
        
        # Emit update to all connected clients
        if state._socketio:
            state._socketio.emit('devices_updated', state.devices)
        
        logger.info(f"Device created: {device['name']}")
        return jsonify(device), 201
    
    except Exception as e:
        logger.error(f"Error creating device: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/api/devices/<device_id>", methods=["PUT"])
def update_device(device_id):
    """Update an existing device with validation."""
    try:
        data = request.get_json() or {}
        state = get_state()
        device = next((d for d in state.devices if d['id'] == device_id), None)
        
        if not device:
            return jsonify({"error": "device not found"}), 404
        
        # Update with validation
        if 'name' in data and not data['name']:
            return jsonify({"error": "name cannot be empty"}), 400
        if 'topic' in data and not data['topic']:
            return jsonify({"error": "topic cannot be empty"}), 400
        
        device.update({
            'name': data.get('name', device['name']),
            'topic': data.get('topic', device['topic']),
            'type': data.get('type', device['type']),
            'enabled': data.get('enabled', device['enabled']),
            'brightness': _normalize_brightness(data.get('brightness', device.get('brightness', 155))),
            'mode': data.get('mode', device.get('mode', 'reactive')),
            'flash_colour': data.get('flash_colour', data.get('flash_color', device.get('flash_colour', '255,255,255'))),
            'flash_random': data.get('flash_random', device.get('flash_random', False)),
            'flash_cooldown': _normalize_flash_cooldown(data.get('flash_cooldown', device.get('flash_cooldown', 0.0))),
            'freq_ranges': data.get('freq_ranges', device['freq_ranges']),
        })
        
        # Emit update to all connected clients
        if state._socketio:
            state._socketio.emit('devices_updated', state.devices)

        save_devices_config(state.devices)
        
        logger.info(f"Device updated: {device['name']} (mode: {device['mode']}, flash_colour: {device.get('flash_colour')})")
        return jsonify(device)
    
    except Exception as e:
        logger.error(f"Error updating device: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/api/devices/<device_id>", methods=["DELETE"])
def delete_device(device_id):
    """Delete a device."""
    try:
        state = get_state()
        initial_count = len(state.devices)
        state.devices[:] = [d for d in state.devices if d['id'] != device_id]
        
        if len(state.devices) == initial_count:
            return jsonify({"error": "device not found"}), 404
        
        # Emit update to all connected clients
        if state._socketio:
            state._socketio.emit('devices_updated', state.devices)

        save_devices_config(state.devices)
        
        logger.info(f"Device deleted: {device_id}")
        return jsonify({"status": "deleted"})
    
    except Exception as e:
        logger.error(f"Error deleting device: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/api/config", methods=["GET"])
def get_config():
    """Get current configuration."""
    state = get_state()
    cfg = current_app.config.get("APP_CONFIG")
    if cfg:
        return jsonify({
            "mqtt": {"host": cfg.mqtt.host, "port": cfg.mqtt.port},
            "audio": {
                "buffer_size": cfg.audio.buffer_size,
                "sample_rate": cfg.audio.sample_rate,
                "channels": cfg.audio.channels,
                "min_volume": cfg.audio.min_volume,
                "beat_threshold": cfg.audio.beat_threshold,
            },
            "runtime": state.config
        })
    return jsonify({"runtime": state.config})


@bp.route("/api/config", methods=["POST"])
def update_config():
    """Update runtime configuration."""
    try:
        state = get_state()
        data = request.get_json() or {}
        
        for key in ['min_publish_interval', 'beat_threshold', 'min_volume', 'flash_duration']:
            if key in data:
                try:
                    state.config[key] = float(data[key])
                except ValueError:
                    return jsonify({"error": f"invalid value for {key}"}), 400
        
        if 'debug' in data:
            state.config['debug'] = bool(data['debug'])
        if 'flash_guard_enabled' in data:
            state.config['flash_guard_enabled'] = bool(data['flash_guard_enabled'])
        
        logger.info(f"Configuration updated: {data}")
        return jsonify({"status": "ok", "config": state.config})
    
    except Exception as e:
        logger.error(f"Error updating config: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/api/config/save", methods=["POST"])
def save_config_to_file():
    """Save current configuration to config.yaml file."""
    try:
        from config import save_config
        
        state = get_state()
        config_obj = state.get_config_for_save()
        
        # Get optional path from request, default to config.yaml
        data = request.get_json(silent=True) or {}
        path = data.get('path', 'config.yaml')
        
        save_config(config_obj, path)
        
        logger.info(f"Configuration saved to {path}")
        return jsonify({
            "status": "saved",
            "path": path,
            "devices_count": len(state.devices)
        })
    
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500
        return jsonify({"status": "error", "error": str(e)}), 500


@bp.route("/api/config/mqtt", methods=["POST"])
def update_mqtt_config():
    """Update MQTT configuration and reconnect."""
    try:
        from config import save_config, MQTTConfig
        
        data = request.get_json() or {}
        state = get_state()
        
        # Validate inputs
        host = data.get('host')
        port = data.get('port')
        
        if not host:
            return jsonify({"error": "host is required"}), 400
        
        try:
            port = int(port)
            if port <= 0 or port > 65535:
                raise ValueError()
        except (ValueError, TypeError):
            return jsonify({"error": "port must be a valid TCP port number"}), 400
        
        # Build new config
        config_obj = state.get_config_for_save()
        config_obj.mqtt = MQTTConfig(
            host=host,
            port=port,
            username=data.get('username') or None,
            password=data.get('password') or None,
        )
        
        # Save to file
        save_config(config_obj, 'config.yaml')
        
        logger.info(f"MQTT config updated to {host}:{port}, restart required")
        return jsonify({
            "status": "updated",
            "message": "MQTT configuration saved. Please restart the application for changes to take effect.",
            "requires_restart": True
        })
    
    except Exception as e:
        logger.error(f"Failed to update MQTT config: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@bp.route("/api/config/audio", methods=["POST"])
def update_audio_config():
    """Update audio configuration and restart audio processor."""
    try:
        from config import save_config, AudioConfig
        
        data = request.get_json() or {}
        state = get_state()
        
        # Validate inputs
        buffer_size = int(data.get('buffer_size', 2048))
        sample_rate = int(data.get('sample_rate', 44100))
        channels = int(data.get('channels', 1))
        
        if buffer_size <= 0:
            return jsonify({"error": "buffer_size must be positive"}), 400
        if sample_rate <= 0:
            return jsonify({"error": "sample_rate must be positive"}), 400
        if channels not in [1, 2]:
            return jsonify({"error": "channels must be 1 or 2"}), 400
        
        # Build new config
        config_obj = state.get_config_for_save()
        config_obj.audio = AudioConfig(
            buffer_size=buffer_size,
            sample_rate=sample_rate,
            channels=channels,
            min_volume=config_obj.audio.min_volume,
            beat_threshold=config_obj.audio.beat_threshold,
        )
        
        # Save to file
        save_config(config_obj, 'config.yaml')
        
        logger.info(f"Audio config updated to {sample_rate}Hz/{buffer_size}, restart required")
        return jsonify({
            "status": "updated",
            "message": "Audio configuration saved. Please restart the application for changes to take effect.",
            "requires_restart": True
        })
    
    except Exception as e:
        logger.error(f"Failed to update audio config: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@bp.route("/api/stats", methods=["GET"])
def get_stats():
    """Get system statistics."""
    state = get_state()
    return jsonify({
        **state.stats,
        'config': state.config
    })


@bp.route("/api/presets", methods=["GET"])
def get_presets():
    """Get frequency range presets."""
    return jsonify(FREQ_PRESETS)


@bp.route("/api/start", methods=["POST"])
def start_system():
    """Start the visualiser system."""
    try:
        state = get_state()
        if state.start():
            logger.info("System started successfully")
            return jsonify({"status": "started", "running": True})
        else:
            return jsonify({"status": "already_running", "running": True})
    except Exception as e:
        logger.error(f"Failed to start system: {e}")
        return jsonify({"status": "error", "error": str(e), "running": False}), 500


@bp.route("/api/stop", methods=["POST"])
def stop_system():
    """Stop the visualiser system."""
    try:
        state = get_state()
        if state.stop():
            logger.info("System stopped successfully")
            return jsonify({"status": "stopped", "running": False})
        else:
            return jsonify({"status": "not_running", "running": False})
    except Exception as e:
        logger.error(f"Failed to stop system: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500
