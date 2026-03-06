"""
models.py — Pydantic data models for STM32 ADC payloads and API responses.

STM32 transmits 5 raw 12-bit ADC channels (A0–A4, range 0–4095).
The ESP8266 gateway wraps them in JSON and publishes to MQTT.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────
# Inbound (from MQTT / ESP8266 gateway)
# ─────────────────────────────────────────────

class SensorPayload(BaseModel):
    """
    Validates the JSON payload arriving from the ESP8266 gateway.

    Expected JSON shape:
    {
        "device_id": "stm32_gateway_01",
        "A0": 512,
        "A1": 300,
        "A2": 1024,
        "A3": 750,
        "A4": 200,
        "timestamp": 1710000000
    }

    STM32 12-bit ADC -> valid range 0-4095.
    """
    device_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r'^[a-zA-Z0-9_\-]+$',
        description="Alphanumeric device identifier",
    )
    A0: int = Field(..., ge=0, le=4095, description="ADC channel 0 raw value (12-bit)")
    A1: int = Field(..., ge=0, le=4095, description="ADC channel 1 raw value (12-bit)")
    A2: int = Field(..., ge=0, le=4095, description="ADC channel 2 raw value (12-bit)")
    A3: int = Field(..., ge=0, le=4095, description="ADC channel 3 raw value (12-bit)")
    A4: int = Field(..., ge=0, le=4095, description="ADC channel 4 raw value (12-bit)")
    timestamp: int = Field(..., gt=0, description="Unix epoch seconds (UTC)")

    @field_validator("device_id")
    @classmethod
    def strip_device_id(cls, v: str) -> str:
        return v.strip()

    @field_validator("A0", "A1", "A2", "A3", "A4", mode="before")
    @classmethod
    def coerce_adc(cls, v):
        """Accept string integers that ArduinoJson may produce."""
        if isinstance(v, str):
            return int(v)
        return v


# ─────────────────────────────────────────────
# Outbound (API responses)
# ─────────────────────────────────────────────

class SensorReading(BaseModel):
    """A single validated ADC reading with an ISO timestamp."""
    device_id: str
    A0: int
    A1: int
    A2: int
    A3: int
    A4: int
    timestamp: datetime

    model_config = {"json_encoders": {datetime: lambda d: d.isoformat()}}


class LatestResponse(BaseModel):
    """Response for GET /api/latest"""
    device_id: str
    A0: int
    A1: int
    A2: int
    A3: int
    A4: int
    timestamp: datetime
    received_at: datetime = Field(default_factory=datetime.utcnow)


class HistoryResponse(BaseModel):
    """Response for GET /api/history"""
    device_id: str
    count: int
    readings: List[SensorReading]


class DeviceInfo(BaseModel):
    """Summary entry for GET /api/devices"""
    device_id: str
    last_seen: datetime
    reading_count: int


class DevicesResponse(BaseModel):
    """Response for GET /api/devices"""
    total: int
    devices: List[DeviceInfo]


class HealthResponse(BaseModel):
    """Response for GET /health"""
    status: str
    mqtt_connected: bool
    influxdb_connected: bool
    uptime_seconds: float
