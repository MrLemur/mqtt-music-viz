from time import sleep, time
import json
import logging
import paho.mqtt.client as mqtt
import sounddevice as sd
import sys
import numpy as np
try:
    import aubio
    _HAS_AUBIO = True
except Exception:
    aubio = None
    _HAS_AUBIO = False
from random import randint
from flask import Flask, redirect, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
from threading import Thread, Lock

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'music-viz-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration
config = {
    'debug': False,
    'min_publish_interval': 0.1,
    'beat_threshold': 0.01,
    'min_volume': 0.005,
    'flash_duration': 0.3,  # How long flash stays on
}

devices_lock = Lock()
devices = [
    {
        "id": "tv_light_1",
        "name": "TV Light 1",
        "topic": "zigbee2mqtt/TV Light 1/set",
        "type": "zigbee",
        "enabled": True,
        "mode": "reactive",  # 'reactive' or 'flash'
        "flash_color": "255,0,0",  # Color for flash mode
        "freq_ranges": [{"min": 20, "max": 20000}],  # Multiple ranges
    },
    {
        "id": "tv_light_2",
        "name": "TV Light 2",
        "topic": "zigbee2mqtt/TV Light 2/set",
        "type": "zigbee",
        "enabled": True,
        "mode": "reactive",  # 'reactive' or 'flash'
        "flash_color": "255,0,0",  # Color for flash mode
        "freq_ranges": [{"min": 20, "max": 20000}],  # Multiple ranges
    }
]

def log_and_emit(level, message, data=None):
    """Log to console and emit to websocket clients"""
    if level == 'debug' and not config['debug']:
        return
    
    log_func = getattr(logger, level, logger.info)
    log_func(message)
    
    socketio.emit('log', {
        'level': level,
        'message': message,
        'data': data,
        'timestamp': time()
    })

def convert_to_hex(value):
    array = value.split(",")
    return f"#{int(array[0]):02x}{int(array[1]):02x}{int(array[2]):02x}"

# Set up MQTT client with proper configuration
client = mqtt.Client(client_id="music_viz", clean_session=True)
auth = {"username": "mqtt-viz", "password": "4f76g3f"}
if auth:
    client.username_pw_set(auth["username"], auth["password"])

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log_and_emit('info', 'Connected to MQTT broker')
    else:
        log_and_emit('error', f'MQTT connection failed with code {rc}')

def on_publish(client, userdata, mid):
    log_and_emit('debug', f'Message {mid} published')

client.on_connect = on_connect
client.on_publish = on_publish
client.connect("10.0.100.153", 1883)
client.loop_start()

colour_values = [
    {"colour": "dark red", "value": "174,0,0"},
    {"colour": "red", "value": "255,0,0"},
    {"colour": "orange-red", "value": "255,102,0"},
    {"colour": "yellow", "value": "255,239,0"},
    {"colour": "chartreuse", "value": "153,255,0"},
    {"colour": "lime", "value": "40,255,0"},
    {"colour": "aqua", "value": "0,255,242"},
    {"colour": "sky blue", "value": "0,122,255"},
    {"colour": "blue", "value": "5,0,255"},
    {"colour": "blue", "value": "71,0,237"},
    {"colour": "indigo", "value": "99,0,178"},
]

stats = {
    'beats_detected': 0,
    'messages_sent': 0,
    'last_beat_time': 0,
    'running': False,
    'current_frequency': 0,
}

# Track flash states
flash_states = {}  # device_id: {'flash_time': timestamp, 'is_on': bool}

def get_device_config(device_type, colour, turn_off=False):
    if device_type == "tasmota":
        if turn_off:
            return "NoDelay;Power1 OFF"
        elif colour == "white":
            return (
                f"NoDelay;Fade 0;NoDelay;Speed 1;NoDelay;Power1 ON;NoDelay;CT 500"
            )
        else:
            return (
                f"NoDelay;Fade 0;NoDelay;Speed 1;NoDelay;Dimmer 100;NoDelay;Color2 {colour}"
            )
    if device_type == "zigbee":
        if turn_off:
            return json.dumps({"state": "OFF"})
        elif colour == "white":
             return json.dumps(
            {
                "state": "ON",
                "brightness": 255,
                "transition": 0.000000001,
                "color_temp": "500"
            }
        )
        else:
             return json.dumps(
            {
                "state": "ON",
                "brightness": 255,
                "transition": 0.000000001,
                "color": {"rgb": colour},
            }
        )

def change_colour(value):
    number = randint(0, len(colour_values) - 1)
    return colour_values[number]

def frequency_in_ranges(freq, ranges):
    """Check if frequency is within any of the device's ranges"""
    for r in ranges:
        if r['min'] <= freq <= r['max']:
            return True
    return False

BUFFER_SIZE = 2048  # Increased for better frequency resolution
CHANNELS = 1
METHOD = "default"
SAMPLE_RATE = 44100
HOP_SIZE = BUFFER_SIZE // 2
PERIOD_SIZE_IN_FRAME = HOP_SIZE

go = False
last_publish_time = {}  # Per-device timing

def run():
    global go, last_publish_time, stats, flash_states

    log_and_emit('info', f'Starting audio processing (aubio: {_HAS_AUBIO})')
    stats['running'] = True

    if _HAS_AUBIO:
        tempo_detect = aubio.tempo(METHOD, BUFFER_SIZE, HOP_SIZE, SAMPLE_RATE)
        pitch_detect = aubio.pitch(METHOD, BUFFER_SIZE, HOP_SIZE, SAMPLE_RATE)
        pitch_detect.set_unit("Hz")
        pitch_detect.set_silence(-40)
    else:
        tempo_detect = None
        pitch_detect = None

    last_colours = {}  # Per-device last colour

    def audio_callback(indata, frames, time_info, status):
        nonlocal last_colours
        global last_publish_time, stats, flash_states
        
        if status:
            log_and_emit('warning', f'Audio callback status: {status}')
        
        current_time = time()
        
        # Check for flash timeouts (turn off lights that have been on too long)
        for device_id, state in list(flash_states.items()):
            if state['is_on'] and (current_time - state['flash_time']) > config['flash_duration']:
                with devices_lock:
                    device = next((d for d in devices if d['id'] == device_id), None)
                    if device:
                        client.publish(
                            device["topic"],
                            get_device_config(device["type"], None, turn_off=True),
                            qos=0,
                            retain=False
                        )
                        flash_states[device_id]['is_on'] = False
                        socketio.emit('device_state', {
                            'device_id': device_id,
                            'state': 'off'
                        })
        
        samples = indata[:, 0].astype(np.float32)
        
        if _HAS_AUBIO:
            samples_a = samples.astype(aubio.float_type)
            is_beat = tempo_detect(samples_a)
            pitch = pitch_detect(samples_a)[0]
        else:
            # Simple energy-based beat detection fallback
            energy = np.sum(samples ** 2) / len(samples)
            threshold = config['beat_threshold']
            is_beat = np.array([energy > threshold])
            # Better pitch estimate using FFT peak
            fft = np.abs(np.fft.rfft(samples))
            freqs = np.fft.rfftfreq(len(samples), 1.0 / SAMPLE_RATE)
            peak_idx = np.argmax(fft)
            pitch = freqs[peak_idx] if fft.sum() > 0 and peak_idx > 0 else 0.0

        volume = np.sum(samples ** 2) / len(samples)
        stats['current_frequency'] = float(pitch)
        
        # Volume gate
        if volume < config['min_volume']:
            return
        
        if is_beat[0] and pitch > 0:
            stats['beats_detected'] += 1
            stats['last_beat_time'] = current_time
            
            log_and_emit('debug', f'Beat detected', {
                'pitch': float(pitch),
                'volume': float(volume)
            })
            
            # Check each device to see if it should react to this frequency
            with devices_lock:
                active_devices = [d for d in devices if d['enabled']]
            
            for device in active_devices:
                device_id = device['id']
                
                # Check if frequency is in device's ranges
                if not frequency_in_ranges(pitch, device['freq_ranges']):
                    log_and_emit('debug', f'{device["name"]}: Frequency {pitch:.0f}Hz outside ranges')
                    continue
                
                # Rate limiting per device
                if device_id not in last_publish_time:
                    last_publish_time[device_id] = 0
                
                if current_time - last_publish_time[device_id] < config['min_publish_interval']:
                    continue
                
                # Handle different modes
                if device['mode'] == 'flash':
                    # Flash mode: turn on, will be turned off by timeout
                    colour = device.get('flash_color', '255,255,255')
                    
                    client.publish(
                        device["topic"], 
                        get_device_config(device["type"], colour),
                        qos=0,
                        retain=False
                    )
                    
                    # Track flash state
                    flash_states[device_id] = {
                        'flash_time': current_time,
                        'is_on': True
                    }
                    
                    log_and_emit('info', f'{device["name"]}: FLASH (freq: {pitch:.0f}Hz)')
                    
                    socketio.emit('device_state', {
                        'device_id': device_id,
                        'device_name': device['name'],
                        'state': 'flash',
                        'colour': colour,
                        'hex': convert_to_hex(colour),
                        'pitch': float(pitch),
                        'volume': float(volume)
                    })
                    
                else:  # reactive mode
                    # Get new colour
                    colour_dict = change_colour(pitch)
                    
                    # Avoid repeating same colour for this device
                    if device_id in last_colours:
                        attempts = 0
                        while colour_dict["value"] == last_colours[device_id] and attempts < 5:
                            colour_dict = change_colour(pitch)
                            attempts += 1
                    
                    colour = colour_dict["value"]
                    
                    log_and_emit('info', f'{device["name"]}: {colour_dict["colour"]} (freq: {pitch:.0f}Hz)')
                    
                    # Publish to device
                    client.publish(
                        device["topic"], 
                        get_device_config(device["type"], colour),
                        qos=0,
                        retain=False
                    )
                    
                    socketio.emit('device_state', {
                        'device_id': device_id,
                        'device_name': device['name'],
                        'state': 'on',
                        'colour': colour,
                        'hex': convert_to_hex(colour),
                        'name': colour_dict["colour"],
                        'pitch': float(pitch),
                        'volume': float(volume)
                    })
                    
                    last_colours[device_id] = colour
                
                stats['messages_sent'] += 1
                last_publish_time[device_id] = current_time

    try:
        with sd.InputStream(channels=CHANNELS, samplerate=SAMPLE_RATE, 
                          blocksize=PERIOD_SIZE_IN_FRAME, dtype='float32', 
                          callback=audio_callback):
            while go:
                sleep(0.1)
    except KeyboardInterrupt:
        log_and_emit('info', 'Stopped by user')
    except Exception as e:
        log_and_emit('error', f'Audio processing error: {e}')
    finally:
        stats['running'] = False
        log_and_emit('info', 'Audio processing stopped')

@app.route('/start', methods=['POST'])
def start():
    global go
    if not go:
        go = True
        thread = Thread(target=run, daemon=True)
        thread.start()
        log_and_emit('info', 'System started')
    return {'status': 'started'}

@app.route('/stop', methods=['POST'])
def stop():
    global go
    if go:
        go = False
        sleep(0.2)
        
        with devices_lock:
            for device in devices:
                if device['enabled']:
                    client.publish(
                        device["topic"], 
                        get_device_config(device["type"], "white"),
                        qos=0
                    )
        log_and_emit('info', 'System stopped, lights set to white')
    return {'status': 'stopped'}

@app.route('/config', methods=['POST'])
def update_config():
    data = request.json
    for key in ['min_publish_interval', 'beat_threshold', 'min_volume', 'flash_duration']:
        if key in data:
            config[key] = float(data[key])
    
    if 'debug' in data:
        config['debug'] = bool(data['debug'])
        logger.setLevel(logging.DEBUG if config['debug'] else logging.INFO)
    
    log_and_emit('info', f'Configuration updated: {data}')
    return {'status': 'ok', 'config': config}

@app.route('/devices', methods=['GET'])
def get_devices():
    with devices_lock:
        return jsonify(devices)

@app.route('/devices', methods=['POST'])
def add_device():
    data = request.json
    device = {
        'id': data.get('id', f"device_{int(time())}"),
        'name': data['name'],
        'topic': data['topic'],
        'type': data.get('type', 'zigbee'),
        'enabled': data.get('enabled', True),
        'mode': data.get('mode', 'reactive'),
        'flash_color': data.get('flash_color', '255,255,255'),
        'freq_ranges': data.get('freq_ranges', [{'min': 20, 'max': 20000}]),
    }
    with devices_lock:
        devices.append(device)
    log_and_emit('info', f'Device added: {device["name"]}')
    socketio.emit('devices_updated', devices)
    return jsonify(device)

@app.route('/devices/<device_id>', methods=['PUT'])
def update_device(device_id):
    data = request.json
    with devices_lock:
        device = next((d for d in devices if d['id'] == device_id), None)
        if not device:
            return {'error': 'Device not found'}, 404
        
        device.update({
            'name': data.get('name', device['name']),
            'topic': data.get('topic', device['topic']),
            'type': data.get('type', device['type']),
            'enabled': data.get('enabled', device['enabled']),
            'mode': data.get('mode', device.get('mode', 'reactive')),
            'flash_color': data.get('flash_color', device.get('flash_color', '255,255,255')),
            'freq_ranges': data.get('freq_ranges', device['freq_ranges']),
        })
    
    log_and_emit('info', f'Device updated: {device["name"]}')
    socketio.emit('devices_updated', devices)
    return jsonify(device)

@app.route('/devices/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    with devices_lock:
        global devices
        devices = [d for d in devices if d['id'] != device_id]
    log_and_emit('info', f'Device deleted: {device_id}')
    socketio.emit('devices_updated', devices)
    return {'status': 'deleted'}

@app.route('/stats', methods=['GET'])
def get_stats():
    return {**stats, 'config': config}

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

@app.route('/', methods=['GET'])
def index():
    return """
<!DOCTYPE html>
<html>
<head>
  <meta content="width=device-width, initial-scale=1" name="viewport"/>
  <title>Music Visualizer Control</title>
  <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      max-width: 1400px;
      margin: 0 auto;
      padding: 20px;
      background: #0a0a0a;
      color: #fff;
    }
    .btn {
      border-radius: 8px;
      padding: 15px;
      font-size: 16pt;
      margin: 10px 0;
      border: none;
      cursor: pointer;
      font-weight: 600;
      transition: all 0.2s;
    }
    .btn-start { background: #00ff88; color: #000; }
    .btn-stop { background: #ff4444; color: #fff; }
    .btn-add { background: #4488ff; color: #fff; padding: 10px 20px; font-size: 14pt; }
    .btn:hover { opacity: 0.8; transform: scale(1.02); }
    .btn:active { transform: scale(0.98); }
    
    .control-group {
      background: #1a1a1a;
      padding: 15px;
      border-radius: 8px;
      margin: 15px 0;
    }
    .control-group h3 { margin-top: 0; }
    .control-group label {
      display: block;
      margin: 10px 0 5px 0;
      font-weight: 500;
    }
    .control-group input[type="range"] {
      width: 100%;
    }
    .control-group input[type="checkbox"] {
      width: 20px;
      height: 20px;
      margin-right: 10px;
    }
    .control-group input[type="text"],
    .control-group input[type="number"],
    .control-group select {
      width: 100%;
      padding: 8px;
      border-radius: 4px;
      border: 1px solid #333;
      background: #000;
      color: #fff;
      margin: 5px 0;
    }
    
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin: 15px 0;
    }
    .stat-box {
      background: #1a1a1a;
      padding: 15px;
      border-radius: 8px;
      text-align: center;
    }
    .stat-value {
      font-size: 24pt;
      font-weight: bold;
      color: #00ff88;
    }
    .stat-label {
      font-size: 10pt;
      color: #888;
      margin-top: 5px;
    }
    
    /* Device Circles */
    .devices-visual {
      display: flex;
      flex-wrap: wrap;
      gap: 20px;
      justify-content: center;
      padding: 20px;
      background: #000;
      border-radius: 8px;
      margin: 20px 0;
    }
    
    .device-circle {
      position: relative;
      width: 150px;
      height: 150px;
    }
    
    .circle {
      width: 150px;
      height: 150px;
      border-radius: 50%;
      background: #1a1a1a;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      transition: all 0.3s ease;
      border: 3px solid #333;
      box-shadow: 0 0 20px rgba(0,0,0,0.5);
    }
    
    .circle.flash {
      animation: flash-pulse 0.3s ease-out;
    }
    
    @keyframes flash-pulse {
      0% { transform: scale(1); }
      50% { transform: scale(1.1); box-shadow: 0 0 40px currentColor; }
      100% { transform: scale(1); }
    }
    
    .circle-name {
      font-size: 12pt;
      font-weight: bold;
      text-align: center;
      margin-bottom: 5px;
      color: #fff;
      text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
    }
    
    .circle-freq {
      font-size: 9pt;
      color: #ccc;
      text-align: center;
      text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
    }
    
    .circle-mode {
      position: absolute;
      top: -10px;
      right: -10px;
      background: #4488ff;
      color: #fff;
      padding: 4px 8px;
      border-radius: 12px;
      font-size: 9pt;
      font-weight: bold;
    }
    
    .circle-mode.flash-mode {
      background: #ff4444;
    }
    
    .device-card {
      background: #1a1a1a;
      padding: 15px;
      border-radius: 8px;
      margin: 10px 0;
      border-left: 4px solid #00ff88;
    }
    .device-card.disabled {
      opacity: 0.5;
      border-left-color: #666;
    }
    .device-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
    }
    .device-name {
      font-size: 14pt;
      font-weight: bold;
    }
    .device-controls {
      display: flex;
      gap: 10px;
    }
    .device-controls button {
      padding: 5px 15px;
      border-radius: 4px;
      border: none;
      cursor: pointer;
      font-size: 11pt;
    }
    .btn-edit { background: #4488ff; color: #fff; }
    .btn-delete { background: #ff4444; color: #fff; }
    .device-info {
      font-size: 10pt;
      color: #888;
      margin: 5px 0;
    }
    
    .freq-ranges-list {
      margin: 10px 0;
    }
    .freq-range-item {
      display: flex;
      gap: 10px;
      align-items: center;
      margin: 5px 0;
      padding: 5px;
      background: #2a2a2a;
      border-radius: 4px;
    }
    .freq-range-item input {
      flex: 1;
      padding: 5px;
    }
    .freq-range-item button {
      padding: 5px 10px;
      border-radius: 4px;
      background: #ff4444;
      color: #fff;
      border: none;
      cursor: pointer;
    }
    
    .freq-presets {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin: 10px 0;
    }
    .preset-btn {
      padding: 5px 10px;
      border-radius: 4px;
      background: #2a2a2a;
      border: 1px solid #444;
      color: #fff;
      cursor: pointer;
      font-size: 10pt;
    }
    .preset-btn:hover { background: #3a3a3a; }
    
    .modal {
      display: none;
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: rgba(0,0,0,0.9);
      z-index: 1000;
      align-items: center;
      justify-content: center;
    }
    .modal.show { display: flex; }
    .modal-content {
      background: #1a1a1a;
      padding: 20px;
      border-radius: 8px;
      max-width: 600px;
      width: 90%;
      max-height: 90vh;
      overflow-y: auto;
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
    }
    .modal-close {
      background: #ff4444;
      color: #fff;
      border: none;
      padding: 5px 15px;
      border-radius: 4px;
      cursor: pointer;
    }
    
    .grid-2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    
    #log-container {
      background: #000;
      border: 1px solid #333;
      border-radius: 8px;
      height: 200px;
      overflow-y: auto;
      padding: 10px;
      font-family: 'Courier New', monospace;
      font-size: 11px;
    }
    .log-entry {
      margin: 2px 0;
      padding: 2px 0;
    }
    .log-info { color: #00ff88; }
    .log-debug { color: #888; }
    .log-warning { color: #ffaa00; }
    .log-error { color: #ff4444; }
    
    .mode-selector {
      display: flex;
      gap: 10px;
      margin: 15px 0;
    }
    .mode-selector label {
      flex: 1;
      padding: 10px;
      background: #2a2a2a;
      border-radius: 4px;
      cursor: pointer;
      text-align: center;
      border: 2px solid transparent;
    }
    .mode-selector input[type="radio"] {
      display: none;
    }
    .mode-selector input[type="radio"]:checked + span {
      border-color: #00ff88;
      background: #1a3a2a;
    }
    .mode-selector label:hover {
      background: #3a3a3a;
    }
    
    .color-picker-wrapper {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .color-picker-wrapper input[type="color"] {
      width: 60px;
      height: 40px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
    }
  </style>
</head>
<body>
  <h1>🎵 Music Visualizer</h1>
  
  <div class="grid-2">
    <button class="btn btn-start" onclick="start()">▶ Start</button>
    <button class="btn btn-stop" onclick="stop()">⏹ Stop</button>
  </div>
  
  <div class="stats">
    <div class="stat-box">
      <div class="stat-value" id="beats">0</div>
      <div class="stat-label">Beats Detected</div>
    </div>
    <div class="stat-box">
      <div class="stat-value" id="messages">0</div>
      <div class="stat-label">Messages Sent</div>
    </div>
    <div class="stat-box">
      <div class="stat-value" id="frequency">0</div>
      <div class="stat-label">Current Frequency (Hz)</div>
    </div>
    <div class="stat-box">
      <div class="stat-value" id="status">Stopped</div>
      <div class="stat-label">Status</div>
    </div>
  </div>
  
  <div class="control-group">
    <h3>Live Visualization</h3>
    <div class="devices-visual" id="devices-visual">
      <p style="color: #888;">No devices configured</p>
    </div>
  </div>
  
  <div class="control-group">
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <h3>Devices</h3>
      <button class="btn btn-add" onclick="showAddDevice()">+ Add Device</button>
    </div>
    <div id="devices-list"></div>
  </div>
  
  <div class="control-group">
    <h3>Settings</h3>
    <label>
      <input type="checkbox" id="debug" onchange="updateConfig()"> Debug Logging
    </label>
    <label>
      Min Publish Interval: <span id="interval-val">0.1</span>s
      <input type="range" id="interval" min="0.05" max="0.5" step="0.05" value="0.1" onchange="updateConfig()">
    </label>
    <label>
      Beat Threshold: <span id="threshold-val">0.01</span>
      <input type="range" id="threshold" min="0.001" max="0.1" step="0.001" value="0.01" onchange="updateConfig()">
    </label>
    <label>
      Min Volume: <span id="volume-val">0.005</span>
      <input type="range" id="volume" min="0.001" max="0.05" step="0.001" value="0.005" onchange="updateConfig()">
    </label>
    <label>
      Flash Duration: <span id="flash-val">0.3</span>s
      <input type="range" id="flash" min="0.1" max="2" step="0.1" value="0.3" onchange="updateConfig()">
    </label>
  </div>
  
  <div class="control-group">
    <h3>Log</h3>
    <div id="log-container"></div>
  </div>

  <!-- Device Modal -->
  <div id="device-modal" class="modal">
    <div class="modal-content">
      <div class="modal-header">
        <h3 id="modal-title">Add Device</h3>
        <button class="modal-close" onclick="closeModal()">✕</button>
      </div>
      <form id="device-form" onsubmit="saveDevice(event)">
        <input type="hidden" id="device-id">
        <label>
          Device Name:
          <input type="text" id="device-name" required>
        </label>
        <label>
          MQTT Topic:
          <input type="text" id="device-topic" placeholder="zigbee2mqtt/Device Name/set" required>
        </label>
        <label>
          Type:
          <select id="device-type">
            <option value="zigbee">Zigbee</option>
            <option value="tasmota">Tasmota</option>
          </select>
        </label>
        <label>
          <input type="checkbox" id="device-enabled" checked> Enabled
        </label>
        
        <h4>Mode</h4>
        <div class="mode-selector">
          <label>
            <input type="radio" name="mode" value="reactive" checked>
            <span style="display: block; padding: 10px; border-radius: 4px; border: 2px solid transparent;">
              🌈 Reactive<br><small>Change colors on beat</small>
            </span>
          </label>
          <label>
            <input type="radio" name="mode" value="flash">
            <span style="display: block; padding: 10px; border-radius: 4px; border: 2px solid transparent;">
              ⚡ Flash<br><small>Pulse on/off on beat</small>
            </span>
          </label>
        </div>
        
        <div id="flash-color-section" style="display: none;">
          <h4>Flash Color</h4>
          <div class="color-picker-wrapper">
            <input type="color" id="flash-color-picker" value="#ff0000">
            <input type="text" id="flash-color-rgb" value="255,0,0" placeholder="R,G,B">
          </div>
        </div>
        
        <h4>Frequency Ranges</h4>
        <div class="freq-presets">
          <button type="button" class="preset-btn" onclick="addFreqPreset('sub_bass')">+ Sub Bass</button>
          <button type="button" class="preset-btn" onclick="addFreqPreset('bass')">+ Bass</button>
          <button type="button" class="preset-btn" onclick="addFreqPreset('low_mid')">+ Low Mid</button>
          <button type="button" class="preset-btn" onclick="addFreqPreset('mid')">+ Mid</button>
          <button type="button" class="preset-btn" onclick="addFreqPreset('high_mid')">+ High Mid</button>
          <button type="button" class="preset-btn" onclick="addFreqPreset('presence')">+ Presence</button>
          <button type="button" class="preset-btn" onclick="addFreqPreset('brilliance')">+ Brilliance</button>
          <button type="button" class="preset-btn" onclick="addFreqPreset('full')">+ Full</button>
        </div>
        <div id="freq-ranges-list" class="freq-ranges-list"></div>
        <button type="button" class="btn-add" style="width: 100%; margin-top: 10px;" onclick="addFreqRange()">+ Add Custom Range</button>
        
        <button type="submit" class="btn btn-start" style="margin-top: 20px;">Save Device</button>
      </form>
    </div>
  </div>

  <script>
    const socket = io();
    const freqPresets = {
      'sub_bass': {min: 20, max: 60, name: 'Sub Bass'},
      'bass': {min: 60, max: 250, name: 'Bass'},
      'low_mid': {min: 250, max: 500, name: 'Low Mid'},
      'mid': {min: 500, max: 2000, name: 'Mid'},
      'high_mid': {min: 2000, max: 4000, name: 'High Mid'},
      'presence': {min: 4000, max: 6000, name: 'Presence'},
      'brilliance': {min: 6000, max: 20000, name: 'Brilliance'},
      'full': {min: 20, max: 20000, name: 'Full'}
    };
    
    let currentFreqRanges = [];
    let deviceStates = {}; // Track current state of each device
    
    socket.on('log', (data) => {
      const log = document.getElementById('log-container');
      const entry = document.createElement('div');
      entry.className = `log-entry log-${data.level}`;
      const timestamp = new Date(data.timestamp * 1000).toLocaleTimeString();
      entry.textContent = `[${timestamp}] ${data.message}`;
      log.appendChild(entry);
      log.scrollTop = log.scrollHeight;
      
      while (log.children.length > 100) {
        log.removeChild(log.firstChild);
      }
    });
    
    socket.on('device_state', (data) => {
      deviceStates[data.device_id] = data;
      updateDeviceCircle(data.device_id, data);
    });
    
    socket.on('devices_updated', loadDevices);
    
    function updateDeviceCircle(deviceId, state) {
      const circle = document.getElementById(`circle-${deviceId}`);
      if (!circle) return;
      
      if (state.state === 'flash' || state.state === 'on') {
        circle.style.backgroundColor = state.hex;
        circle.style.borderColor = state.hex;
        
        if (state.state === 'flash') {
          circle.classList.add('flash');
          setTimeout(() => circle.classList.remove('flash'), 300);
        }
      } else if (state.state === 'off') {
        circle.style.backgroundColor = '#1a1a1a';
        circle.style.borderColor = '#333';
      }
    }
    
    function start() {
      fetch('/start', { method: 'POST' });
    }
    
    function stop() {
      fetch('/stop', { method: 'POST' });
    }
    
    function updateConfig() {
      const debug = document.getElementById('debug').checked;
      const interval = parseFloat(document.getElementById('interval').value);
      const threshold = parseFloat(document.getElementById('threshold').value);
      const volume = parseFloat(document.getElementById('volume').value);
      const flash = parseFloat(document.getElementById('flash').value);
      
      document.getElementById('interval-val').textContent = interval.toFixed(2);
      document.getElementById('threshold-val').textContent = threshold.toFixed(3);
      document.getElementById('volume-val').textContent = volume.toFixed(3);
      document.getElementById('flash-val').textContent = flash.toFixed(1);
      
      fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          debug: debug,
          min_publish_interval: interval,
          beat_threshold: threshold,
          min_volume: volume,
          flash_duration: flash
        })
      });
    }
    
    function loadDevices() {
      fetch('/devices')
        .then(r => r.json())
        .then(devices => {
          // Update visual circles
          const visual = document.getElementById('devices-visual');
          if (devices.length === 0) {
            visual.innerHTML = '<p style="color: #888;">No devices configured</p>';
          } else {
            visual.innerHTML = devices.filter(d => d.enabled).map(d => {
              const freqText = d.freq_ranges.map(r => {
                // Check if it matches a preset
                for (const [key, preset] of Object.entries(freqPresets)) {
                  if (preset.min === r.min && preset.max === r.max) {
                    return preset.name;
                  }
                }
                return `${r.min}-${r.max}Hz`;
              }).join(', ');
              
              return `
                <div class="device-circle">
                  ${d.mode === 'flash' ? '<div class="circle-mode flash-mode">FLASH</div>' : '<div class="circle-mode">COLOR</div>'}
                  <div class="circle" id="circle-${d.id}">
                    <div class="circle-name">${d.name}</div>
                    <div class="circle-freq">${freqText}</div>
                  </div>
                </div>
              `;
            }).join('');
          }
          
          // Update device list
          const list = document.getElementById('devices-list');
          if (devices.length === 0) {
            list.innerHTML = '<p style="color: #888;">No devices configured. Click "Add Device" to get started.</p>';
            return;
          }
          
          list.innerHTML = devices.map(d => {
            const freqText = d.freq_ranges.map(r => {
              for (const [key, preset] of Object.entries(freqPresets)) {
                if (preset.min === r.min && preset.max === r.max) {
                  return `<span style="color: #00ff88;">${preset.name}</span>`;
                }
              }
              return `${r.min}-${r.max}Hz`;
            }).join(', ');
            
            return `
              <div class="device-card ${d.enabled ? '' : 'disabled'}">
                <div class="device-header">
                  <div class="device-name">${d.name} ${d.enabled ? '' : '(Disabled)'}</div>
                  <div class="device-controls">
                    <button class="btn-edit" onclick="editDevice('${d.id}')">✎ Edit</button>
                    <button class="btn-delete" onclick="deleteDevice('${d.id}')">🗑</button>
                  </div>
                </div>
                <div class="device-info">
                  <strong>Topic:</strong> ${d.topic}<br>
                  <strong>Type:</strong> ${d.type}<br>
                  <strong>Mode:</strong> ${d.mode === 'flash' ? '⚡ Flash' : '🌈 Reactive'}<br>
                  <strong>Frequency:</strong> ${freqText}
                </div>
              </div>
            `;
          }).join('');
        });
    }
    
    function showAddDevice() {
      document.getElementById('modal-title').textContent = 'Add Device';
      document.getElementById('device-form').reset();
      document.getElementById('device-id').value = '';
      document.getElementById('device-enabled').checked = true;
      document.querySelector('input[name="mode"][value="reactive"]').checked = true;
      document.getElementById('flash-color-section').style.display = 'none';
      currentFreqRanges = [{min: 20, max: 20000}];
      renderFreqRanges();
      document.getElementById('device-modal').classList.add('show');
    }
    
    function editDevice(id) {
      fetch('/devices')
        .then(r => r.json())
        .then(devices => {
          const device = devices.find(d => d.id === id);
          if (!device) return;
          
          document.getElementById('modal-title').textContent = 'Edit Device';
          document.getElementById('device-id').value = device.id;
          document.getElementById('device-name').value = device.name;
          document.getElementById('device-topic').value = device.topic;
          document.getElementById('device-type').value = device.type;
          document.getElementById('device-enabled').checked = device.enabled;
          
          document.querySelector(`input[name="mode"][value="${device.mode}"]`).checked = true;
          document.getElementById('flash-color-section').style.display = device.mode === 'flash' ? 'block' : 'none';
          
          if (device.flash_color) {
            document.getElementById('flash-color-rgb').value = device.flash_color;
            const hex = rgbToHex(device.flash_color);
            document.getElementById('flash-color-picker').value = hex;
          }
          
          currentFreqRanges = device.freq_ranges || [{min: 20, max: 20000}];
          renderFreqRanges();
          document.getElementById('device-modal').classList.add('show');
        });
    }
    
    function deleteDevice(id) {
      if (!confirm('Delete this device?')) return;
      fetch(`/devices/${id}`, { method: 'DELETE' })
        .then(() => loadDevices());
    }
    
    function closeModal() {
      document.getElementById('device-modal').classList.remove('show');
    }
    
    function addFreqRange() {
      currentFreqRanges.push({min: 20, max: 20000});
      renderFreqRanges();
    }
    
    function addFreqPreset(preset) {
      const freq = freqPresets[preset];
      currentFreqRanges.push({min: freq.min, max: freq.max});
      renderFreqRanges();
    }
    
    function removeFreqRange(index) {
      currentFreqRanges.splice(index, 1);
      if (currentFreqRanges.length === 0) {
        currentFreqRanges = [{min: 20, max: 20000}];
      }
      renderFreqRanges();
    }
    
    function renderFreqRanges() {
      const container = document.getElementById('freq-ranges-list');
      container.innerHTML = currentFreqRanges.map((range, index) => `
        <div class="freq-range-item">
          <input type="number" value="${range.min}" min="20" max="20000" 
                 onchange="currentFreqRanges[${index}].min = parseInt(this.value)" 
                 placeholder="Min Hz">
          <span>to</span>
          <input type="number" value="${range.max}" min="20" max="20000" 
                 onchange="currentFreqRanges[${index}].max = parseInt(this.value)"
                 placeholder="Max Hz">
          <button type="button" onclick="removeFreqRange(${index})">✕</button>
        </div>
      `).join('');
    }
    
    function rgbToHex(rgb) {
      const parts = rgb.split(',').map(p => parseInt(p.trim()));
      return '#' + parts.map(p => p.toString(16).padStart(2, '0')).join('');
    }
    
    function hexToRgb(hex) {
      const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
      return result ? 
        `${parseInt(result[1], 16)},${parseInt(result[2], 16)},${parseInt(result[3], 16)}` : 
        '255,255,255';
    }
    
    // Mode change handler
    document.addEventListener('change', (e) => {
      if (e.target.name === 'mode') {
        const flashSection = document.getElementById('flash-color-section');
        flashSection.style.display = e.target.value === 'flash' ? 'block' : 'none';
      }
    });
    
    // Color picker sync
    document.addEventListener('input', (e) => {
      if (e.target.id === 'flash-color-picker') {
        document.getElementById('flash-color-rgb').value = hexToRgb(e.target.value);
      } else if (e.target.id === 'flash-color-rgb') {
        try {
          const hex = rgbToHex(e.target.value);
          document.getElementById('flash-color-picker').value = hex;
        } catch (err) {}
      }
    });
    
    function saveDevice(e) {
      e.preventDefault();
      
      const id = document.getElementById('device-id').value;
      const mode = document.querySelector('input[name="mode"]:checked').value;
      
      const data = {
        id: id || undefined,
        name: document.getElementById('device-name').value,
        topic: document.getElementById('device-topic').value,
        type: document.getElementById('device-type').value,
        enabled: document.getElementById('device-enabled').checked,
        mode: mode,
        flash_color: mode === 'flash' ? document.getElementById('flash-color-rgb').value : '255,255,255',
        freq_ranges: currentFreqRanges
      };
      
      const method = id ? 'PUT' : 'POST';
      const url = id ? `/devices/${id}` : '/devices';
      
      fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      .then(r => r.json())
      .then(() => {
        closeModal();
        loadDevices();
      });
    }
    
    // Update stats every second
    setInterval(() => {
      fetch('/stats')
        .then(r => r.json())
        .then(data => {
          document.getElementById('beats').textContent = data.beats_detected;
          document.getElementById('messages').textContent = data.messages_sent;
          document.getElementById('frequency').textContent = Math.round(data.current_frequency);
          document.getElementById('status').textContent = data.running ? 'Running' : 'Stopped';
        });
    }, 1000);
    
    // Load devices on startup
    loadDevices();
  </script>
</body>
</html>
    """

if __name__ == '__main__':
    try:
        log_and_emit('info', 'Music Visualizer starting...')
        socketio.run(app, host='0.0.0.0', port=8888, debug=False, allow_unsafe_werkzeug=True)
    finally:
        go = False
        client.loop_stop()
        client.disconnect()
        log_and_emit('info', 'Shutdown complete')