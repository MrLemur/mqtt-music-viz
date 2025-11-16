"""MQTT manager wrapper for publishing device state and handling connection."""
import logging
import time
import paho.mqtt.client as mqtt
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class MQTTManager:
    """Manages MQTT connections and publishing with auto-reconnect."""

    host: str
    port: int
    username: str | None = None
    password: str | None = None
    
    def __post_init__(self):
        self.client = None
        self._connected = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._on_connect_callback: Callable | None = None
        self._on_disconnect_callback: Callable | None = None
    
    def connect(self, on_connect: Callable | None = None, on_disconnect: Callable | None = None) -> None:
        """Establish MQTT connection with callbacks."""
        self._on_connect_callback = on_connect
        self._on_disconnect_callback = on_disconnect
        
        try:
            self.client = mqtt.Client(client_id="music_viz", clean_session=True)
            
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)
            
            self.client.on_connect = self._handle_connect
            self.client.on_disconnect = self._handle_disconnect
            self.client.on_publish = self._handle_publish
            
            logger.info(f"Connecting to MQTT broker at {self.host}:{self.port}")
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_start()
            
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            self._schedule_reconnect()
    
    def _handle_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker."""
        if rc == 0:
            self._connected = True
            self._reconnect_delay = 1.0  # Reset backoff on successful connection
            logger.info("Connected to MQTT broker")
            if self._on_connect_callback:
                self._on_connect_callback()
        else:
            self._connected = False
            logger.error(f"MQTT connection failed with code {rc}")
            self._schedule_reconnect()
    
    def _handle_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker."""
        self._connected = False
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection (code {rc}), reconnecting...")
            self._schedule_reconnect()
        else:
            logger.info("MQTT client disconnected")
        
        if self._on_disconnect_callback:
            self._on_disconnect_callback(rc)
    
    def _handle_publish(self, client, userdata, mid):
        """Callback when message is published."""
        logger.debug(f"Message {mid} published")
    
    def _schedule_reconnect(self):
        """Schedule reconnection with exponential backoff."""
        logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s...")
        time.sleep(self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
        
        if self.client:
            try:
                self.client.reconnect()
            except Exception as e:
                logger.error(f"Reconnection attempt failed: {e}")
                self._schedule_reconnect()
    
    def publish_device_state(self, topic: str, payload: str, turn_off: bool = False) -> bool:
        """Publish state change to device topic."""
        if not self._connected or not self.client:
            logger.warning(f"Cannot publish to {topic}: not connected")
            return False
        
        try:
            # Use QoS 1 for off commands to ensure delivery, QoS 0 for on/color changes
            qos = 2 if turn_off else 0
            result = self.client.publish(topic, payload, qos=qos, retain=False)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"Failed to publish to {topic}: {e}")
            return False
    
    def disconnect(self) -> None:
        """Clean disconnect from broker."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self._connected = False
            logger.info("MQTT client disconnected cleanly")
    
    @property
    def is_connected(self) -> bool:
        """Check if currently connected to broker."""
        return self._connected
