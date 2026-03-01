#include <OneWire.h>
#include <DallasTemperature.h>

// ========== USER CONFIG ==========
#define ONE_WIRE_BUS 27        // GPIO connected to DQ
#define TEMP_OFFSET  0.0       // Calibration offset (°C)
// =================================

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

void setup() {
  Serial.begin(115200);
  delay(1000);

  sensors.begin();

  // Set resolution (9–12 bits)
  sensors.setResolution(12);   // 12-bit = 0.0625 °C

  Serial.println("DS18B20 Temperature Sensor Initialized");
}

void loop() {

  sensors.requestTemperatures();   // Blocking call (~750 ms at 12-bit)
  float tempC = sensors.getTempCByIndex(0);

  if (tempC == DEVICE_DISCONNECTED_C) {
    Serial.println("Error: DS18B20 not detected");
  } else {
    float calibratedTemp = tempC + TEMP_OFFSET;

    Serial.print("Temperature: ");
    Serial.print(calibratedTemp, 2);
    Serial.println(" °C");
  }

  delay(2000);
}
