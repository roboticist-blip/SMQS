"""
=============================================================
 SOIL MICROBIAL ACTIVITY MONITOR - Raspberry Pi Pico W
 Firmware written in MicroPython
=============================================================
 WIRING SUMMARY:
   ADC0 (GPIO26) → MQ135 gas sensor (via voltage divider)
   ADC1 (GPIO27) → Soil moisture sensor (analog)
   ADC2 (GPIO28) → pH sensor (via LM358 op-amp buffer)
   GPIO2         → DS18B20 soil temperature (4.7k pull-up to 3.3V)
   GPIO3         → DHT22 chamber temp + humidity
=============================================================
"""

import machine
import time
import network
import urequests
import ujson
import dht
import onewire
import ds18x20

# ─────────────────────────────────────────────
#  WIFI CONFIGURATION  (change these!)
# ─────────────────────────────────────────────
WIFI_SSID     = "Redmi 12 5G"
WIFI_PASSWORD = "ROBOT697"

# Server address — IP of the machine running server.py
SERVER_IP     = "10.195.40.239"
SERVER_PORT   = 5000
SERVER_URL    = f"http://{SERVER_IP}:{SERVER_PORT}/data"

# ─────────────────────────────────────────────
#  TIMING CONFIGURATION
# ─────────────────────────────────────────────
SEND_INTERVAL_SEC  = 12     # How often to send data (seconds)
ADC_SAMPLES        = 50     # Number of ADC samples to average

# ─────────────────────────────────────────────
#  SENSOR PIN SETUP
# ─────────────────────────────────────────────
adc_mq135    = machine.ADC(machine.Pin(26))   # MQ135 gas sensor
adc_moisture = machine.ADC(machine.Pin(27))   # Soil moisture
adc_ph       = machine.ADC(machine.Pin(28))   # pH sensor

# DS18B20 — soil temperature (OneWire on GPIO2)
ow_pin    = machine.Pin(2)
ow_bus    = onewire.OneWire(ow_pin)
ds_sensor = ds18x20.DS18X20(ow_bus)
ds_roms   = ds_sensor.scan()                  # Find all connected DS18B20 devices

# DHT22 — chamber temperature & humidity (GPIO3)
dht_sensor = dht.DHT22(machine.Pin(3))

# ─────────────────────────────────────────────
#  CALIBRATION CONSTANTS  (tune per hardware)
# ─────────────────────────────────────────────
# Moisture: map raw ADC (0–65535) to dry/wet voltages
MOISTURE_DRY_RAW = 52000    # Raw ADC value in dry air
MOISTURE_WET_RAW = 20000    # Raw ADC value in water

# pH: the LM358 buffer output maps ~0–3.3V to pH 0–14
# Adjust PH_OFFSET and PH_SCALE after calibration with buffer solutions
PH_OFFSET = 7.0             # pH at midpoint voltage (1.65 V)
PH_SCALE  = 3.5             # pH units per volt deviation from midpoint

# MQ135: raw ADC mapped to a CO2-proxy ppm range
MQ135_MIN_RAW = 5000        # Minimum expected raw value (clean air)
MQ135_MAX_RAW = 50000       # Maximum expected raw value (high CO2 proxy)
MQ135_MIN_PPM = 400         # Corresponding minimum ppm
MQ135_MAX_PPM = 5000        # Corresponding maximum ppm

# ─────────────────────────────────────────────
#  STATE — used for gas accumulation rate
# ─────────────────────────────────────────────
previous_gas_ppm  = None
previous_gas_time = None


# ═════════════════════════════════════════════
#  HELPER — read ADC with averaging & filtering
# ═════════════════════════════════════════════
def read_adc_average(adc_pin, samples=ADC_SAMPLES):
    """
    Read an ADC pin 'samples' times, discard the top and bottom 10 %,
    then return the mean of the remaining values (trimmed mean).
    This removes spikes and noise effectively.
    """
    readings = []
    for _ in range(samples):
        readings.append(adc_pin.read_u16())
        time.sleep_us(500)          # Small delay between samples

    readings.sort()

    # Trim 10 % from each end
    trim = max(1, samples // 10)
    trimmed = readings[trim : samples - trim]

    return sum(trimmed) / len(trimmed)


# ═════════════════════════════════════════════
#  SENSOR READERS
# ═════════════════════════════════════════════
def read_moisture_percent():
    """
    Analog soil moisture: lower raw value → wetter soil.
    Maps raw ADC range to 0–100 %.
    """
    raw = read_adc_average(adc_moisture)
    # Clamp to calibrated range
    raw = max(MOISTURE_WET_RAW, min(MOISTURE_DRY_RAW, raw))
    percent = (MOISTURE_DRY_RAW - raw) / (MOISTURE_DRY_RAW - MOISTURE_WET_RAW) * 100.0
    return round(percent, 1)


def read_ph():
    """
    pH sensor via LM358 buffer.
    The op-amp outputs a voltage proportional to the H+ ion activity.
    We convert the ADC reading to a voltage then to pH.
    """
    raw = read_adc_average(adc_ph)
    voltage = (raw / 65535.0) * 3.3        # 12-bit ADC, 3.3V ref
    midpoint_voltage = 3.3 / 2.0           # 1.65 V = neutral pH 7
    ph = PH_OFFSET - PH_SCALE * (voltage - midpoint_voltage)
    ph = max(0.0, min(14.0, ph))           # Clamp to valid pH range
    return round(ph, 2)


def read_mq135_ppm():
    """
    MQ135 gas sensor: outputs higher voltage (higher raw) for higher CO2 proxy.
    We do a simple linear interpolation from raw to ppm.
    """
    raw = read_adc_average(adc_mq135)
    raw = max(MQ135_MIN_RAW, min(MQ135_MAX_RAW, raw))
    ppm = MQ135_MIN_PPM + (raw - MQ135_MIN_RAW) / (MQ135_MAX_RAW - MQ135_MIN_RAW) * (MQ135_MAX_PPM - MQ135_MIN_PPM)
    return round(ppm, 1)


def read_soil_temperature():
    """
    DS18B20 digital temperature sensor on OneWire bus.
    Returns temperature in °C.
    """
    if not ds_roms:
        print("WARNING: No DS18B20 found on GPIO2")
        return None
    try:
        ds_sensor.convert_temp()
        time.sleep_ms(750)          # DS18B20 needs ~750 ms for conversion
        temp = ds_sensor.read_temp(ds_roms[0])
        return round(temp, 1)
    except Exception as e:
        print("DS18B20 read error:", e)
        return None


def read_dht22():
    """
    DHT22: returns (temperature_C, humidity_%) inside the gas chamber.
    """
    try:
        dht_sensor.measure()
        temp = dht_sensor.temperature()
        hum  = dht_sensor.humidity()
        return round(temp, 1), round(hum, 1)
    except Exception as e:
        print("DHT22 read error:", e)
        return None, None


# ═════════════════════════════════════════════
#  GAS ACCUMULATION RATE
# ═════════════════════════════════════════════
def compute_gas_rate(current_ppm):
    """
    gas_rate = (current_gas - previous_gas) / time_elapsed_seconds
    Returns ppm/second. Positive = CO2 is rising (microbial activity).
    """
    global previous_gas_ppm, previous_gas_time

    now = time.time()
    if previous_gas_ppm is None or previous_gas_time is None:
        previous_gas_ppm  = current_ppm
        previous_gas_time = now
        return 0.0

    elapsed = now - previous_gas_time
    if elapsed <= 0:
        return 0.0

    rate = (current_ppm - previous_gas_ppm) / elapsed

    # Update state
    previous_gas_ppm  = current_ppm
    previous_gas_time = now

    return round(rate, 4)


# ═════════════════════════════════════════════
#  MICROBIAL ACTIVITY CLASSIFIER
# ═════════════════════════════════════════════
def classify_activity(gas_rate, moisture_pct, soil_temp_c):
    """
    Simple rule-based classifier for microbial activity level.

    Optimal conditions for soil microbes:
      - Moisture: 40–70 %
      - Soil temperature: 15–30 °C
      - Rising CO2 (positive gas_rate)

    Returns: "HIGH", "MEDIUM", or "LOW"
    """
    # Score each parameter (0 = poor, 1 = ok, 2 = optimal)
    score = 0

    # Gas rate contribution
    if gas_rate > 0.5:
        score += 2
    elif gas_rate > 0.1:
        score += 1

    # Moisture contribution
    if 40 <= moisture_pct <= 70:
        score += 2
    elif 25 <= moisture_pct < 40 or 70 < moisture_pct <= 80:
        score += 1

    # Temperature contribution (if available)
    if soil_temp_c is not None:
        if 15 <= soil_temp_c <= 30:
            score += 2
        elif 10 <= soil_temp_c < 15 or 30 < soil_temp_c <= 38:
            score += 1

    # Map total score to activity level
    if score >= 5:
        return "HIGH"
    elif score >= 3:
        return "MEDIUM"
    else:
        return "LOW"


# ═════════════════════════════════════════════
#  WIFI CONNECTION
# ═════════════════════════════════════════════
def connect_wifi():
    """Connect to WiFi. Blocks until connected or 20 attempts exhausted."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        print("Already connected:", wlan.ifconfig())
        return wlan

    print(f"Connecting to WiFi '{WIFI_SSID}' ...")
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    for attempt in range(20):
        if wlan.isconnected():
            print("WiFi connected! IP:", wlan.ifconfig()[0])
            return wlan
        time.sleep(1)
        print(f"  Attempt {attempt + 1}/20 ...")

    print("ERROR: Could not connect to WiFi after 20 attempts.")
    return wlan


# ═════════════════════════════════════════════
#  SEND DATA TO SERVER
# ═════════════════════════════════════════════
def send_data(payload_dict):
    """
    HTTP POST JSON payload to the server endpoint.
    Returns True on success, False on failure.
    """
    try:
        json_str = ujson.dumps(payload_dict)
        headers  = {"Content-Type": "application/json"}
        response = urequests.post(SERVER_URL, data=json_str, headers=headers)
        print(f"Server response: {response.status_code}")
        response.close()
        return True
    except Exception as e:
        print("HTTP POST error:", e)
        return False


# ═════════════════════════════════════════════
#  MAIN LOOP
# ═════════════════════════════════════════════
def main():
    print("=" * 50)
    print(" Soil Microbial Activity Monitor — Starting")
    print("=" * 50)

    # Connect to WiFi
    wlan = connect_wifi()

    while True:
        loop_start = time.time()
        print("\n--- Reading sensors ---")

        # 1. Read all sensors
        moisture_pct             = read_moisture_percent()
        soil_temp_c              = read_soil_temperature()
        chamber_temp_c, hum_pct  = read_dht22()
        gas_ppm                  = read_mq135_ppm()
        ph_value                 = read_ph()

        # 2. Compute gas accumulation rate
        gas_rate = compute_gas_rate(gas_ppm)

        # 3. Classify microbial activity
        activity = classify_activity(gas_rate, moisture_pct, soil_temp_c)

        # 4. Print to console for debugging
        print(f"  Soil Moisture  : {moisture_pct} %")
        print(f"  Soil Temp      : {soil_temp_c} °C")
        print(f"  Chamber Humidity: {hum_pct} %")
        print(f"  Chamber Temp   : {chamber_temp_c} °C")
        print(f"  pH             : {ph_value}")
        print(f"  Gas (CO2 proxy): {gas_ppm} ppm")
        print(f"  Gas Rate       : {gas_rate} ppm/s")
        print(f"  Activity       : {activity}")

        # 5. Build JSON payload
        payload = {
            "moisture"   : moisture_pct,
            "soil_temp"  : soil_temp_c,
            "humidity"   : hum_pct,
            "ph"         : ph_value,
            "gas_ppm"    : gas_ppm,
            "gas_rate"   : gas_rate,
            "activity"   : activity
        }

        # 6. Send to server (reconnect WiFi if dropped)
        if not wlan.isconnected():
            print("WiFi dropped — reconnecting ...")
            wlan = connect_wifi()

        if wlan.isconnected():
            send_data(payload)
        else:
            print("Skipping send — no WiFi connection.")

        # 7. Wait until next cycle
        elapsed  = time.time() - loop_start
        sleep_ms = max(0, int((SEND_INTERVAL_SEC - elapsed) * 1000))
        print(f"  (Next reading in {sleep_ms // 1000} s)")
        time.sleep_ms(sleep_ms)


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    main()
