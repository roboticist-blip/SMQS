# MQ-135 Sensor Calibration – Complete Procedure

This document describes the **full calibration process** for the MQ-135 gas sensor, starting from **hardware modification** (load resistor change) to **software and library configuration**. Follow all steps in order. Skipping any step will invalidate the calibration.

---

## 1. Load Resistor (RL) Modification

Most MQ-135 modules come with a **1 kΩ load resistor (RL)** soldered on the back side of the PCB.

### Required Action
- Desolder the existing **1 kΩ resistor**
- Replace it with a **22 kΩ resistor**

```text
Default RL  : 1 kΩ  ❌
Required RL : 22 kΩ ✅
```
## 2. Calculating the Ro Value of MQ135 Sensor
Now that we know the value of RL, let’s proceed on how to calculate the Ro values in clean air. Here we are going to use MQ135.h to measure the CO2 concentration in the air. So first download the MQ-135 Library, then preheat the sensor for 24 hours before reading the Ro values. After the preheating process, use the below code to read the Ro values:

```text
#include "MQ135.h"
void setup (){
Serial.begin (9600);
}
void loop() {
MQ135 gasSensor = MQ135(A0); // Attach sensor to pin A0
float rzero = gasSensor.getRZero();
Serial.println (rzero);
delay(1000);
}
```
Now once you got the Ro values, Go to Documents > Arduino > libraries > MQ135-master folder and open the MQ135.h file and change the RLOAD & RZERO values.

```text
> ///The load resistance on the board
> #define RLOAD 22.0
> ///Calibration resistence at atmospheric CO2 level
> #define RZERO 5804.99
```
Now scroll down and replace the ATMOCO2 value with the current Atmospheric CO2 that is 411.29

```text
> ///Atmospheric CO2 level for calibration purposes
> #define ATMOCO2 397.13
```
And then upload the final measuring code.
