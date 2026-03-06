"""
database.py — InfluxDB 2.x integration for STM32 5-channel ADC data.

Fields stored per measurement point:
  Tag:    device_id
  Fields: A0, A1, A2, A3, A4  (int, 0-4095)
  Time:   Unix timestamp from STM32 NTP-synced gateway
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import List, Optional

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.exceptions import InfluxDBError
from influxdb_client.client.write_api import SYNCHRONOUS

from models import DeviceInfo, LatestResponse, SensorReading

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
INFLUX_URL    = os.getenv("INFLUXDB_URL",    "http://influxdb:8086")
INFLUX_TOKEN  = os.getenv("INFLUXDB_TOKEN",  "iot_super_secret_token")
INFLUX_ORG    = os.getenv("INFLUXDB_ORG",    "iot_org")
INFLUX_BUCKET = os.getenv("INFLUXDB_BUCKET", "sensor_data")

MEASUREMENT   = "adc_readings"   # InfluxDB measurement name


# ─────────────────────────────────────────────
# Client singleton
# ─────────────────────────────────────────────

class InfluxDBService:
    """Thin service wrapper around influxdb-client-python."""

    def __init__(self) -> None:
        self._client     = None
        self._write_api  = None
        self._query_api  = None

    def connect(self) -> None:
        logger.info("Connecting to InfluxDB at %s ...", INFLUX_URL)
        self._client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        self._query_api = self._client.query_api()

        health = self._client.health()
        if health.status != "pass":
            raise RuntimeError(f"InfluxDB health check failed: {health.message}")
        logger.info("InfluxDB connected (status=%s)", health.status)

    def is_connected(self) -> bool:
        try:
            return self._client is not None and self._client.health().status == "pass"
        except Exception:
            return False

    def close(self) -> None:
        if self._client:
            self._client.close()
            logger.info("InfluxDB connection closed")

    # ─────────────────────────────────────────
    # Write
    # ─────────────────────────────────────────

    def write_sensor_data(
        self,
        device_id: str,
        A0: int,
        A1: int,
        A2: int,
        A3: int,
        A4: int,
        timestamp: int,          # Unix epoch seconds
    ) -> None:
        """
        Write one STM32 ADC frame as an InfluxDB Point.

        Tag:    device_id   (indexed, enables fast per-device queries)
        Fields: A0–A4       (raw 12-bit ADC integers, 0-4095)
        Time:   provided Unix timestamp (seconds precision)
        """
        point = (
            Point(MEASUREMENT)
            .tag("device_id", device_id)
            .field("A0", int(A0))
            .field("A1", int(A1))
            .field("A2", int(A2))
            .field("A3", int(A3))
            .field("A4", int(A4))
            .time(timestamp, WritePrecision.SECONDS)
        )
        try:
            self._write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            logger.debug("Wrote ADC frame device=%s ts=%d A0=%d A1=%d A2=%d A3=%d A4=%d",
                         device_id, timestamp, A0, A1, A2, A3, A4)
        except InfluxDBError as exc:
            logger.error("InfluxDB write error: %s", exc)
            raise

    # ─────────────────────────────────────────
    # Query: latest reading per device
    # ─────────────────────────────────────────

    def query_latest(self, device_id: Optional[str] = None) -> List[LatestResponse]:
        """Return the most recent ADC frame for each device (or a specific one)."""
        device_filter = (
            f'|> filter(fn: (r) => r["device_id"] == "{device_id}")'
            if device_id else ""
        )

        flux = f"""
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -1h)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
          {device_filter}
          |> filter(fn: (r) =>
               r["_field"] == "A0" or r["_field"] == "A1" or r["_field"] == "A2" or
               r["_field"] == "A3" or r["_field"] == "A4")
          |> last()
          |> pivot(rowKey: ["_time", "device_id"],
                   columnKey: ["_field"],
                   valueColumn: "_value")
        """

        results: List[LatestResponse] = []
        try:
            tables = self._query_api.query(flux, org=INFLUX_ORG)
            for table in tables:
                for record in table.records:
                    results.append(LatestResponse(
                        device_id = record.values.get("device_id", "unknown"),
                        A0        = int(record.values.get("A0", 0)),
                        A1        = int(record.values.get("A1", 0)),
                        A2        = int(record.values.get("A2", 0)),
                        A3        = int(record.values.get("A3", 0)),
                        A4        = int(record.values.get("A4", 0)),
                        timestamp = record.get_time(),
                    ))
        except InfluxDBError as exc:
            logger.error("InfluxDB query_latest error: %s", exc)

        return results

    # ─────────────────────────────────────────
    # Query: historical data
    # ─────────────────────────────────────────

    def query_history(
        self,
        device_id: Optional[str] = None,
        range_minutes: int = 60,
        limit: int = 500,
    ) -> List[SensorReading]:
        """Return time-ordered ADC frames within the last range_minutes."""
        device_filter = (
            f'|> filter(fn: (r) => r["device_id"] == "{device_id}")'
            if device_id else ""
        )

        flux = f"""
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -{range_minutes}m)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
          {device_filter}
          |> filter(fn: (r) =>
               r["_field"] == "A0" or r["_field"] == "A1" or r["_field"] == "A2" or
               r["_field"] == "A3" or r["_field"] == "A4")
          |> pivot(rowKey: ["_time", "device_id"],
                   columnKey: ["_field"],
                   valueColumn: "_value")
          |> sort(columns: ["_time"], desc: false)
          |> limit(n: {limit})
        """

        results: List[SensorReading] = []
        try:
            tables = self._query_api.query(flux, org=INFLUX_ORG)
            for table in tables:
                for record in table.records:
                    results.append(SensorReading(
                        device_id = record.values.get("device_id", "unknown"),
                        A0        = int(record.values.get("A0", 0)),
                        A1        = int(record.values.get("A1", 0)),
                        A2        = int(record.values.get("A2", 0)),
                        A3        = int(record.values.get("A3", 0)),
                        A4        = int(record.values.get("A4", 0)),
                        timestamp = record.get_time(),
                    ))
        except InfluxDBError as exc:
            logger.error("InfluxDB query_history error: %s", exc)

        return results

    # ─────────────────────────────────────────
    # Query: device list
    # ─────────────────────────────────────────

    def query_devices(self) -> List[DeviceInfo]:
        """Return summary for all devices active in the last 24 hours."""
        flux = f"""
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -24h)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
          |> filter(fn: (r) => r["_field"] == "A0")
          |> group(columns: ["device_id"])
          |> last()
          |> keep(columns: ["device_id", "_time"])
        """

        count_flux = f"""
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: -24h)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
          |> filter(fn: (r) => r["_field"] == "A0")
          |> group(columns: ["device_id"])
          |> count()
          |> keep(columns: ["device_id", "_value"])
        """

        last_seen:     dict = {}
        reading_count: dict = {}

        try:
            for table in self._query_api.query(flux, org=INFLUX_ORG):
                for record in table.records:
                    did = record.values.get("device_id", "unknown")
                    last_seen[did] = record.get_time()

            for table in self._query_api.query(count_flux, org=INFLUX_ORG):
                for record in table.records:
                    did = record.values.get("device_id", "unknown")
                    reading_count[did] = int(record.get_value() or 0)
        except InfluxDBError as exc:
            logger.error("InfluxDB query_devices error: %s", exc)

        return [
            DeviceInfo(
                device_id     = did,
                last_seen     = ts,
                reading_count = reading_count.get(did, 0),
            )
            for did, ts in last_seen.items()
        ]


# Module-level singleton
db = InfluxDBService()
