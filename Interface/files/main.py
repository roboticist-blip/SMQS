"""
main.py — FastAPI application entrypoint.

Starts the MQTT subscriber and InfluxDB connection on startup,
registers API routes, and exposes a health check.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import db
from models import HealthResponse
from mqtt_client import mqtt_service
from routes.sensors import router as sensors_router

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

APP_START_TIME = time.time()


# ─────────────────────────────────────────────
# Lifespan (startup / shutdown)
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup:
      1. Connect to InfluxDB
      2. Start MQTT subscriber thread

    Runs on shutdown:
      1. Stop MQTT subscriber
      2. Close InfluxDB connection
    """
    logger.info("── IoT Backend starting ──")

    # InfluxDB
    try:
        db.connect()
    except Exception as exc:
        logger.error("InfluxDB startup error: %s — continuing without DB", exc)

    # MQTT
    try:
        mqtt_service.start()
    except Exception as exc:
        logger.error("MQTT startup error: %s", exc)

    logger.info("── IoT Backend ready ──")
    yield

    # Shutdown
    logger.info("── IoT Backend shutting down ──")
    mqtt_service.stop()
    db.close()


# ─────────────────────────────────────────────
# App
# ─────────────────────────────────────────────

app = FastAPI(
    title       = "IoT Telemetry API",
    description = "Real-time sensor data ingestion and query service",
    version     = "1.0.0",
    lifespan    = lifespan,
)

# CORS — restrict origins in production
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ALLOWED_ORIGINS,
    allow_methods     = ["GET", "OPTIONS"],
    allow_headers     = ["*"],
    allow_credentials = False,
)

# Routes
app.include_router(sensors_router)


# ─────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Service health check",
)
async def health() -> HealthResponse:
    return HealthResponse(
        status              = "ok",
        mqtt_connected      = mqtt_service.is_connected,
        influxdb_connected  = db.is_connected(),
        uptime_seconds      = round(time.time() - APP_START_TIME, 1),
    )


@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse({"service": "IoT Telemetry API", "docs": "/docs"})


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host    = "0.0.0.0",
        port    = int(os.getenv("PORT", "8000")),
        reload  = False,
        workers = 1,         # single worker — MQTT thread is shared state
    )
