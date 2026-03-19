# 🌱 Soil Microbial Activity Monitor — Complete Setup Guide

---

## 📁 File Overview

| File | Purpose |
|------|---------|
| `pico_firmware.py` | MicroPython code for Raspberry Pi Pico W |
| `server.py` | Python Flask backend server |
| `dashboard.html` | Web dashboard (served by Flask automatically) |
| `README.md` | This guide |

---

## 🔌 WIRING DIAGRAM

```
Raspberry Pi Pico W
────────────────────────────────────────────────────────

GPIO26 (ADC0) ──────────────── MQ135 AOUT
                              (via voltage divider: 10kΩ from AOUT to GPIO26,
                               10kΩ from GPIO26 to GND — keeps voltage ≤3.3V)

GPIO27 (ADC1) ──────────────── Soil Moisture Sensor AOUT

GPIO28 (ADC2) ──────────────── LM358 output pin (pH sensor buffer)
                              pH probe (Al + Cu) → LM358 non-inverting input
                              LM358 VCC → 3.3V,  GND → GND

GPIO2  (OneWire) ───────────── DS18B20 DATA pin
                              4.7kΩ resistor between DATA and 3.3V (pull-up)

GPIO3  ─────────────────────── DHT22 DATA pin
                              10kΩ resistor between DATA and 3.3V (pull-up)

3.3V ───────────────────────── VCC for: DS18B20, DHT22, Soil sensor, LM358
VBUS (5V) ──────────────────── VCC for: MQ135 heater circuit

GND ────────────────────────── GND for all sensors
```

### MQ135 Voltage Divider (IMPORTANT)
The MQ135 AOUT can go up to 5V. Pico W ADC max is 3.3V.
Build this voltage divider between AOUT and GPIO26:

```
AOUT ──── 10kΩ ──── GPIO26 ──── 10kΩ ──── GND
```

This halves the voltage: 5V → 2.5V (safe for Pico W).

---

## ⚙️ PART 1 — Setting Up the Pico W Firmware

### Step 1: Install MicroPython on Pico W
1. Download the latest MicroPython UF2 for Pico W from:
   https://micropython.org/download/RPI_PICO_W/
2. Hold the BOOTSEL button on the Pico W and plug it into USB
3. It appears as a USB drive — drag the .uf2 file onto it
4. It reboots automatically into MicroPython

### Step 2: Install Thonny IDE
Download from: https://thonny.org
In Thonny: Tools → Options → Interpreter → MicroPython (Raspberry Pi Pico)

### Step 3: Install required MicroPython libraries
The following are built into MicroPython for Pico W — no install needed:
- `network`, `urequests`, `ujson`, `machine`, `time`
- `dht` (for DHT22)
- `onewire`, `ds18x20` (for DS18B20)

If `ds18x20` is not available, install via Thonny:
Tools → Manage Packages → search "ds18x20" → Install

### Step 4: Configure WiFi & Server IP
Open `pico_firmware.py` and edit these lines at the top:

```python
WIFI_SSID     = "YOUR_WIFI_SSID"       # ← Your WiFi name
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"   # ← Your WiFi password
SERVER_IP     = "192.168.1.100"        # ← IP of PC running server.py
```

To find your PC's IP address:
- Windows: Open cmd → type `ipconfig` → look for "IPv4 Address"
- Linux/Mac: Open terminal → type `hostname -I`

### Step 5: Upload firmware to Pico W
1. Open `pico_firmware.py` in Thonny
2. File → Save As → select "Raspberry Pi Pico" → name it `main.py`
3. The Pico W will auto-run `main.py` on every boot
4. Watch the Shell panel — you should see sensor readings printed

---

## ⚙️ PART 2 — Setting Up the Flask Server

### Step 1: Install Python 3 and Flask
Make sure Python 3.8+ is installed: https://python.org

```bash
pip install flask
```

### Step 2: Place files together
Put these two files in the SAME folder:
```
my_server/
  ├── server.py
  └── dashboard.html
```

### Step 3: Run the server
```bash
cd my_server
python server.py
```

You should see:
```
 * Running on http://0.0.0.0:5000
```

### Step 4: Open the dashboard
Open your browser and go to:
```
http://localhost:5000
```

Or from another device on the same network:
```
http://192.168.1.100:5000        (replace with your PC's IP)
```

---

## 🧪 PART 3 — Testing Without the Pico W

You can test the server and dashboard with a simple curl command:

### Windows (PowerShell):
```powershell
Invoke-WebRequest -Uri "http://localhost:5000/data" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"moisture":55.3,"soil_temp":22.1,"humidity":68.0,"ph":6.8,"gas_ppm":850,"gas_rate":0.34,"activity":"HIGH"}'
```

### Linux / Mac:
```bash
curl -X POST http://localhost:5000/data \
  -H "Content-Type: application/json" \
  -d '{"moisture":55.3,"soil_temp":22.1,"humidity":68.0,"ph":6.8,"gas_ppm":850,"gas_rate":0.34,"activity":"HIGH"}'
```

Then refresh http://localhost:5000 — you should see the values update!

---

## 🔧 CALIBRATION GUIDE

### Soil Moisture Sensor
1. Hold sensor in dry air → note the raw ADC value in console (e.g. 52000)
2. Dip sensor in water → note raw ADC value (e.g. 20000)
3. Update in `pico_firmware.py`:
```python
MOISTURE_DRY_RAW = 52000
MOISTURE_WET_RAW = 20000
```

### pH Sensor (Al + Cu probes)
1. Use pH 4.0 and pH 7.0 buffer solutions
2. Note the voltage output at each (print `voltage` in the `read_ph()` function)
3. Adjust `PH_OFFSET` and `PH_SCALE` to match your probe's response curve

### MQ135 (CO2 Proxy)
1. Let the sensor warm up for at least 24 hours before first use
2. The raw ADC value in clean outdoor air ≈ 5000–8000 on a 3.3V supply
3. Values above 20000 generally indicate elevated CO2 from decomposition

---

## 📊 MICROBIAL ACTIVITY SCORING LOGIC

```
Parameter         | Score 0 | Score 1       | Score 2 (Optimal)
──────────────────|─────────|───────────────|──────────────────
Gas rate (ppm/s)  | < 0.1   | 0.1 – 0.5     | > 0.5
Moisture (%)      | outside | 25–40 or 70–80| 40–70
Soil temp (°C)    | outside | 10–15 or 30–38| 15–30

Total Score → Activity:
  5–6 → HIGH
  3–4 → MEDIUM
  0–2 → LOW
```

---

## ❓ TROUBLESHOOTING

| Problem | Solution |
|---------|---------|
| Pico W can't connect to WiFi | Double-check SSID/password; ensure 2.4 GHz network |
| DS18B20 shows None | Check 4.7kΩ pull-up resistor; verify GPIO2 connection |
| DHT22 read error | Add 10kΩ pull-up; DHT22 needs >1s between reads |
| MQ135 always reads max | Check voltage divider; sensor needs 24h burn-in |
| pH reads strange values | Calibrate with buffer solutions; LM358 needs stable 3.3V |
| Server not receiving data | Confirm PC IP matches SERVER_IP in firmware; check firewall |
| Dashboard shows "--" | Server is running but no POST received yet from Pico |

---

## 🔒 FIREWALL NOTE

If the Pico W can't reach the server, allow port 5000:

**Windows:**
```
netsh advfirewall firewall add rule name="Flask" dir=in action=allow protocol=TCP localport=5000
```

**Linux (ufw):**
```bash
sudo ufw allow 5000
```

---

## 🌐 OPTIONAL: Run Server on Startup (Linux/Raspberry Pi)

Create a systemd service `/etc/systemd/system/soilmonitor.service`:

```ini
[Unit]
Description=Soil Monitor Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/my_server/server.py
WorkingDirectory=/home/pi/my_server
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable soilmonitor
sudo systemctl start soilmonitor
```
