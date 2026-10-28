# Terrain-Aware Autonomous Rover

An ESP32-based rover that classifies the surface it's driving on — **tile, pavement, carpet, or gravel** — in real time using IMU vibration, and automatically adjusts its speed to match the terrain.

```
MPU6050 (100 Hz IMU)
    → 1s windowed accel signal (z-axis, gravity-removed)
    → 3-feature vector: std, p2p, zcr
    → on-device decision tree classifier  (terrain_classifier.h)
    → terrain label: tile / pavement / carpet / gravel
    → adaptive PWM ramp to terrain target speed
    → L298N dual H-bridge → 2× DC motors
```

---

## Why this matters

Different surfaces have very different traction properties. A rover running at full speed on gravel will lose traction and slip; the same speed on tile is fine. By detecting the surface from vibration signature alone (no camera, no extra sensors), the rover can:

- **Automatically set speed** to the optimal PWM for each terrain — no manual tuning needed
- **Enforce a hard safety ceiling** so even if the user requests too much speed, the firmware caps it
- **Smooth speed transitions** with soft-start ramps on every terrain change
- **Collect richer datasets** using Auto Sweep mode — multiple speeds recorded automatically

---

## Hardware

| Component | Part | Notes |
|-----------|------|-------|
| MCU | ESP32 DevKit V1 (30-pin) | WiFi AP + WebSocket + OLED + motor control |
| IMU | MPU6050 | I2C addr 0x68, GPIO 21 (SDA) / 22 (SCL) |
| Motor driver | L298N dual H-bridge | ENA/ENB jumpers **must be removed** for PWM speed control |
| Motors | 2x yellow TT DC motors | Rear-left (ch A) + Rear-right (ch B); front caster is passive |
| Display | SSD1306 0.96" OLED (128x64) | I2C addr 0x3C, shared SDA/SCL bus with MPU6050 |
| Power | 3S 18650 Li-ion (11.1 V) + 3S BMS | Drives motors via L298N; L298N 5 V output to ESP32 VIN |

> **Mounting critical:** bolt the MPU6050 directly to the chassis frame, near a wheel mount — not on foam or a loose breadboard. Soft mounting low-pass-filters the vibration signal and kills classification accuracy.

### Power Supply — Required Decoupling Capacitors

The ESP32 reboots (brown-out reset) the moment a motor command is sent because motor startup inrush current causes a brief voltage dip on the supply rail. A capacitor is **required** to stabilise the 5 V rail:

| Location | Capacitor | Purpose |
|----------|-----------|---------|
| L298N 12V/VCC to GND terminals | 470-1000 uF electrolytic, >= 16 V | Absorbs motor inrush current |
| L298N 5V out to GND, near ESP32 VIN/GND | 100-220 uF electrolytic, >= 10 V | Keeps 5 V rail stable during motor startup |

**Firmware soft-start (complementary fix):**
The firmware ramps motor PWM from 0 to target over 150 ms (`RAMP_STEPS = 15 x RAMP_STEP_MS = 10 ms`) whenever a `go`, `back`, `turn`, or `spin` command is received — including when the adaptive controller changes speed.

### Pin Map

| Signal | ESP32 GPIO | Notes |
|--------|-----------|-------|
| L298N IN1 (Left dir A) | 27 | |
| L298N IN2 (Left dir B) | 26 | |
| L298N IN3 (Right dir A) | 25 | ADC2_CH8 — WiFi conflict, workaround in firmware |
| L298N IN4 (Right dir B) | 33 | |
| L298N ENA (Left PWM) | 14 | LEDC ch 4, 1 kHz |
| L298N ENB (Right PWM) | **13** | LEDC ch 5, 1 kHz — **not GPIO 12** |
| MPU6050 / OLED SDA | 21 | |
| MPU6050 / OLED SCL | 22 | |

> **ENB pin:** uses GPIO 13, not GPIO 12. GPIO 12 is a bootstrap pin that can prevent booting if held HIGH at power-on.

---

## Operating Modes

The firmware runs in one of **three modes**, switchable at any time from the WiFi dashboard or Serial:

### Training Mode

- Select the current terrain label (Tile / Pavement / Carpet / Gravel) via the dashboard or `LABEL <name>` Serial command
- Every 1-second feature window is tagged with your label and logged to Serial CSV
- Use this to collect `train_dataset.csv` for re-training on real hardware
- Drive manually and record — full motor control available

### Testing Mode

- The on-board decision tree classifier (`terrain_classifier.h`) predicts the terrain every 1-second window
- OLED and dashboard show **Predicted** terrain + confidence bar
- **Adaptive Speed Control** automatically ramps motors to the terrain's optimal PWM target (toggle on/off from the dashboard)
- You confirm (YES) or correct (NO) via the dashboard — feedback rows are logged for future retraining

### Auto Sweep Mode *(new)*

- The rover **automatically steps through a configurable set of PWM values** on a chosen terrain
- Each speed step runs for a configurable dwell time (2-20 s), logs IMU feature windows, then advances
- Up to 8 speed steps can be configured via the dashboard speed-pill selector
- After completing all steps, motors stop and a completion banner is shown
- Purpose: collect **multi-speed training data** efficiently without manually changing PWM

---

## WiFi Dashboard

The ESP32 creates a WiFi Access Point — no router needed.

| Setting | Value |
|---------|-------|
| SSID | `TerrainRover` |
| Password | `rover1234` |
| Dashboard URL | `http://192.168.4.1` |

Open the URL from any phone or PC browser. The dashboard has **three panels** (Training / Testing / Auto Sweep):

### Training Panel
- **Terrain selector** — large buttons for Tile / Pavement / Carpet / Gravel
- **Motor controls** — PWM slider (0-255), GO / STOP, D-pad, spin buttons
- **Live vibration gauges** — STD, RMS, P2P, ZCR updated every second via WebSocket
- **Data logging** — REC / STOP, sample counter, Download CSV button

### Testing Panel
- **Terrain prediction** — large terrain label + confidence bar
- **Adaptive Speed Control** toggle pill — when ON, firmware auto-ramps to terrain's target PWM; current target shown live (e.g., `-> PWM 200`)
- **Feedback buttons** — YES / NO + correction terrain picker
- **Motor controls** — PWM slider (respects adaptive setting), D-pad
- **Session stats** — total predictions, correct count, accuracy bar

### Auto Sweep Panel
- **Terrain label selector** — which terrain is being swept
- **Speed step pills** — toggle individual PWM values (80 / 100 / 120 / 140 / 160 / 180 / 200 / 220)
- **Dwell slider** — time per step (2-20 seconds)
- **Progress display** — overall step progress bar + per-step dwell sub-bar + sample counters
- **START SWEEP / STOP** — starts the autonomous sweep sequence
- **Download CSV** — downloads all collected windows

---

## OLED Display

The 128x64 OLED mounted on the rover shows at a glance:

```
[TRAIN]              00:02:34   <- mode + uptime
Surface:
TILE                            <- your selected label
RMS: 0.141   ZCR: 57
STD: 0.142   P2P: 1.37
PWM:180  0.29m/s  REC          <- motor + speed + rec
```

In **Testing Mode**, the predicted terrain is shown large with a match indicator. When predicted != actual, the predicted label inverts so mismatches are obvious while the rover is in motion.

---

## Adaptive Driving Profiles

Each terrain has a **target PWM** (optimal cruise speed) and a **max PWM** (hard safety ceiling), stored in `terrain_classifier.h`:

| Terrain  | Target PWM | Max PWM | Accel Ramp (s) | Turn Gain |
|----------|-----------|---------|----------------|-----------|
| Tile     | 200       | 220     | 0.20           | 1.00      |
| Pavement | 170       | 200     | 0.30           | 0.90      |
| Carpet   | 150       | 170     | 0.40           | 0.80      |
| Gravel   | 110       | 130     | 0.60           | 0.60      |

**Adaptive ON (default):** when the classifier fires, the firmware calls `rampMotors()` to smoothly transition to the terrain's `targetPwm`. Serial logs `[ADAPTIVE] gravel -> PWM 110 (target 110, max 130)`.

**Adaptive OFF:** the controller only enforces the `maxPwm` ceiling — useful when you want manual speed control during data collection.

---

## Auto Sweep — Data Collection Workflow

To build a multi-speed dataset for a single terrain:

1. Place rover on the terrain and label it (e.g., **CARPET**)
2. Switch to **Auto Sweep** mode in the dashboard
3. Select the desired PWM steps (e.g., 80, 100, 120, 140, 160, 180) and set dwell to **8 s**
4. Press **START SWEEP** — the rover drives forward, steps through each PWM automatically
5. Each 1-second IMU window is logged with its `label` and `pwm` to Serial CSV (same `TRAIN,...` format)
6. After the last step, motors stop and "Sweep complete!" banner appears
7. Download `sweep_dataset.csv` from the dashboard, or capture via `collect_data.py` over Serial
8. Repeat for each terrain surface

**Why multi-speed data matters:** vibration features (STD, P2P, ZCR) are speed-dependent. A classifier trained at only one speed will fail at other speeds. Sweeping 6 PWM levels x 8 s x 100 Hz = **~48 windows per terrain per sweep** — enough to retrain a robust speed-invariant decision tree.

### Serial commands for Auto Sweep

| Command | Action |
|---------|--------|
| `MODE SWEEP` | Switch to Auto Sweep mode |
| `SWEEP START` | Begin sweep with current config |
| `SWEEP STOP` | Abort sweep, stop motors |
| `SWEEP DWELL <ms>` | Set dwell time in milliseconds |
| `LABEL <name>` | Set terrain label before sweep |

---

## Repository Layout

```
terrain_sim.py              MuJoCo physics sim — heightfield terrain + 4-wheel rover
generate_ml_dataset.py      Generate ML training data from MuJoCo (ml_dataset.csv)
mujoco_to_firmware.py       Train decision tree on ml_dataset.csv -> export terrain_classifier.h
terrain_classifier.py       Standalone sklearn classifier — scatter plots, feature importances
plot_scatter.py             Scatter plot: Vibration RMS vs Speed (presentation figure)
plot_dataset_summary.py     Dataset summary table (presentation figure)
export_summary_csv.py       Export per-class statistics CSV

dataset.csv                 Original 108-sample dataset (3 PWM x 4 terrains x 9 samples)
ml_dataset.csv              340-sample dataset (5 PWM x 4 terrains x 17 samples, + speed)
ml_dataset_fresh.csv        Extended dataset from longer MuJoCo rollouts
dataset_summary.csv         Per-class feature statistics (std, rms, p2p, zcr, speed range)
mujoco_classifier_report.txt  Training report: accuracy, confusion matrix, feature importances

data/
    carpet_train_dataset.csv    Real hardware data — carpet terrain
    gravel_train_dataset.csv    Real hardware data — gravel terrain
    pavement_train_dataset.csv  Real hardware data — pavement terrain
    tile_train_dataset.csv      Real hardware data — tile terrain

rover_firmware/
    rover_firmware.ino      Main ESP32 firmware — IMU, OLED, WiFi AP, WebSocket, motors
                            Modes: TRAINING, TESTING, AUTO_SWEEP
    dashboard.h             Embedded HTML/CSS/JS web dashboard (3-tab: Train/Test/Sweep)
    terrain_classifier.h    Decision tree + terrain driving profiles (targetPwm, maxPwm)
    collect_data.py         PC-side Serial logger — writes train_dataset.csv + feedback_log.csv
```

---

## Getting Started

### 1. Flash firmware

Install required Arduino libraries (Library Manager):
- **WebSockets** by Markus Sattler
- **Adafruit SSD1306**
- **Adafruit GFX Library**
- **ArduinoJson** by Benoit Blanchon

Open `rover_firmware/rover_firmware.ino` in Arduino IDE, select **ESP32 Dev Module**, flash.

### 2. Connect & control

1. Connect phone/PC to WiFi `TerrainRover` (password: `rover1234`)
2. Open `http://192.168.4.1` in browser
3. Switch to **Training Mode**, select terrain, set PWM, tap GO
4. Drive over each surface — data logs automatically every 1 second

### 3a. Collect real-world data (manual)

Drive on each surface at several PWM levels, ~10 s per run:

| Terrain  | Suggested PWM levels |
|----------|---------------------|
| Tile     | 160, 180, 200, 220  |
| Pavement | 140, 160, 180, 200  |
| Carpet   | 120, 140, 160, 180  |
| Gravel   | 80, 100, 120, 140   |

Download `train_dataset.csv` from the dashboard, or use `rover_firmware/collect_data.py` over Serial.

### 3b. Collect real-world data (Auto Sweep — recommended)

1. Place rover on terrain, select terrain label in dashboard
2. Switch to **Auto Sweep** mode
3. Tick the PWM steps to sweep (e.g. 80 to 180 in steps of 20)
4. Set dwell to 8 s, press **START SWEEP**
5. Rover drives, steps through speeds, stops automatically
6. Download CSV — repeat for each terrain

This is faster and more systematic than manual collection.

### 4. Re-train classifier (optional)

```bash
python mujoco_to_firmware.py   # trains on ml_dataset.csv by default
# or pass your real hardware data:
python mujoco_to_firmware.py --dataset train_dataset.csv
# -> writes rover_firmware/terrain_classifier.h
```

Re-flash firmware. Switch to **Testing Mode** — the rover now classifies terrain on-device and sets speed adaptively.

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

---

## ML Classifier

The classifier is a **depth-5 decision tree** trained on std, p2p, zcr features, exported to pure C++ in `terrain_classifier.h` — no ML library needed on the ESP32.

| Class    | Precision | Recall | F1-Score |
|----------|-----------|--------|----------|
| carpet   | 0.65      | 0.79   | 0.71     |
| gravel   | 1.00      | 0.84   | 0.91     |
| pavement | 0.77      | 0.60   | 0.68     |
| tile     | 0.85      | 1.00   | 0.92     |

Accuracy improves significantly when retrained on real hardware multi-speed data — use Auto Sweep to collect this.

### PWM to Speed Calibration

```
speed_ms = 0.001471 x PWM - 0.000265    (RMSE: 0.0001 m/s)
```

Embedded in `terrain_classifier.h` as `PWM_SPEED_SLOPE` and `PWM_SPEED_INTERCEPT`.

---

## Key Constants

| Parameter | Value | Location |
|-----------|-------|----------|
| IMU accel range | +-8 g (AFS_SEL = 2) | Firmware |
| Sample rate | 100 Hz | Firmware loop |
| Window size | 100 samples (1 s) | Feature extraction |
| OLED address | 0x3C | I2C bus |
| MPU6050 address | 0x68 | I2C bus |
| WiFi AP IP | 192.168.4.1 | WebServer |
| WebSocket port | 81 | WebSocketsServer |
| Serial baud | 115200 | USB Serial |
| Motor supply | 7-12 V (3S Li-ion) | Battery to L298N |
| PWM to speed slope | 0.001471 m/s per PWM unit | terrain_classifier.h |
| PWM to speed intercept | -0.000265 m/s | terrain_classifier.h |
| Sweep max steps | 8 | rover_firmware.ino |
| Default sweep dwell | 5000 ms | rover_firmware.ino |
