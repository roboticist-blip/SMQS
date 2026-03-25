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

## 🔌 Wiring Diagram

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

GPIO29 (ADC3) ──────────────── NTC Thermistor (soil temperature)
                              Voltage divider circuit:
                              3.3V ── 10kΩ (R_REF) ──┬── GPIO29
                                                      └── Thermistor ── GND

GPIO3         ──────────────── DHT22 DATA pin
                              10kΩ resistor between DATA and 3.3V (pull-up)

3.3V  ──────────────────────── VCC for: DHT22, Soil sensor, LM358, R_REF leg of thermistor divider
VBUS (5V) ──────────────────── VCC for: MQ135 heater circuit
GND   ──────────────────────── GND for all sensors
```

### MQ135 Voltage Divider (IMPORTANT)

The MQ135 AOUT can go up to 5V. Pico W ADC max is 3.3V.
Build this voltage divider between AOUT and GPIO26:

```
AOUT ──── 10kΩ ──── GPIO26 ──── 10kΩ ──── GND
```

This halves the voltage: 5V → 2.5V (safe for Pico W).

### Thermistor Voltage Divider

The NTC thermistor is wired as the lower leg of a voltage divider.
Use a fixed resistor (R_REF) equal to the thermistor's nominal resistance (e.g. 10kΩ for a 10kΩ NTC):

```
3.3V ──── R_REF (10kΩ) ──── GPIO29 ──── Thermistor ──── GND
```

As soil temperature rises, thermistor resistance drops → voltage on GPIO29 rises.

---

## ⚙️ Part 1 — Setting Up the Pico W Firmware

### Step 1: Install MicroPython on Pico W

1. Download the latest MicroPython UF2 for Pico W from:
   https://micropython.org/download/RPI_PICO_W/
2. Hold the BOOTSEL button on the Pico W and plug it into USB
3. It appears as a USB drive — drag the `.uf2` file onto it
4. It reboots automatically into MicroPython

### Step 2: Install Thonny IDE

Download from: https://thonny.org

In Thonny: **Tools → Options → Interpreter → MicroPython (Raspberry Pi Pico)**

### Step 3: Required MicroPython Libraries

The following are built into MicroPython for Pico W — **no install needed**:
- `network`, `urequests`, `ujson`, `machine`, `time`, `math`
- `dht` (for DHT22)

> ℹ️ `onewire` and `ds18x20` are **no longer needed** — the thermistor is read
> directly via ADC. No extra libraries required.

### Step 4: Configure WiFi & Server IP

Open `pico_firmware.py` and edit these lines at the top:

```python
WIFI_SSID     = "YOUR_WIFI_SSID"       # ← Your WiFi name
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"   # ← Your WiFi password
SERVER_IP     = "192.168.1.100"        # ← IP of PC running server.py
```

To find your PC's IP address:
- **Windows:** Open cmd → type `ipconfig` → look for "IPv4 Address"
- **Linux/Mac:** Open terminal → type `hostname -I`

### Step 5: Configure Thermistor Constants

Match these values to your thermistor's datasheet:

```python
THERMISTOR_R_REF = 10000   # Fixed resistor value in voltage divider (Ohms)
THERMISTOR_R_NOM = 10000   # Thermistor resistance at 25°C (Ohms)
THERMISTOR_BETA  = 3950    # Beta coefficient (check datasheet, usually 3380–3950)
```

> If you don't have a datasheet, **10kΩ / 10kΩ / Beta=3950** works for most
> common NTC thermistors and will be accurate to within ~1–2°C.

### Step 6: Upload Firmware to Pico W

1. Open `pico_firmware.py` in Thonny
2. **File → Save As** → select "Raspberry Pi Pico" → name it `main.py`
3. The Pico W will auto-run `main.py` on every boot
4. Watch the Shell panel — you should see sensor readings printed

---

## ⚙️ Part 2 — Setting Up the Flask Server

### Step 1: Install Python 3 and Flask

Make sure Python 3.8+ is installed: https://python.org

```bash
pip install flask
```

### Step 2: Place Files Together

Put these two files in the **same folder**:

```
my_server/
  ├── server.py
  └── dashboard.html
```

### Step 3: Run the Server

```bash
cd my_server
python server.py
```

You should see:
```
 * Running on http://0.0.0.0:5000
```

### Step 4: Open the Dashboard

Open your browser and go to:
```
http://localhost:5000
```

Or from another device on the same network:
```
http://192.168.1.100:5000        (replace with your PC's IP)
```

---

## 🧪 Part 3 — Testing Without the Pico W

You can test the server and dashboard with a simple command:

### Windows (PowerShell)

```powershell
Invoke-WebRequest -Uri "http://localhost:5000/data" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"moisture":55.3,"soil_temp":22.1,"humidity":68.0,"ph":6.8,"gas_ppm":850,"gas_rate":0.34,"activity":"HIGH"}'
```

### Linux / Mac

```bash
curl -X POST http://localhost:5000/data \
  -H "Content-Type: application/json" \
  -d '{"moisture":55.3,"soil_temp":22.1,"humidity":68.0,"ph":6.8,"gas_ppm":850,"gas_rate":0.34,"activity":"HIGH"}'
```

Then refresh `http://localhost:5000` — you should see the values update!

---

## 🔧 Calibration Guide

### Soil Moisture Sensor

1. Hold sensor in dry air → note the raw ADC value in console (e.g. `52000`)
2. Dip sensor in water → note raw ADC value (e.g. `20000`)
3. Update in `pico_firmware.py`:

```python
MOISTURE_DRY_RAW = 52000
MOISTURE_WET_RAW = 20000
```

### pH Sensor (Al + Cu Probes)

1. Use pH 4.0 and pH 7.0 buffer solutions
2. Note the voltage output at each (print `voltage` in the `read_ph()` function)
3. Adjust `PH_OFFSET` and `PH_SCALE` to match your probe's response curve

### MQ135 (CO2 Proxy)

1. Let the sensor warm up for at least **24 hours** before first use
2. The raw ADC value in clean outdoor air ≈ 5000–8000 on a 3.3V supply
3. Values above 20000 generally indicate elevated CO2 from decomposition

### NTC Thermistor (Soil Temperature)

1. Check your thermistor's datasheet for `R_NOM`, `T_NOM`, and `Beta`
2. To verify accuracy, place the thermistor in ice water (0°C) and boiling
   water (100°C) and compare the printed readings to expected values
3. If readings are consistently off, adjust `THERMISTOR_BETA` slightly up or
   down until they match
4. Ensure the thermistor tip is fully insulated from moisture with heat-shrink
   or waterproof epoxy — water ingress into the divider circuit will cause
   incorrect ADC readings

---

## 📊 Microbial Activity Scoring Logic

| Parameter | Score 0 | Score 1 | Score 2 (Optimal) |
|-----------|---------|---------|-------------------|
| Gas rate (ppm/s) | < 0.1 | 0.1 – 0.5 | > 0.5 |
| Moisture (%) | Outside all ranges | 25–40 or 70–80 | 40–70 |
| Soil temp (°C) | Outside all ranges | 10–15 or 30–38 | 15–30 |

**Total Score → Activity Level:**
- **5–6 → HIGH**
- **3–4 → MEDIUM**
- **0–2 → LOW**

---

## ❓ Troubleshooting

| Problem | Solution |
|---------|---------|
| Pico W can't connect to WiFi | Double-check SSID/password; ensure 2.4 GHz network |
| Soil temp reads `None` | Check thermistor wiring; confirm R_REF is connected to 3.3V |
| Soil temp wildly inaccurate | Verify Beta value matches datasheet; re-check R_REF value |
| Soil temp reads ~0°C or ~150°C | Thermistor legs are swapped — flip the thermistor in the divider |
| DHT22 read error | Add 10kΩ pull-up; DHT22 needs >1s between reads |
| MQ135 always reads max | Check voltage divider; sensor needs 24h burn-in |
| pH reads strange values | Calibrate with buffer solutions; LM358 needs stable 3.3V |
| Server not receiving data | Confirm PC IP matches SERVER_IP in firmware; check firewall |
| Dashboard shows "--" | Server is running but no POST received yet from Pico |

---

## 🔒 Firewall Note

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

## 🌐 Optional: Run Server on Startup (Linux/Raspberry Pi)

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
