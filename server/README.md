# IoT Telemetry System

A production-grade IoT monitoring stack covering the complete data pipeline from embedded hardware to a real-time web dashboard.

```
Sensor MCU
   │  UART 115200 baud
   ▼
ESP8266 WiFi Gateway  ──WiFi──►  Mosquitto MQTT Broker
                                          │
                                   iot/sensors/data
                                          │
                                          ▼
                               Python FastAPI Backend
                                  (paho-mqtt subscriber)
                                          │
                                          ▼
                                InfluxDB 2.x  (time-series)
                                          │
                                   REST API /api/*
                                          │
                                          ▼
                                  Web Dashboard
                              (Chart.js · auto-refresh 3s)
```

---

## Project Structure

```
interface
       |-- files
              |--frontend
                     |--app.js
                     |--index.html
                     |--style.css
              |--mosquito
                     |--mosquitto.conf
                     |--passwd
              |--database.py
              |--main.py
              |--model.py
              |--mqtt_cilent.py
              |--sensors.py
              |--nginx.conf
              |--Dockerfile
              |--docker-compose.yml

```

---

---

## Installation & Running

### 1. Clone / place project files

```bash
git clone <your-repo>
cd iot-telemetry
```

### 2. Generate MQTT password file

This only needs to be done once. It creates a hashed credentials file for the Mosquitto broker.

```bash
chmod +x generate_mqtt_passwd.sh
./generate_mqtt_passwd.sh
```

> **Security**: Change the default passwords in `generate_mqtt_passwd.sh` before running in any non-local environment.

### 3. Start all Docker services

```bash
docker compose up -d
```

Services started:

| Service | Port | URL |
|---------|------|-----|
| Mosquitto (MQTT) | 1883 | `mqtt://localhost:1883` |
| Mosquitto (WebSocket) | 9001 | `ws://localhost:9001` |
| InfluxDB | 8086 | http://localhost:8086 |
| FastAPI backend | 8000 | http://localhost:8000 |
| Dashboard (nginx) | 3000 | **http://localhost:3000** |

### 4. Verify services

```bash
# Check all containers are running
docker compose ps

# Tail backend logs (shows MQTT messages + DB writes)
docker compose logs -f backend

# Check API health
curl http://localhost:8000/health
```

### 5. Open the dashboard

Navigate to **http://localhost:3000** in your browser.

---

## Flashing the ESP8266 Firmware

### Required Arduino Libraries

Install via Arduino Library Manager (Sketch → Include Library → Manage Libraries):

| Library | Author | Version |
|---------|--------|---------|
| `PubSubClient` | Nick O'Leary | ≥ 2.8 |
| `ArduinoJson` | Benoit Blanchon | ≥ 6.21 |
| `NTPClient` | Arduino | ≥ 3.2 |

The ESP8266 Arduino core must be installed. Add this URL to Board Manager URLs:
```
http://arduino.esp8266.com/stable/package_esp8266com_index.json
```
Then install: **esp8266 by ESP8266 Community** via Board Manager.

### Configure before flashing

Open `firmware/esp8266_gateway.ino` and edit the `Config` namespace:

```cpp
namespace Config {
  const char* WIFI_SSID     = "YOUR_WIFI_SSID";      
  const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";  

  const char* MQTT_HOST     = "10.227.3.222";      
  const char* MQTT_USER     = "iot_user";
  const char* MQTT_PASS     = "iot_password";

  const char* DEVICE_ID     = "stm32_gateway_01";  
}
```

### Flash steps

1. Select board: **Tools → Board → ESP8266 Boards → NodeMCU 1.0 (ESP-12E Module)** (or your specific module)
2. Set CPU Frequency: **80 MHz**
3. Select the correct COM port
4. Click **Upload**

### Wiring (ESP8266 ↔ Sensor MCU)

```
Sensor MCU TX  ──►  ESP8266 RX (GPIO3)
Sensor MCU RX  ──►  ESP8266 TX (GPIO1)   [optional, for commands]
Sensor MCU GND ──►  ESP8266 GND
```

### UART message format

The sensor MCU must output lines in this exact format at 115200 baud:

```
A0:512 A1:300 A2:1024 A3:750 A4:200\n
```

Values are validated against safe ranges:
- `TEMP`: −40 … +85 °C
- `HUM`: 0 … 100 %
- `LIGHT`: 0 … 65535 (raw ADC)

---

## API Reference

Base URL: `http://localhost:8000`

### `GET /api/latest`

Returns the most recent sensor reading for each device.

**Query parameters:**
- `device_id` (optional) — filter to a specific device

**Example:**
```bash
curl http://localhost:8000/api/latest
curl http://localhost:8000/api/latest?device_id=stm32_gateway_01
```

---

### `GET /api/history`

Returns time-series readings.

**Query parameters:**
- `device_id` (optional)
- `range_minutes` (default 60, max 10080)
- `limit` (default 500, max 5000)

**Example:**
```bash
curl "http://localhost:8000/api/history?range_minutes=30&limit=200"
```

---

### `GET /api/devices`

Returns summary of all devices seen in the last 24 hours.

---

### `GET /health`

Returns service health status including MQTT and InfluxDB connectivity.

---

## InfluxDB UI

Access the InfluxDB web UI at **http://localhost:8086**

Login credentials (set in `docker-compose.yml`):
- Username: `iot_admin`
- Password: `iot_admin_password`
- Organisation: `iot_org`
- Bucket: `sensor_data`

You can use the Data Explorer to write custom Flux queries against your sensor data.

---

## Security Notes

| Layer | Mechanism |
|-------|-----------|
| MQTT broker | Username/password auth + ACL per-user topic permissions |
| Backend | Pydantic input validation; device_id regex whitelist |
| API | Input bounds checking on all query parameters |
| JSON | Safe parsing with exception handling throughout |
| CORS | Configurable via `CORS_ORIGINS` env var |

### Production hardening checklist

- [ ] Change all default passwords in `generate_mqtt_passwd.sh` and `docker-compose.yml`
- [ ] Enable TLS on MQTT (add `tls_set()` in firmware and broker cert config)
- [ ] Set `CORS_ORIGINS` to your frontend's specific domain
- [ ] Place backend behind a reverse proxy (e.g. nginx with HTTPS)
- [ ] Rotate the InfluxDB admin token
- [ ] Set up log rotation for Mosquitto

---

## Stopping Services

```bash
# Stop all containers (data preserved)
docker compose down

# Stop and remove all data volumes
docker compose down -v
```

---

## Troubleshooting

**ESP8266 won't connect to MQTT**
- Verify `MQTT_HOST` is the LAN IP of your Docker host (not `localhost`)
- Ensure port 1883 is reachable: `telnet <host> 1883`
- Check MQTT credentials match `generate_mqtt_passwd.sh`

**No data appearing in dashboard**
- Check backend logs: `docker compose logs backend`
- Verify MQTT is receiving messages: `docker compose logs mosquitto`
- Confirm InfluxDB health: `curl http://localhost:8086/health`

**Chart.js not rendering**
- The dashboard requires an internet connection to load Chart.js from CDN
- For offline use, download Chart.js and serve locally

**InfluxDB write errors**
- Token mismatch — ensure `INFLUXDB_TOKEN` in `docker-compose.yml` matches everywhere
- Check bucket name matches `INFLUXDB_BUCKET`
