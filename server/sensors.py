"""
routes/sensors.py — FastAPI router for STM32 ADC data endpoints.

Endpoints:
  GET /api/latest          -> most recent ADC frame per device
  GET /api/history         -> time-series ADC frames with optional filters
  GET /api/devices         -> list of all known devices
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import db
from models import DevicesResponse, HistoryResponse, LatestResponse

router = APIRouter(prefix="/api", tags=["sensors"])


@router.get(
    "/latest",
    response_model=list[LatestResponse],
    summary="Latest ADC readings",
    description=(
        "Returns the most recent 5-channel ADC frame for every known device, "
        "or for a specific device when `device_id` is supplied."
    ),
)
async def get_latest(
    device_id: Optional[str] = Query(
        default=None,
        description="Filter to a single device",
        min_length=1,
        max_length=64,
        pattern=r'^[a-zA-Z0-9_\-]+$',
    )
) -> list[LatestResponse]:
    readings = db.query_latest(device_id=device_id)
    if not readings:
        raise HTTPException(status_code=404, detail="No recent readings found")
    return readings


@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Historical ADC readings",
    description="Returns time-ordered ADC frames from the last N minutes.",
)
async def get_history(
    device_id: Optional[str] = Query(
        default=None,
        description="Filter to a single device",
        min_length=1,
        max_length=64,
        pattern=r'^[a-zA-Z0-9_\-]+$',
    ),
    range_minutes: int = Query(
        default=60,
        ge=1,
        le=10080,
        description="Look-back window in minutes (default 60, max 10080 = 1 week)",
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=5000,
        description="Maximum number of data points to return",
    ),
) -> HistoryResponse:
    readings = db.query_history(
        device_id     = device_id,
        range_minutes = range_minutes,
        limit         = limit,
    )
    return HistoryResponse(
        device_id = device_id or "all",
        count     = len(readings),
        readings  = readings,
    )


@router.get(
    "/devices",
    response_model=DevicesResponse,
    summary="List known devices",
    description="Returns summary information for all devices seen in the last 24 hours.",
)
async def get_devices() -> DevicesResponse:
    devices = db.query_devices()
    return DevicesResponse(
        total   = len(devices),
        devices = devices,
    )
