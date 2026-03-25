"""
=============================================================
 SOIL MICROBIAL ACTIVITY MONITOR - Raspberry Pi Pico W
 Firmware written in MicroPython
=============================================================
 WIRING SUMMARY:
   ADC0 (GPIO26) → MQ135 gas sensor (via voltage divider)
   ADC1 (GPIO27) → Soil moisture sensor (analog)
   ADC2 (GPIO28) → pH sensor (via LM358 op-amp buffer)
   ADC3 (GPIO29) → NTC Thermistor (voltage divider with R_REF)
   GPIO3         → DHT22 chamber temp + humidity
=============================================================
"""

import machine
import time
import network
import urequests
import ujson
import dht
import math

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
adc_mq135      = machine.ADC(machine.Pin(26))   # MQ135 gas sensor
adc_moisture   = machine.ADC(machine.Pin(27))   # Soil moisture
adc_ph         = machine.ADC(machine.Pin(28))   # pH sensor
adc_thermistor = machine.ADC(machine.Pin(29))   # NTC Thermistor

# DHT22 — chamber temperature & humidity (GPIO3)
dht_sensor = dht.DHT22(machine.Pin(3))

# ─────────────────────────────────────────────
#  CALIBRATION CONSTANTS  (tune per hardware)
# ─────────────────────────────────────────────
# Moisture: map raw ADC (0–65535) to dry/wet voltages
MOISTURE_DRY_RAW = 52000    # Raw ADC value in dry air
MOISTURE_WET_RAW = 20000    # Raw ADC value in water

# pH: the LM358 buffer output maps ~0–3.3V to pH 0–14
PH_OFFSET = 7.0             # pH at midpoint voltage (1.65 V)
PH_SCALE  = 3.5             # pH units per volt deviation from midpoint

# MQ135: raw ADC mapped to a CO2-proxy ppm range
MQ135_MIN_RAW = 5000
MQ135_MAX_RAW = 50000
MQ135_MIN_PPM = 400
MQ135_MAX_PPM = 5000

# ─────────────────────────────────────────────
#  THERMISTOR CONSTANTS (Steinhart-Hart / Beta)
# ─────────────────────────────────────────────
# Change these to match your specific thermistor's datasheet
THERMISTOR_R_REF    = 10000   # Reference resistor in voltage divider (Ohms) — e.g. 10kΩ
THERMISTOR_R_NOM    = 10000   # Thermistor nominal resistance at 25°C (Ohms) — e.g. 10kΩ
THERMISTOR_BETA     = 3950    # Beta coefficient — check datasheet (common: 3380–3950)
THERMISTOR_T_NOM    = 25.0    # Nominal temperature for R_NOM in °C
THERMISTOR_VCC      = 3.3     # Supply voltage (Pico runs at 3.3V)
# Wiring: 3.3V → R_REF → GPIO29/ADC3 → Thermistor → GND
# (thermistor is the lower leg of the divider)

# ─────────────────────────────────────────────
#  STATE — used for gas accumulation rate
# ─────────────────────────────────────────────
previous_gas_ppm  = None
previous_gas_time = None


# ═════════════════════════════════════════════
#  HELPER — read ADC with averaging & filtering
# ═════════════════════════════════════════════
def read_adc_average(adc_pin, samples=ADC_SAMPLES):
    readings = []
    for _ in range(samples):
        readings.append(adc_pin.read_u16())
        time.sleep_us(500)

    readings.sort()
    trim    = max(1, samples // 10)
    trimmed = readings[trim : samples - trim]
    return sum(trimmed) / len(trimmed)


# ═════════════════════════════════════════════
#  SENSOR READERS
# ═════════════════════════════════════════════
def read_moisture_percent():
    raw = read_adc_average(adc_moisture)
    raw = max(MOISTURE_WET_RAW, min(MOISTURE_DRY_RAW, raw))
    percent = (MOISTURE_DRY_RAW - raw) / (MOISTURE_DRY_RAW - MOISTURE_WET_RAW) * 100.0
    return round(percent, 1)


def read_ph():
    raw     = read_adc_average(adc_ph)
    voltage = (raw / 65535.0) * 3.3
    midpoint_voltage = 3.3 / 2.0
    ph = PH_OFFSET - PH_SCALE * (voltage - midpoint_voltage)
    ph = max(0.0, min(14.0, ph))
    return round(ph, 2)


def read_mq135_ppm():
    raw = read_adc_average(adc_mq135)
    raw = max(MQ135_MIN_RAW, min(MQ135_MAX_RAW, raw))
    ppm = MQ135_MIN_PPM + (raw - MQ135_MIN_RAW) / (MQ135_MAX_RAW - MQ135_MIN_RAW) * (MQ135_MAX_PPM - MQ135_MIN_PPM)
    return round(ppm, 1)


def read_soil_temperature():
    """
    NTC Thermistor via voltage divider on ADC3 (GPIO29).
    Uses the Beta equation to convert resistance → temperature.

    Circuit:  3.3V ── R_REF ──┬── Thermistor ── GND
                               └── ADC3
    """
    try:
        raw     = read_adc_average(adc_thermistor)
        voltage = (raw / 65535.0) * THERMISTOR_VCC

        # Guard against divide-by-zero at rail voltages
        if voltage <= 0 or voltage >= THERMISTOR_VCC:
            print("WARNING: Thermistor voltage out of range:", voltage)
            return None

        # Compute thermistor resistance from voltage divider
        # V_adc = VCC * R_therm / (R_REF + R_therm)
        # → R_therm = R_REF * V_adc / (VCC - V_adc)
        r_therm = THERMISTOR_R_REF * voltage / (THERMISTOR_VCC - voltage)

        # Beta equation: 1/T = 1/T0 + (1/B) * ln(R/R0)
        t_nom_k = THERMISTOR_T_NOM + 273.15
        temp_k  = 1.0 / (1.0 / t_nom_k + math.log(r_therm / THERMISTOR_R_NOM) / THERMISTOR_BETA)
        temp_c  = temp_k - 273.15

        return round(temp_c, 1)

    except Exception as e:
        print("Thermistor read error:", e)
        return None


def read_dht22():
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
    previous_gas_ppm  = current_ppm
    previous_gas_time = now
    return round(rate, 4)


# ═════════════════════════════════════════════
#  MICROBIAL ACTIVITY CLASSIFIER
# ═════════════════════════════════════════════
def classify_activity(gas_rate, moisture_pct, soil_temp_c):
    score = 0

    if gas_rate > 0.5:
        score += 2
    elif gas_rate > 0.1:
        score += 1

    if 40 <= moisture_pct <= 70:
        score += 2
    elif 25 <= moisture_pct < 40 or 70 < moisture_pct <= 80:
        score += 1

    if soil_temp_c is not None:
        if 15 <= soil_temp_c <= 30:
            score += 2
        elif 10 <= soil_temp_c < 15 or 30 < soil_temp_c <= 38:
            score += 1

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

    wlan = connect_wifi()

    while True:
        loop_start = time.time()
        print("\n--- Reading sensors ---")

        moisture_pct            = read_moisture_percent()
        soil_temp_c             = read_soil_temperature()
        chamber_temp_c, hum_pct = read_dht22()
        gas_ppm                 = read_mq135_ppm()
        ph_value                = read_ph()

        gas_rate = compute_gas_rate(gas_ppm)
        activity = classify_activity(gas_rate, moisture_pct, soil_temp_c)

        print(f"  Soil Moisture   : {moisture_pct} %")
        print(f"  Soil Temp       : {soil_temp_c} °C")
        print(f"  Chamber Humidity: {hum_pct} %")
        print(f"  Chamber Temp    : {chamber_temp_c} °C")
        print(f"  pH              : {ph_value}")
        print(f"  Gas (CO2 proxy) : {gas_ppm} ppm")
        print(f"  Gas Rate        : {gas_rate} ppm/s")
        print(f"  Activity        : {activity}")

        payload = {
            "moisture"  : moisture_pct,
            "soil_temp" : soil_temp_c,
            "humidity"  : hum_pct,
            "ph"        : ph_value,
            "gas_ppm"   : gas_ppm,
            "gas_rate"  : gas_rate,
            "activity"  : activity
        }

        if not wlan.isconnected():
            print("WiFi dropped — reconnecting ...")
            wlan = connect_wifi()

        if wlan.isconnected():
            send_data(payload)
        else:
            print("Skipping send — no WiFi connection.")

        elapsed  = time.time() - loop_start
        sleep_ms = max(0, int((SEND_INTERVAL_SEC - elapsed) * 1000))
        print(f"  (Next reading in {sleep_ms // 1000} s)")
        time.sleep_ms(sleep_ms)


if __name__ == "__main__":
    main()
