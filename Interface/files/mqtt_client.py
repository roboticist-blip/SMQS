"""
mqtt_client.py — MQTT subscriber for STM32 ADC data.

Subscribes to iot/sensors/data, validates each message with Pydantic,
and persists all 5 ADC channels to InfluxDB.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from database import db
from models import SensorPayload

logger = logging.getLogger(__name__)

MQTT_HOST      = os.getenv("MQTT_HOST",     "mosquitto")
MQTT_PORT      = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER      = os.getenv("MQTT_USER",     "backend_service")
MQTT_PASS      = os.getenv("MQTT_PASS",     "backend_password")
MQTT_TOPIC     = os.getenv("MQTT_TOPIC",    "iot/sensors/data")
MQTT_CLIENT_ID = "iot_backend_service"
MQTT_KEEPALIVE = 60
RECONNECT_DELAY = 5


class MQTTService:
    def __init__(self) -> None:
        self._client: Optional[mqtt.Client] = None
        self._connected  = False
        self._running    = False
        self._lock       = threading.Lock()
        self.message_count = 0
        self.error_count   = 0

    def start(self) -> None:
        self._running = True
        self._client  = mqtt.Client(
            client_id     = MQTT_CLIENT_ID,
            clean_session = True,
            protocol      = mqtt.MQTTv311,
        )
        self._client.username_pw_set(MQTT_USER, MQTT_PASS)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message
        self._connect_with_retry()
        self._client.loop_start()
        logger.info("MQTT service started (topic=%s)", MQTT_TOPIC)

    def stop(self) -> None:
        self._running = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
        logger.info("MQTT service stopped")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _connect_with_retry(self) -> None:
        while self._running:
            try:
                logger.info("Connecting to MQTT broker %s:%d ...", MQTT_HOST, MQTT_PORT)
                self._client.connect(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEPALIVE)
                break
            except (ConnectionRefusedError, OSError) as exc:
                logger.warning("MQTT connect failed (%s) — retrying in %ds", exc, RECONNECT_DELAY)
                time.sleep(RECONNECT_DELAY)

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            client.subscribe(MQTT_TOPIC, qos=1)
            logger.info("MQTT connected — subscribed to %s", MQTT_TOPIC)
        else:
            self._connected = False
            logger.error("MQTT connection refused (rc=%d)", rc)

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        if rc != 0:
            logger.warning("MQTT unexpected disconnect (rc=%d)", rc)

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        """decode -> validate -> persist ADC frame."""
        raw = msg.payload.decode("utf-8", errors="replace")
        logger.debug("MQTT message on %s: %s", msg.topic, raw)

        # 1. Safe JSON parse
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON: %s | payload=%s", exc, raw[:200])
            self.error_count += 1
            return

        # 2. Pydantic validation (checks device_id pattern + ADC 0-4095 bounds)
        try:
            payload = SensorPayload(**data)
        except ValidationError as exc:
            logger.warning("Payload validation failed: %s | data=%s", exc, data)
            self.error_count += 1
            return

        # 3. Persist to InfluxDB
        try:
            db.write_sensor_data(
                device_id = payload.device_id,
                A0        = payload.A0,
                A1        = payload.A1,
                A2        = payload.A2,
                A3        = payload.A3,
                A4        = payload.A4,
                timestamp = payload.timestamp,
            )
            with self._lock:
                self.message_count += 1
            logger.info(
                "Stored ADC frame | device=%s A0=%d A1=%d A2=%d A3=%d A4=%d",
                payload.device_id,
                payload.A0, payload.A1, payload.A2, payload.A3, payload.A4,
            )
        except Exception as exc:
            logger.error("DB write failed: %s", exc)
            self.error_count += 1


mqtt_service = MQTTService()
