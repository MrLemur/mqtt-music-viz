"""Application entrypoint for mqtt-music-viz."""
from flask import Flask
from api import bp as api_bp
from api.websocket import socketio
from config import load_config
import logging
import paho.mqtt.client as mqtt
import sys
import os
import signal
from threading import Thread
from time import sleep

logger = logging.getLogger(__name__)


def watch_config_file(config_path: str = "config.yaml"):
    """Watch config file for changes and trigger reload."""
    try:
        last_mtime = os.path.getmtime(config_path)
        logger.info(f"Watching {config_path} for changes...")
        
        while True:
            sleep(1)  # Check every second
            try:
                current_mtime = os.path.getmtime(config_path)
                if current_mtime != last_mtime:
                    logger.info(f"⚠️  {config_path} changed - reloading application...")
                    last_mtime = current_mtime
                    sleep(0.5)  # Brief delay to ensure file write is complete
                    
                    # Trigger app reload by sending SIGTERM to self
                    os.kill(os.getpid(), signal.SIGTERM)
                    break
            except FileNotFoundError:
                logger.warning(f"{config_path} not found, stopping watch")
                break
    except Exception as e:
        logger.error(f"Config file watcher error: {e}")


def check_mqtt_connection(mqtt_config) -> bool:
    """Test MQTT connection before starting the application."""
    logger.info(f"Testing MQTT connection to {mqtt_config.host}:{mqtt_config.port}...")
    
    connection_successful = False
    connection_error = None
    
    def on_connect(client, userdata, flags, rc):
        nonlocal connection_successful, connection_error
        if rc == 0:
            connection_successful = True
            logger.info("✓ MQTT connection successful")
        else:
            connection_error = f"Connection failed with code {rc}"
            logger.error(f"✗ MQTT connection failed with code {rc}")
    
    try:
        test_client = mqtt.Client(client_id="mqtt_viz_test", clean_session=True)
        test_client.on_connect = on_connect
        
        if mqtt_config.username and mqtt_config.password:
            test_client.username_pw_set(mqtt_config.username, mqtt_config.password)
        
        test_client.connect(mqtt_config.host, mqtt_config.port, keepalive=5)
        test_client.loop_start()
        
        # Wait for connection (max 5 seconds)
        import time
        for _ in range(50):
            if connection_successful or connection_error:
                break
            time.sleep(0.1)
        
        test_client.loop_stop()
        test_client.disconnect()
        
        if not connection_successful:
            if connection_error:
                logger.error(f"MQTT connection check failed: {connection_error}")
            else:
                logger.error("MQTT connection check timed out")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"MQTT connection check error: {e}")
        return False


def create_app(config_path: str = "config.yaml") -> Flask:
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config["APP_CONFIG"] = load_config(config_path)
    app.register_blueprint(api_bp)

    return app


def run():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Load configuration
    try:
        config = load_config()
        logger.info("✓ Configuration loaded")
    except Exception as e:
        logger.error(f"✗ Failed to load configuration: {e}")
        sys.exit(1)
    
    # Check MQTT connection
    if not check_mqtt_connection(config.mqtt):
        logger.error("✗ Cannot start application without MQTT connection")
        logger.error(f"   Please check MQTT broker is running at {config.mqtt.host}:{config.mqtt.port}")
        sys.exit(1)
    
    # Initialize MQTT manager
    from core.mqtt import MQTTManager
    mqtt_manager = MQTTManager(
        host=config.mqtt.host,
        port=config.mqtt.port,
        username=config.mqtt.username,
        password=config.mqtt.password
    )
    mqtt_manager.connect()
    
    # Initialize application state
    from core.state import get_state
    state = get_state()
    state.initialize(config, mqtt_manager)
    
    # Create and run app
    app = create_app()
    socketio.init_app(app)
    
    # Set socketio in state for real-time updates
    state.set_socketio(socketio)
    
    # Auto-start if system was running before restart
    state.auto_restart_if_was_running()
    
    # Start config file watcher in background thread
    watcher_thread = Thread(target=watch_config_file, args=("config.yaml",), daemon=True)
    watcher_thread.start()
    
    logger.info(f"Starting web server on http://0.0.0.0:8888")
    logger.info(f"Auto-reload enabled - changes to config.yaml will restart the app")
    socketio.run(app, host='0.0.0.0', port=8888, use_reloader=False)  # Disable werkzeug reloader, use our own


if __name__ == '__main__':
    run()
