// ====== USER CONFIG ======
#define PH_ADC_PIN A0
#define ADC_SAMPLES 50      // Averaging for noise reduction
#define VREF_ADC 5.0        // ADC reference voltage (UNO = 5V)

// Calibration constants (REPLACE after calibration)
float CAL_A = 9.89;
float CAL_B = 106.44;

// =========================

void setup() {
  Serial.begin(9600);
  analogReference(DEFAULT); // Uses Vcc as reference
}

void loop() {

  // -------- ADC Averaging --------
  long adcSum = 0;
  for (int i = 0; i < ADC_SAMPLES; i++) {
    adcSum += analogRead(PH_ADC_PIN);
    delay(5);
  }
  float adcAvg = adcSum / (float)ADC_SAMPLES;

  // -------- Convert ADC to Voltage --------
  float voltage = (adcAvg / 1023.0) * VREF_ADC;

  // -------- Convert ADC to pH --------
  // Model from paper: pH = A - B * ADC_normalized
  float adcNorm = adcAvg / 1023.0;
  float pH = CAL_A - (CAL_B * adcNorm);

  // -------- Output --------
  Serial.print("ADC: ");
  Serial.print(adcAvg, 1);
  Serial.print(" | Voltage: ");
  Serial.print(voltage, 3);
  Serial.print(" V | pH: ");
  Serial.println(pH, 2);

  delay(1000);
}
