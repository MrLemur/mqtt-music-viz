"""WebSocket event handlers for real-time updates."""
import logging
from time import time
from flask_socketio import SocketIO, emit

logger = logging.getLogger(__name__)
socketio = SocketIO(cors_allowed_origins="*")


@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    logger.info("Client connected")
    emit('log', {'level': 'info', 'message': 'Connected to server', 'timestamp': time()})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    logger.info("Client disconnected")


@socketio.on('ping')
def handle_ping():
    """Handle ping from client."""
    emit('pong', {'timestamp': time()})


def emit_log(level: str, message: str, data: dict | None = None):
    """Emit log message to all connected clients."""
    payload = {
        'level': level,
        'message': message,
        'data': data,
        'timestamp': time()
    }
    socketio.emit('log', payload)
    
    # Also log to Python logger
    log_func = getattr(logger, level, logger.info)
    log_func(message)


def emit_device_state(device_id: str, device_name: str, state: str, **kwargs):
    """Emit device state change to all connected clients."""
    payload = {
        'device_id': device_id,
        'device_name': device_name,
        'state': state,
        'timestamp': time(),
        **kwargs
    }
    socketio.emit('device_state', payload)


def emit_devices_updated(devices: list):
    """Emit updated device list to all connected clients."""
    socketio.emit('devices_updated', devices)


def emit_stats(stats: dict):
    """Emit statistics update to all connected clients."""
    socketio.emit('stats', stats)
