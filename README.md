# Terrain-Aware Autonomous Rover

An ESP32-based rover that classifies the surface it's driving on — **tile, pavement, carpet, or gravel** — in real time using IMU vibration, and automatically adjusts its speed and torque profile to maintain traction.

```
MPU6050 (100 Hz IMU)
    → 1s windowed accel signal (z-axis, gravity-removed)
    → 6-D feature vector: std, peak, rms, p2p, zcr, speed
    → on-device decision tree classifier  (terrain_classifier.h)
    → terrain label: tile / pavement / carpet / gravel
    → adaptive PWM + transition-pair ramp control
    → L298N dual H-bridge → 2× DC motors
```

---

## Why this matters

Different surfaces have very different traction properties. A rover running at full speed on gravel will lose traction and slip; the same speed on tile is fine. By detecting the surface from vibration signature alone (no camera, no extra sensors), the rover can:

- **Reduce PWM** on low-grip surfaces like gravel before a slip happens
- **Smooth speed transitions** with per-pair ramp rates (e.g., gravel→tile ramps up faster than tile→gravel brakes)
- **Reduce turn gain** on loose surfaces to keep straight-line traction
- **Confirm terrain changes** over multiple windows before committing (prevents flickering at seams)

---

## Hardware

| Component | Part | Notes |
|-----------|------|-------|
| MCU | ESP32 DevKit V1 (30-pin) | WiFi AP + WebSocket + OLED + motor control |
| IMU | MPU6050 | I²C addr 0x68, GPIO 21 (SDA) / 22 (SCL) |
| Motor driver | L298N dual H-bridge | ENA/ENB jumpers **must be removed** for PWM speed control |
| Motors | 2× yellow TT DC motors | Rear-left (ch A) + Rear-right (ch B); front caster is passive |
| Display | SSD1306 0.96″ OLED (128×64) | I²C addr 0x3C, shared SDA/SCL bus with MPU6050 |
| Power | 3S 18650 Li-ion (11.1 V) + 3S BMS | Drives motors via L298N; L298N 5 V output → ESP32 VIN (no buck converter — see capacitor note below) |

> **Mounting critical:** bolt the MPU6050 directly to the chassis frame, near a wheel mount — not on foam or a loose breadboard. Soft mounting low-pass-filters the vibration signal and kills classification accuracy.

### Power Supply — Required Decoupling Capacitors

The ESP32 reboots (brown-out reset) the moment a motor command is sent because motor startup inrush current causes a brief voltage dip on the supply rail.  A capacitor is **required** to stabilise the 5 V rail:

| Location | Capacitor | Polarity | Purpose |
|----------|-----------|----------|---------|
| L298N `12V / VCC` → `GND` terminals | **470–1000 µF** electrolytic, ≥ 16 V | + to VCC, − to GND | Absorbs motor inrush current; prevents voltage collapse on the motor rail |
| L298N `5V out` → `GND`, **as close to ESP32 `VIN`/`GND` as possible** | **100–220 µF** electrolytic, ≥ 10 V | + to 5 V, − to GND | Keeps the 5 V rail stable during motor startup so ESP32 does not brown-out |

> **No buck converter is used.** The L298N's onboard 5 V regulator (enabled when its 5 V Enable jumper is in place) supplies the ESP32 directly.  The 100–220 µF cap on the 5 V output is the only additional component needed.

**Placement rules:**
- Solder the caps directly across the screw terminals / power pads — not at the end of long wires.
- Keep leads as short as possible; every cm of wire adds inductance that reduces effectiveness.
- A small 100 nF ceramic cap in parallel with each electrolytic (same pads) helps filter high-frequency switching noise from the L298N.

**Firmware soft-start (complementary fix):**  
The firmware also ramps motor PWM from 0 → target over 150 ms (`RAMP_STEPS = 15 × RAMP_STEP_MS = 10 ms`) whenever a `go`, `back`, `turn`, or `spin` command is received.  This reduces the inrush spike magnitude even before the cap has time to respond, and makes the cap requirement less critical.

> **Diagnosis:** if the ESP32 still reboots after adding the cap, open the Serial Monitor — a brown-out will print `rst:0xc (SW_CPU_RESET)` or `rst:0x10 (RTCWDT_RTC_RESET)` in the boot log.  Increase cap value or reduce the default `currentPwm` starting value.

### Pin Map

| Signal | ESP32 GPIO | Notes |
|--------|-----------|-------|
| L298N IN1 (Left dir A) | 27 | |
| L298N IN2 (Left dir B) | 26 | |
| L298N IN3 (Right dir A) | 25 | ADC2_CH8 — see note below |
| L298N IN4 (Right dir B) | 33 | |
| L298N ENA (Left PWM) | 14 | LEDC ch 4, 1 kHz |
| L298N ENB (Right PWM) | **13** | LEDC ch 5, 1 kHz — **not 12** |
| MPU6050 / OLED SDA | 21 | |
| MPU6050 / OLED SCL | 22 | |

> **ENB pin:** the firmware uses **GPIO 13** for ENB, not GPIO 12. GPIO 12 is a bootstrap pin on ESP32 that can prevent booting if held HIGH at power-on.

> **GPIO 25 (IN3) — ADC2 / WiFi conflict:** GPIO 25 is `ADC2_CH8` on the ESP32. When `WiFi.softAP()` starts, the WiFi stack uses ADC2 internally for RF calibration and silently reconfigures ADC2 pins as analog inputs, which breaks `digitalWrite`. The firmware works around this by re-asserting `pinMode(OUTPUT)` inside `setRightMotor()` on every call. If you redesign the wiring, move IN3 to a non-ADC2 GPIO (e.g. GPIO 16, 17, or 18) to avoid this entirely.

---

## Operating Modes

The firmware runs in one of two modes, switchable at any time from the WiFi dashboard or Serial:

### Training Mode
- You select the current terrain label (Tile / Pavement / Carpet / Gravel) via the dashboard or `LABEL <name>` Serial command
- Every 1-second feature window is tagged with your label and logged to Serial CSV
- Use this to collect `hw_dataset.csv` for re-training on real hardware

### Testing Mode
- The on-board decision tree classifier (`terrain_classifier.h`) predicts the terrain every 1-second window
- OLED and dashboard show **Predicted** terrain + confidence
- You confirm (✓) or correct (✗) via the dashboard — feedback rows are logged for future retraining

---

## WiFi Dashboard

The ESP32 creates a WiFi Access Point — no router needed.

| Setting | Value |
|---------|-------|
| SSID | `TerrainRover` |
| Password | `rover1234` |
| Dashboard URL | `http://192.168.4.1` |

Open the URL from any phone or PC browser. The dashboard provides:

- **Mode toggle** — Training / Testing
- **Terrain selector** (Training mode) — large buttons for Tile / Pavement / Carpet / Gravel
- **Classification result** (Testing mode) — Predicted vs Actual with ✓/✗ match indicator and confidence bar
- **Motor controls** — PWM slider (0–255), GO / STOP buttons
- **Live vibration gauges** — std, peak, rms, p2p, zcr, speed updated every second via WebSocket
- **Data logging** — REC / STOP, sample counter, Download CSV button

---

## OLED Display

The 128×64 OLED mounted on the rover shows at a glance:

```
┌────────────────────────────────┐
│ TERRAIN-AWARE ROVER    00:02:34│  ← uptime
├────────────────────────────────┤
│ Mode: TRAINING                 │  ← current mode
│ Actual:    TILE                │  ← your selected label
│ Predicted: TILE  ✓             │  ← classifier + match icon
├────────────────────────────────┤
│ RMS: 0.141   ZCR: 57          │
│ STD: 0.142   P2P: 1.37        │
├────────────────────────────────┤
│ PWM:180  0.29m/s  WiFi:1  REC●│  ← motor, speed, clients, rec
└────────────────────────────────┘
```

When **predicted ≠ actual**, the predicted label inverts (white on black) so mismatches are obvious while the rover is in motion.

---

## Adaptive Driving Profiles

Speed targets and turn gains are stored in `terrain_classifier.h` and applied automatically after each terrain classification:

| Terrain | Max PWM | Accel Ramp (s) | Turn Gain |
|---------|---------|----------------|-----------|
| Tile    | 220     | 0.20           | 1.00      |
| pavement     | 190     | 0.30           | 0.90      |
| Carpet  | 170     | 0.40           | 0.80      |
| Gravel  | 130     | 0.60           | 0.60      |

Lower max PWM and a longer acceleration ramp on rough terrain prevent wheel slip. Reduced turn gain on loose surfaces maintains straight-line traction during cornering.

### Transition-Pair Ramp Control

Rather than snapping instantly to the new terrain's speed target, the controller interpolates smoothly using a per-pair ramp table. The new label must be confirmed over **K consecutive 1-second windows** before committing (prevents false triggers at noisy surface seams).

| From → To       | Ramp Rate (m/s·tick) | Hold Windows | Rationale                         |
|-----------------|---------------------|--------------|-----------------------------------|
| tile → gravel   | 0.04                | 4            | Sudden rough — brake hard, wait   |
| tile → carpet   | 0.08                | 3            | Moderate softening                |
| tile → pavement      | 0.10                | 2            | Subtle — quick ramp               |
| pavement → gravel    | 0.05                | 4            | Rough incoming — brake firmly     |
| pavement → carpet    | 0.09                | 2            | Near-similar — gentle             |
| pavement → tile      | 0.12                | 2            | Smoother — ease up                |
| carpet → gravel | 0.05                | 4            | Big jump in roughness             |
| carpet → pavement    | 0.10                | 2            | Slight improvement                |
| carpet → tile   | 0.14                | 1            | Much smoother — accelerate freely |
| gravel → carpet | 0.08                | 3            | Some improvement — ramp gently    |
| gravel → pavement    | 0.10                | 2            | Clear improvement                 |
| gravel → tile   | 0.15                | 1            | Suddenly smooth — quick ramp      |

> **Ramp Rate** is per 0.1 s control tick (one feature window). **Hold Windows** = consecutive matching labels required before the transition is committed.

---

## Repository Layout

```
terrain_sim.py              MuJoCo physics sim — heightfield terrain + 4-wheel rover
generate_ml_dataset.py      Generate ML training data from MuJoCo (ml_dataset.csv)
mujoco_to_firmware.py       Train decision tree on ml_dataset.csv → export terrain_classifier.h
terrain_classifier.py       Standalone sklearn classifier — scatter plots, feature importances
plot_scatter.py             Scatter plot: Vibration RMS vs Speed (presentation figure)
plot_dataset_summary.py     Dataset summary table (presentation figure)
export_summary_csv.py       Export per-class statistics CSV

dataset.csv                 Original 108-sample dataset (3 PWM × 4 terrains × 9 samples)
ml_dataset.csv              340-sample dataset (5 PWM × 4 terrains × 17 samples, + speed)
ml_dataset_fresh.csv        Extended dataset from longer MuJoCo rollouts
dataset_summary.csv         Per-class feature statistics (std, rms, p2p, zcr, speed range)
mujoco_classifier_report.txt  Training report: accuracy, confusion matrix, feature importances

ml_classifier_plan.md       ML classifier design decisions and presentation slide plan
transition_aware_features.md  Transition-pair ramp control architecture
implementation_plan_v2.md   Full hardware build plan (wiring, firmware, dashboard, OLED)

rover_firmware/
    rover_firmware.ino      Main ESP32 firmware — IMU, OLED, WiFi AP, WebSocket, motors
    dashboard.h             Embedded HTML/CSS/JS web dashboard (served as C string)
    terrain_classifier.h    Auto-generated decision tree (from mujoco_to_firmware.py)
    collect_data.py         PC-side Serial logger — writes hw_dataset.csv

scatter_speed_vib.png       Vibration vs Speed scatter (why RMS alone fails)
dataset_summary_table.png   Per-class feature summary table
example_plots.png           MuJoCo accelerometer traces for all 4 terrains
```

---

## Getting Started

### 1. Flash firmware

Install required Arduino libraries (Library Manager):
- **WebSockets** by Markus Sattler
- **Adafruit SSD1306**
- **Adafruit GFX Library**
- **ArduinoJson** by Benoît Blanchon

Open `rover_firmware/rover_firmware.ino` in Arduino IDE, select **ESP32 Dev Module**, flash.

### 2. Connect & control

1. Connect phone/PC to WiFi `TerrainRover` (password: `rover1234`)
2. Open `http://192.168.4.1` in browser
3. Switch to **Training Mode**, select terrain, set PWM, tap GO
4. Drive over each surface → data logs automatically every 1 second

### 3. Collect real-world data

Drive on each surface at 3 PWM levels (see table below), ~10 s per run:

| Terrain | PWM levels |
|---------|-----------|
| Tile    | 180, 220, 255 |
| pavement     | 150, 190, 230 |
| Carpet  | 135, 170, 205 |
| Gravel  | 100, 130, 165 |

Download `hw_dataset.csv` from the dashboard, or use `rover_firmware/collect_data.py` over Serial.

### 4. Re-train classifier (optional)

```bash
python mujoco_to_firmware.py   # trains on ml_dataset.csv by default
# or pass your real hardware data:
python mujoco_to_firmware.py --dataset hw_dataset.csv
# → writes rover_firmware/terrain_classifier.h
```

Re-flash firmware. Switch to **Testing Mode** and compare predicted vs actual terrain labels.

---

## Synthetic Data & Simulation

If you don't have the hardware yet, `terrain_sim.py` generates labelled data using MuJoCo physics:

```bash
pip install mujoco numpy matplotlib
python terrain_sim.py                           # generate dataset.csv + example_plots.png
python terrain_sim.py --view gravel             # interactive 3D viewer (needs display)
python terrain_sim.py --view-adaptive           # mixed-terrain adaptive controller demo
python terrain_sim.py --view-adaptive --seed 42 # reproducible track
```

> This is **not** a substitute for real data — bump amplitudes are estimates. Use it to validate the feature extraction and ML pipeline before hardware is ready.

**Mixed-terrain terminal output:**
```
Track (6 segments): tile → gravel → carpet → pavement → pavement → gravel
Controller: BLIND (IMU only)  |  Looping: yes

t=  2.14s | RMS=0.082 | terrain→tile    | speed=0.55 m/s
t=  4.30s | RMS=0.499 | terrain→carpet  | speed=0.28 m/s
t=  4.35s | RMS=1.134 | terrain→gravel  | speed=0.18 m/s
```

---

## ML Classifier

### Dataset

The classifier is trained on **340 windows** generated from MuJoCo rollouts across 5 PWM levels × 4 terrain classes (85 samples per class):

| Terrain | Samples | Avg STD | Avg RMS | Avg P2P | Avg ZCR | Speed range (m/s) |
|---------|---------|---------|---------|---------|---------|-------------------|
| Tile    | 85      | 0.413   | 0.416   | 3.844   | 53.2    | 0.288 – 0.525     |
| pavement     | 85      | 0.290   | 0.291   | 2.167   | 55.4    | 0.247 – 0.463     |
| Carpet  | 85      | 0.254   | 0.255   | 2.020   | 54.7    | 0.206 – 0.422     |
| Gravel  | 85      | 0.476   | 0.477   | 4.615   | 46.3    | 0.165 – 0.340     |

### Why the RMS threshold fails

The original classifier used a single RMS threshold per terrain:
```python
RMS_THRESHOLDS = [(0.273, "carpet"), (0.354, "pavement"), (0.447, "tile"), (inf, "gravel")]
```
This breaks at higher speeds — **tile driven fast** produces RMS values that overlap with gravel and carpet. Vibration RMS is speed-dependent, so a single threshold per terrain can't separate all cases.

### Solution: Decision tree on Speed + Vibration

Adding **rover speed (m/s)** as a 6th feature alongside std, peak, rms, p2p, zcr cleanly separates all four terrain classes. The classifier is a depth-5 decision tree exported to pure C++ — no ML library needed on the ESP32.

```
5-fold CV accuracy:  77.1% ± 11.2%  (340-sample simulation dataset)
Training set accuracy: 81.2%
Feature importances: speed > peak > std > rms > p2p > zcr
```

**Per-class results (training set):**

| Class  | Precision | Recall | F1-Score |
|--------|-----------|--------|----------|
| carpet | 0.65      | 0.79   | 0.71     |
| gravel | 1.00      | 0.84   | 0.91     |
| pavement    | 0.77      | 0.60   | 0.68     |
| tile   | 0.85      | 1.00   | 0.92     |

Accuracy is expected to improve significantly when retrained on real hardware data (simulation vibration amplitudes are estimates).

### PWM → Speed Calibration

The firmware derives rover speed from PWM using a linear model fitted from MuJoCo rollouts:

```
speed_ms = 0.001471 × PWM − 0.000265    (RMSE: 0.0001 m/s)
```

This calibration is embedded in `terrain_classifier.h` as `PWM_SPEED_SLOPE` and `PWM_SPEED_INTERCEPT`.

---

## Key Constants

| IMU accel range | ±8 g (AFS_SEL = 2) | Firmware — prevents gravel clipping |
| Sample rate | 100 Hz | Firmware loop |
| Window size | 100 samples (1 s) | Feature extraction |
| Hold windows | 1–4 (per terrain pair) | Transition ramp table |
| OLED address | 0x3C | I²C bus |
| MPU6050 address | 0x68 | I²C bus |
| WiFi AP IP | 192.168.4.1 | WebServer |
| WebSocket port | 81 | WebSocketsServer |
| Serial baud | 115200 | USB Serial |
| Motor supply | 7–12 V (3S Li-ion recommended) | Battery → L298N |
| 5 V supply | L298N onboard regulator → ESP32 VIN (no buck converter) | Decoupled with 100–220 µF cap |
| PWM→speed slope | 0.001471 m/s per PWM unit | terrain_classifier.h |
| PWM→speed intercept | −0.000265 m/s | terrain_classifier.h |

