/**
 * ESP8266 WiFi Gateway Firmware
 * ==============================
 * Role: UART receiver → JSON encoder → MQTT publisher
 *
 * Data flow:
 *   STM32 MCU → UART 115200 baud → ESP8266 → WiFi → MQTT Broker
 *
 * STM32 transmits via:
 *   snprintf(msg, sizeof(msg), "A0:%u A1:%u A2:%u A3:%u A4:%u\r\n",
 *            adc_buffer[0], adc_buffer[1], adc_buffer[2],
 *            adc_buffer[3], adc_buffer[4]);
 *   HAL_UART_Transmit(&huart1, (uint8_t*)msg, len, 10);
 *
 * Example UART line received:
 *   A0:512 A1:300 A2:1024 A3:750 A4:200\r\n
 *
 * MQTT output (topic: iot/sensors/data):
 *   {
 *     "device_id": "stm32_gateway_01",
 *     "A0": 512,
 *     "A1": 300,
 *     "A2": 1024,
 *     "A3": 750,
 *     "A4": 200,
 *     "timestamp": 1710000000
 *   }
 *
 * ADC range: STM32 12-bit ADC → 0–4095
 *
 * Libraries required:
 *   - ESP8266WiFi    (bundled with ESP8266 Arduino core)
 *   - PubSubClient   https://github.com/knolleary/pubsubclient
 *   - ArduinoJson    https://arduinojson.org/
 *   - NTPClient      https://github.com/arduino-libraries/NTPClient
 */

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <NTPClient.h>
#include <WiFiUdp.h>


#define LED_PIN 2
// ─────────────────────────────────────────────
// Configuration — edit before flashing
// ─────────────────────────────────────────────
namespace Config {
  // WiFi
  const char* WIFI_SSID      = "Redmi 12 5G";
  const char* WIFI_PASSWORD  = "ROBOT697";

  // MQTT Broker
  const char* MQTT_HOST      = "192.168.1.100";  // LAN IP of your Docker host
  const uint16_t MQTT_PORT   = 1883;
  const char* MQTT_USER      = "iot_user";
  const char* MQTT_PASS      = "iot_password";
  const char* MQTT_CLIENT_ID = "stm32_gateway_01";
  const char* MQTT_TOPIC     = "iot/sensors/data";

  // Device identity (must match device_id pattern: [a-zA-Z0-9_-]+)
  const char* DEVICE_ID      = "stm32_gateway_01";

  // STM32 ADC: 12-bit → valid range 0–4095
  const uint16_t ADC_MAX     = 4095;

  // Timing
  const uint32_t WIFI_TIMEOUT_MS     = 20000;
  const uint32_t MQTT_RETRY_DELAY_MS = 5000;
  const uint32_t NTP_UPDATE_INTERVAL = 60000;  // 1 minute

  // UART
  const uint32_t UART_BAUD   = 115200;
  const uint16_t UART_BUF    = 128;  // "A0:4095 A1:4095 A2:4095 A3:4095 A4:4095\r\n" = ~43 chars
}

// ─────────────────────────────────────────────
// ADC sample struct
// ─────────────────────────────────────────────
struct AdcSample {
  uint16_t ch[5];   // A0 … A4
};

// ─────────────────────────────────────────────
// Globals
// ─────────────────────────────────────────────
WiFiClient    wifiClient;
PubSubClient  mqttClient(wifiClient);
WiFiUDP       ntpUDP;
NTPClient     timeClient(ntpUDP, "pool.ntp.org", 0, Config::NTP_UPDATE_INTERVAL);

String   uartBuffer    = "";
bool     uartLineReady = false;
uint32_t lastMqttRetry = 0;

// ─────────────────────────────────────────────
// WiFi helpers
// ─────────────────────────────────────────────
void connectWiFi() {
  Serial.printf("[WiFi] Connecting to %s", Config::WIFI_SSID);
  WiFi.mode(WIFI_STA); 
  WiFi.begin(Config::WIFI_SSID, Config::WIFI_PASSWORD);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > Config::WIFI_TIMEOUT_MS) {
      Serial.println(F("\n[WiFi] Timeout — restarting"));
      ESP.restart();
    }
    delay(500);
    Serial.print('.');
  }
  digitalWrite(LED_PIN, HIGH);  // turn on LED when connected
  Serial.printf("\n[WiFi] Connected. IP: %s\n", WiFi.localIP().toString().c_str());
}

void ensureWiFi() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(F("[WiFi] Lost connection — reconnecting"));
    connectWiFi();
  }
}

// ─────────────────────────────────────────────
// MQTT helpers
// ─────────────────────────────────────────────
void connectMQTT() {
  Serial.printf("[MQTT] Connecting to %s:%d … ", Config::MQTT_HOST, Config::MQTT_PORT);
  mqttClient.setServer(Config::MQTT_HOST, Config::MQTT_PORT);
  mqttClient.setBufferSize(256);

  if (mqttClient.connect(Config::MQTT_CLIENT_ID, Config::MQTT_USER, Config::MQTT_PASS)) {
    Serial.println(F("OK"));
  } else {
    Serial.printf("FAILED (state=%d)\n", mqttClient.state());
  }
}

void ensureMQTT() {
  if (!mqttClient.connected()) {
    uint32_t now = millis();
    if (now - lastMqttRetry >= Config::MQTT_RETRY_DELAY_MS) {
      lastMqttRetry = now;
      connectMQTT();
    }
  }
}

// ─────────────────────────────────────────────
// UART parser
//
// Expects exactly the format produced by the STM32 snprintf:
//   "A0:512 A1:300 A2:1024 A3:750 A4:200"
//   (spaces as delimiters, \r\n already stripped by the reader)
//
// Returns true and fills `out` on success.
// Rejects lines where any channel is outside 0–ADC_MAX.
// ─────────────────────────────────────────────
bool parseUARTLine(const String& line, AdcSample& out) {
  // Require all five channel prefixes
  if (line.indexOf("A0:") < 0 || line.indexOf("A1:") < 0 ||
      line.indexOf("A2:") < 0 || line.indexOf("A3:") < 0 ||
      line.indexOf("A4:") < 0) {
    return false;
  }

  // Extract unsigned integer after "AN:" up to the next space or end-of-string
  auto extractUInt = [&](const char* key, bool& ok) -> uint16_t {
    int idx = line.indexOf(key);
    if (idx < 0) { ok = false; return 0; }
    int valueStart = idx + strlen(key);
    int valueEnd   = line.indexOf(' ', valueStart);
    String s = (valueEnd < 0) ? line.substring(valueStart)
                               : line.substring(valueStart, valueEnd);
    s.trim();
    // strtoul for proper unsigned parsing
    char buf[8];
    s.toCharArray(buf, sizeof(buf));
    char* endPtr;
    unsigned long v = strtoul(buf, &endPtr, 10);
    if (endPtr == buf) { ok = false; return 0; }   // no digits parsed
    if (v > Config::ADC_MAX) { ok = false; return 0; }
    return (uint16_t)v;
  };

  bool ok = true;
  out.ch[0] = extractUInt("A0:", ok);
  out.ch[1] = extractUInt("A1:", ok);
  out.ch[2] = extractUInt("A2:", ok);
  out.ch[3] = extractUInt("A3:", ok);
  out.ch[4] = extractUInt("A4:", ok);
  return ok;
}

// ─────────────────────────────────────────────
// JSON builder & MQTT publisher
// ─────────────────────────────────────────────
bool publishAdcData(const AdcSample& sample) {
  timeClient.update();
  unsigned long ts = timeClient.getEpochTime();

  // Payload example:
  // {"device_id":"stm32_gateway_01","A0":512,"A1":300,"A2":1024,"A3":750,"A4":200,"timestamp":1710000000}
  StaticJsonDocument<192> doc;
  doc["device_id"] = Config::DEVICE_ID;
  doc["A0"]        = sample.ch[0];
  doc["A1"]        = sample.ch[1];
  doc["A2"]        = sample.ch[2];
  doc["A3"]        = sample.ch[3];
  doc["A4"]        = sample.ch[4];
  doc["timestamp"] = (uint32_t)ts;

  char payload[192];
  size_t len = serializeJson(doc, payload, sizeof(payload));

  bool ok = mqttClient.publish(Config::MQTT_TOPIC, payload, len);
  if (ok) {
    Serial.printf("[MQTT] Published → %s\n", payload);
  } else {
    Serial.println(F("[MQTT] Publish FAILED"));
  }
  return ok;
}

// ─────────────────────────────────────────────
// setup / loop
// ─────────────────────────────────────────────
void setup() {
  Serial.begin(Config::UART_BAUD);
  uartBuffer.reserve(Config::UART_BUF);
  pinMode(LED_PIN, OUTPUT);

  Serial.println(F("\n[BOOT] ESP8266 STM32-ADC Gateway starting …"));
  connectWiFi();
  timeClient.begin();
  timeClient.update();
  connectMQTT();
  Serial.println(F("[BOOT] Ready — waiting for STM32 ADC data on UART"));
}

void loop() {
  ensureWiFi();
  ensureMQTT();
  mqttClient.loop();   // keep MQTT heartbeat alive

  // ── Non-blocking UART line reader ──
  // STM32 terminates each line with \r\n.
  // We accumulate until \n, stripping \r in place.
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      uartLineReady = true;
      break;
    }
    if (c != '\r') {
      uartBuffer += c;
      if (uartBuffer.length() >= Config::UART_BUF) {
        Serial.println(F("[UART] Buffer overflow — discarding"));
        uartBuffer = "";
      }
    }
  }

  if (uartLineReady) {
    uartLineReady = false;
    uartBuffer.trim();
    Serial.printf("[UART] Received: \"%s\"\n", uartBuffer.c_str());

    AdcSample sample;
    if (parseUARTLine(uartBuffer, sample)) {
      if (mqttClient.connected()) {
        publishAdcData(sample);
      } else {
        Serial.println(F("[MQTT] Not connected — frame dropped"));
      }
    } else {
      Serial.printf("[PARSE] Rejected line: \"%s\"\n", uartBuffer.c_str());
    }

    uartBuffer = "";
  }
}
