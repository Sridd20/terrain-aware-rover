# Terrain-Aware Autonomous Rover

An ESP32-based rover that classifies the surface it's driving on — **tile, mat, carpet, or gravel** — in real time using IMU vibration, and automatically adjusts its speed and torque profile to maintain traction.

```
MPU6050 (100 Hz IMU)
    → 1s windowed accel signal (z-axis, gravity-removed)
    → 5-D feature vector: std, rms, p2p, zcr, speed
    → on-device decision tree classifier  (terrain_classifier.h)
    → terrain label: tile / mat / carpet / gravel
    → adaptive PWM + transition ramp control
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
| Power | 3S 18650 Li-ion (11.1 V) + 3S BMS | Motor supply; L298N 5 V reg powers ESP32 via VIN |

> **Mounting critical:** bolt the MPU6050 directly to the chassis frame, near a wheel mount — not on foam or a loose breadboard. Soft mounting low-pass-filters the vibration signal and kills classification accuracy.

### Pin Map

| Signal | ESP32 GPIO |
|--------|-----------|
| L298N IN1 (Left dir A) | 27 |
| L298N IN2 (Left dir B) | 26 |
| L298N IN3 (Right dir A) | 25 |
| L298N IN4 (Right dir B) | 33 |
| L298N ENA (Left PWM) | 14 |
| L298N ENB (Right PWM) | 12 |
| MPU6050 / OLED SDA | 21 |
| MPU6050 / OLED SCL | 22 |

---

## Operating Modes

The firmware runs in one of two modes, switchable at any time from the WiFi dashboard or Serial:

### Training Mode
- You select the current terrain label (Tile / Mat / Carpet / Gravel) via the dashboard or `LABEL <name>` Serial command
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
- **Terrain selector** (Training mode) — large buttons for Tile / Mat / Carpet / Gravel
- **Classification result** (Testing mode) — Predicted vs Actual with ✓/✗ match indicator and confidence bar
- **Motor controls** — PWM slider (0–255), GO / STOP buttons
- **Live vibration gauges** — std, rms, p2p, zcr, speed updated every second via WebSocket
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

| Terrain | Target speed | Motor gain (kv) | Ramp to tile | Ramp to gravel |
|---------|-------------|-----------------|-------------|----------------|
| Tile    | 0.55 m/s    | 0.08            | —           | 0.04 m/s·tick  |
| Mat     | 0.40 m/s    | 0.06            | 0.12        | 0.05           |
| Carpet  | 0.28 m/s    | 0.05            | 0.14        | 0.05           |
| Gravel  | 0.18 m/s    | 0.04            | 0.15        | —              |

Softer motor gain on rough terrain prevents numerical instability (NaN/Inf QACC) at high wheel speeds over coarse surfaces. Ramp rates are per 0.1 s control tick; hold windows (2–4 consecutive matching windows) are required before committing a terrain change.

---

## Repository Layout

```
terrain_sim.py              MuJoCo physics sim — heightfield terrain + 4-wheel rover
generate_ml_dataset.py      Generate ML training data from MuJoCo (ml_dataset.csv)
mujoco_to_firmware.py       Train decision tree on ml_dataset.csv → export terrain_classifier.h
plot_scatter.py             Scatter plot: Vibration RMS vs Speed (presentation figure)
plot_dataset_summary.py     Dataset summary table (presentation figure)
export_summary_csv.py       Export per-class statistics CSV

dataset.csv                 Original 108-sample dataset (3 PWM × 4 terrains)
ml_dataset.csv              340-sample dataset (5 PWM × 4 terrains, + speed column)
ml_dataset_fresh.csv        Extended dataset from longer MuJoCo rollouts
mujoco_classifier_report.txt  Training report: accuracy, confusion matrix, feature importances

ml_classifier_plan.md       ML classifier design decisions
transition_aware_features.md  Transition-pair ramp control design
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
| Mat     | 150, 190, 230 |
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
Track (6 segments): tile → gravel → carpet → mat → mat → gravel
Controller: BLIND (IMU only)  |  Looping: yes

t=  2.14s | RMS=0.082 | terrain→tile    | speed=0.55 m/s
t=  4.30s | RMS=0.499 | terrain→carpet  | speed=0.28 m/s
t=  4.35s | RMS=1.134 | terrain→gravel  | speed=0.18 m/s
```

---

## ML Classifier

### Why the RMS threshold fails

The original classifier used a single RMS threshold per terrain:
```python
RMS_THRESHOLDS = [(0.273, "carpet"), (0.354, "mat"), (0.447, "tile"), (inf, "gravel")]
```
This breaks at higher speeds — **tile driven fast** produces RMS values that overlap with gravel and carpet. Vibration RMS is speed-dependent, so a single threshold per terrain can't separate all cases.

### Solution: Decision tree on Speed + Vibration

Adding **rover speed (m/s)** as a 6th feature alongside std, rms, p2p, zcr, peak cleanly separates all four terrain classes. The classifier is exported to pure C++ (no ML library needed on the ESP32).

```
5-fold CV accuracy:  77.1% ± 11.2%  (simulation data)
Feature importances: speed > std > rms > p2p > zcr > peak
```

Accuracy is expected to improve significantly when retrained on real hardware data (simulation vibration amplitudes are estimates).

---

## Key Constants

| Constant | Value | Location |
|----------|-------|---------|
| Sample rate | 100 Hz | Firmware loop |
| Window size | 100 samples (1 s) | Feature extraction |
| Hold windows | 2–4 (per terrain pair) | Transition ramp |
| OLED address | 0x3C | I²C bus |
| MPU6050 address | 0x68 | I²C bus |
| WiFi AP IP | 192.168.4.1 | WebServer |
| WebSocket port | 81 | WebSocketsServer |
| Serial baud | 115200 | USB Serial |
| Motor supply | 7–12 V (3S Li-ion recommended) | Battery |

