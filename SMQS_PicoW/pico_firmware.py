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

# ───────── WIFI CONFIG ─────────
WIFI_SSID     = "Redmi_12"
WIFI_PASSWORD = "ROBOT697"

SERVER_IP   = "10.181.177.239"   # CHANGE IF NEEDED
SERVER_PORT = 5000
SERVER_URL  = f"http://{SERVER_IP}:{SERVER_PORT}/data"

SEND_INTERVAL_SEC = 5
ADC_SAMPLES = 10

# ───────── PINS ─────────
adc_mq135    = machine.ADC(machine.Pin(26))
adc_moisture = machine.ADC(machine.Pin(27))
adc_ph       = machine.ADC(machine.Pin(28))

# DHT22 on GPIO2 (as per your wiring)
dht_sensor = dht.DHT22(machine.Pin(2))

# ───────── CALIBRATION ─────────
MOISTURE_DRY_RAW = 52000
MOISTURE_WET_RAW = 20000

PH_OFFSET = 7.0
PH_SCALE  = 3.5

MQ135_MIN_RAW = 10000
MQ135_MAX_RAW = 30000
MQ135_MIN_PPM = 400
MQ135_MAX_PPM = 5000

previous_gas_ppm  = None
previous_gas_time = None


# ───────── HELPERS ─────────
def read_adc_average(adc, samples=ADC_SAMPLES):
    vals = []
    for _ in range(samples):
        vals.append(adc.read_u16())
        time.sleep_us(200)

    vals.sort()
    trim = max(1, samples // 10)
    vals = vals[trim:-trim]

    return sum(vals) / len(vals)


# ───────── SENSOR FUNCTIONS ─────────
def read_moisture():
    raw = read_adc_average(adc_moisture)
    raw = max(MOISTURE_WET_RAW, min(MOISTURE_DRY_RAW, raw))
    pct = (MOISTURE_DRY_RAW - raw) / (MOISTURE_DRY_RAW - MOISTURE_WET_RAW) * 100
    return round(pct, 1)


def read_ph():
    raw = read_adc_average(adc_ph)
    voltage = (raw / 65535) * 3.3
    ph = PH_OFFSET - PH_SCALE * (voltage - 1.65)
    return round(max(0, min(14, ph)), 2)


def read_gas():
    raw = read_adc_average(adc_mq135)
    raw = max(MQ135_MIN_RAW, min(MQ135_MAX_RAW, raw))
    ppm = MQ135_MIN_PPM + (raw - MQ135_MIN_RAW) / (MQ135_MAX_RAW - MQ135_MIN_RAW) * (MQ135_MAX_PPM - MQ135_MIN_PPM)
    return round(ppm, 1)


def read_dht():
    try:
        dht_sensor.measure()
        return dht_sensor.temperature(), dht_sensor.humidity()
    except:
        return None, None


# ───────── GAS RATE ─────────
def compute_gas_rate(current):
    global previous_gas_ppm, previous_gas_time

    now = time.time()

    if previous_gas_ppm is None:
        previous_gas_ppm = current
        previous_gas_time = now
        return 0.0

    dt = now - previous_gas_time
    if dt <= 0:
        return 0.0

    rate = (current - previous_gas_ppm) / dt

    previous_gas_ppm = current
    previous_gas_time = now

    return round(rate, 3)


# ───────── ACTIVITY ─────────
def classify(rate, moisture, temp):
    score = 0

    if rate > 0.5: score += 2
    elif rate > 0.1: score += 1

    if 40 <= moisture <= 70: score += 2
    elif 25 <= moisture <= 80: score += 1

    if temp and 15 <= temp <= 30: score += 2

    if score >= 5: return "HIGH"
    if score >= 3: return "MEDIUM"
    return "LOW"


# ───────── WIFI ─────────
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        print("Connected:", wlan.ifconfig())
        return wlan

    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    for _ in range(20):
        if wlan.isconnected():
            print("Connected:", wlan.ifconfig())
            return wlan
        time.sleep(1)

    return wlan


# ───────── SEND ─────────
def send(payload):
    try:
        r = urequests.post(SERVER_URL, data=ujson.dumps(payload), headers={"Content-Type": "application/json"})
        print("Sent:", r.status_code)
        r.close()
    except Exception as e:
        print("HTTP ERROR:", e)


# ───────── MAIN LOOP ─────────
def main():
    wlan = connect_wifi()

    while True:
        moisture = read_moisture()
        temp, humidity = read_dht()
        gas = read_gas()
        rate = compute_gas_rate(gas)
        ph = read_ph()

        activity = classify(rate, moisture, temp)

        payload = {
            "moisture": moisture,
            "soil_temp": temp,
            "humidity": humidity,
            "ph": ph,
            "gas_ppm": gas,
            "gas_rate": rate,
            "activity": activity
        }

        print(payload)

        if wlan.isconnected():
            send(payload)
        else:
            wlan = connect_wifi()

        time.sleep(SEND_INTERVAL_SEC)


main()

