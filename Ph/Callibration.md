## Calibration Procedure (Critical)

> **Do not skip this.** Without calibration, the readings are not scientifically meaningful.

### Required Buffer Solutions
- **pH 4.00**
- **pH 6.86**
- **pH 9.18**
- **Temperature:** approximately **25 °C**

---

### Calibration Steps

1. **Place the sensor in pH 6.86 buffer**
   - Wait until the reading stabilizes
   - Record the measured voltage as:
     ```
     V_mid
     ```

2. **Place the sensor in pH 4.00 buffer**
   - Wait for stabilization
   - Record the measured voltage as:
     ```
     V_low
     ```

3. **Place the sensor in pH 9.18 buffer**
   - Wait for stabilization
   - Record the measured voltage as:
     ```
     V_high
     ```

---

### Compute Calibration Parameters (Linear Model)

#### Slope
```math
slope = \frac{pH_{high} - pH_{low}}{V_{high} - V_{low}}

offset = pH_{mid} - (slope*V_{mid})
