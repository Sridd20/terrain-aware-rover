# Terrain-Aware Autonomous Rover

An ESP32-based rover that classifies the surface it's driving on — **tile, mat, carpet, or gravel** — in real time using IMU vibration, and automatically adjusts its speed and torque profile to prevent slipping and maintain traction.

```
MPU6050 (100 Hz IMU)
    → 1s windowed accel signal (z-axis)
    → 5-D feature vector: std, rms, peak, p2p, zcr
    → on-device decision tree classifier
    → terrain label (tile / mat / carpet / gravel)
    → adaptive driving profile (PWM + accel ramp + turn gain)
    → L298N motor driver → DC motors
```

---

## Why this matters

Different surfaces have very different traction properties. A rover running at full speed on gravel will lose traction and slip; the same speed on tile is fine. By detecting the surface from vibration signature alone (no camera, no extra sensors), the rover can:

- **Reduce PWM** on low-grip surfaces like gravel before a slip happens
- **Slow acceleration ramps** so wheels don't spin up faster than grip allows
- **Reduce turn gain** on loose surfaces to keep straight-line traction
- **React to slopes** — if pitch exceeds a threshold, override to a climb/retreat mode regardless of terrain

---

## Hardware

| Component | Part | Notes |
|-----------|------|-------|
| MCU | ESP32 DevKit V1 | Runs classifier + control loop |
| IMU | MPU6050 | I2C, GPIO 21/22; bolt rigidly near a wheel mount |
| Motor driver | L298N | Single driver per side (skid-steer) |
| Motors | 2× DC with encoder (optional) | Left/right coupled |
| Power | Separate battery for motors | Do not power motors from ESP32 5V pin |

> **Mounting critical:** bolt the MPU6050 directly to the chassis frame, near a wheel mount — not on foam or a loose breadboard. Soft mounting low-pass-filters the vibration signal and kills classification accuracy.

---

## Driving Profiles (per terrain)

| Terrain | PWM (0–255) | Accel ramp | Turn gain | Why |
|---------|------------|------------|-----------|-----|
| Tile | 220 | 0.2 s | 1.0 | Hard, high grip — full speed safe |
| Mat | 190 | 0.3 s | 0.9 | Slightly deformable — mild caution |
| Carpet | 170 | 0.4 s | 0.8 | Fibres grab unpredictably — slower ramp |
| Gravel | 130 | 0.6 s | 0.6 | Loose, low grip — slowest, gentlest ramp |

These are tuned to prevent slip at the nominal speed for each surface. Tune further once you have real hardware runs.

---

## Slope Handling (overrides terrain profile)

| State | Entry | Action |
|-------|-------|--------|
| NORMAL | default | Apply terrain profile |
| DETECT | pitch > 6° | Hold heading, sample pitch |
| CLIMB | pitch 6–12° | Elevated PWM, minimal turning |
| RETREAT | pitch ≥ 12° | Reverse ~15–20 cm |
| APPROACH | after retreat | Max PWM, locked heading, then re-attempt |

Pitch = `atan2(-ax, sqrt(ay² + az²))` from the IMU gravity vector.

---

## Repository Layout

```
terrain_sim.py            MuJoCo physics sim — heightfield terrain + 4-wheel rover
generate_ml_dataset.py    Generate richer ML training data from MuJoCo (ml_dataset.csv)
plot_scatter.py           Scatter plot: Vibration RMS vs Speed (presentation figure)
plot_dataset_summary.py   Dataset summary table (presentation figure)
dataset.csv               Original 108-sample dataset (3 PWM levels × 4 terrains)
ml_dataset.csv            Richer 340-sample dataset (5 PWM levels × 4 terrains, + speed column)
/firmware                 ESP32 C++ — IMU sampling, feature extraction, classifier, motor control
/ml                       Python — training pipeline (collect → extract → train → export to C++)
/dashboard                Flask/Streamlit — live label, confidence, PWM, slope state over MQTT
/data                     Labelled vibration sessions (raw + processed CSVs)
/docs                     Design doc, wiring diagrams, test results
```

---

## Getting Started

### 1. Collect real vibration data
Flash a minimal firmware that streams IMU data over MQTT (`rover/imu`), then drive the rover on each surface at 3 PWM levels (low/med/high) for ~3 minutes per session × 4 sessions per class.

### 2. Train the classifier
```bash
cd ml/
pip install scikit-learn numpy pandas micromlgen
python train.py          # outputs terrain_classifier.h
```

### 3. Flash full firmware
Copy `terrain_classifier.h` into `/firmware`, build, and flash. The rover will classify terrain and apply the matching driving profile automatically.

### 4. (Optional) Live dashboard
```bash
cd dashboard/
pip install flask paho-mqtt
python app.py
```
Open `http://localhost:5000` — shows live accel trace, terrain label, confidence, PWM, and slope state.

---

## Synthetic Data Bootstrap

If you don't have the hardware yet and want to test the ML pipeline end-to-end, `terrain_sim.py` can generate a labelled `dataset.csv` using MuJoCo physics:

```bash
pip install mujoco
python terrain_sim.py                        # generate dataset.csv
python terrain_sim.py --view gravel --pwm 25 # interactive 3D viewer
```

> This is **not** a substitute for real data — bump amplitudes are estimates, not measurements. Use it to shake out bugs in the feature extraction → training pipeline before hardware is ready.

---

## ML Classifier Pipeline

### Why the RMS threshold fails

The original `AdaptiveController` classifies terrain using a single RMS threshold:

```python
RMS_THRESHOLDS = [(0.10, "tile"), (0.25, "mat"), (0.55, "carpet"), (inf, "gravel")]
```

This breaks at higher speeds: **tile driven fast** produces RMS values (0.6–1.6 m/s²) that overlap with gravel and carpet ranges. The root cause — vibration RMS is speed-dependent, so a single threshold per terrain can't separate all cases.

### Solution: ML classifier using Speed + Vibration

By adding **rover speed (m/s)** as a second feature alongside the 5 vibration features, an ML classifier cleanly separates all four terrain classes. Speed is always distinct per terrain because each class runs at a different target velocity from the adaptive policy.

### Generating the ML dataset

```bash
python generate_ml_dataset.py    # writes ml_dataset.csv (340 windows)
```

`generate_ml_dataset.py` runs MuJoCo rollouts with **5 PWM levels per terrain** (vs 3 in the original) and **10 s rollouts** (vs 6 s), producing 85 windows per class:

| Terrain | PWM levels | Speed range (m/s) | Windows |
|---------|------------|-------------------|---------|
| Tile    | 140–255    | 0.29 – 0.53       | 85      |
| Mat     | 120–225    | 0.25 – 0.46       | 85      |
| Carpet  | 100–205    | 0.21 – 0.42       | 85      |
| Gravel  | 80–165     | 0.16 – 0.34       | 85      |

The CSV schema adds a `speed` column:
```
std, peak, rms, p2p, zcr, speed, label
```

### Generating presentation figures

```bash
# Scatter plot: Vibration RMS vs Speed (shows why RMS alone fails)
python plot_scatter.py              # -> scatter_speed_vib.png

# Dataset summary table
python plot_dataset_summary.py      # -> dataset_summary_table.png
```

Both scripts use the `Agg` matplotlib backend (headless — no display required).

---

## Adaptive Mixed-Terrain Simulation

`terrain_sim.py` now supports a **mixed-terrain track** mode where the rover drives over multiple surface types in random order and adapts its speed and motor torque in real-time — purely from IMU vibration, with no terrain label fed to the controller.

### How it works

```
[MPU6050 Z-axis accel, rolling 50-sample buffer]
        ↓
   gravity-bias removal (subtract median)
        ↓
   vibration RMS  (re-computed every 25 physics steps ≈ 50 ms)
        ↓
   low-pass smoothed  (α = 0.20, prevents flickering at transitions)
        ↓
   roughness classify  →  speed + motor-gain lookup
        ↓
   update wheel velocity targets + actuator kv
```

The controller is **entirely blind** — it never receives the terrain label, only what the IMU feels.

### Adaptive Policy Table

| Terrain (inferred) | RMS threshold (m/s²) | Target speed | Motor gain (kv) |
|--------------------|----------------------|--------------|-----------------|
| tile               | < 0.10               | 0.55 m/s     | 0.08 (fast)     |
| mat                | 0.10 – 0.25          | 0.40 m/s     | 0.06            |
| carpet             | 0.25 – 0.55          | 0.28 m/s     | 0.05            |
| gravel             | ≥ 0.55               | 0.18 m/s     | 0.04 (careful)  |

Softer motor gain on rough terrain prevents the numerical instability (`Nan/Inf QACC`) that occurs at high wheel speeds over coarse surfaces.

### Track generation

The heightfield is split into N equal segments along the X (travel) axis. Each segment is filled with a different terrain's band-limited noise profile, scaled to its elevation, with a 3-column cosine cross-fade at each boundary. The rover **loops continuously** — when it reaches the far end it is teleported back to the start.

### Running the adaptive viewer

```bash
# Random track (different every run)
python terrain_sim.py --view-adaptive

# Reproducible track with fixed seed
python terrain_sim.py --view-adaptive --seed 42

# More segments (default is 6)
python terrain_sim.py --view-adaptive --segments 8
```

**Terminal output while running:**
```
Track (6 segments): tile -> gravel -> carpet -> mat -> mat -> gravel
Controller: BLIND (IMU only)  |  Looping: yes

t=  2.14s | RMS=0.082 | terrain->tile    | speed=0.55 m/s
t=  4.30s | RMS=0.499 | terrain->carpet  | speed=0.28 m/s
t=  4.35s | RMS=1.134 | terrain->gravel  | speed=0.18 m/s
```

### Running all 4 single-terrain viewers simultaneously

```powershell
Start-Process python -ArgumentList "terrain_sim.py --view tile   --pwm 25 --speed 0.8"
Start-Process python -ArgumentList "terrain_sim.py --view mat    --pwm 25 --speed 0.8"
Start-Process python -ArgumentList "terrain_sim.py --view carpet --pwm 25 --speed 0.8"
Start-Process python -ArgumentList "terrain_sim.py --view gravel --pwm 25 --speed 0.8"
```

---

## Key Constants

| Constant | Value | Location |
|----------|-------|----------|
| Sample rate | 100 Hz | Firmware loop |
| Window size | 100 samples (1 s) | Feature extraction |
| Window overlap | 50% | Training pipeline |
| Smoothing | majority vote, last 5 | Firmware |
| Tree depth | 5 | Training |
| Slope detect | 6° pitch | State machine |
| Slope steep | 12° pitch | State machine |
| Slope resume | 2° pitch | State machine |
| Retreat distance | 15–20 cm | State machine |

All thresholds are initial estimates from the design phase — **tune on real hardware**, especially pitch thresholds and retreat distance.

---

## Team

2 × EEE · 2 × CSE — MBCET
