# Hardware Build v2: ESP32 + L298N + MPU6050 + OLED — Terrain-Aware Rover

> **What changed from v1?**  
> The rover now has **two explicit operating modes** selectable from the WiFi dashboard or Serial:
> - **Training Mode** — you tell the rover the correct terrain; it logs labelled data.
> - **Testing Mode** — the on-board classifier guesses the terrain; you confirm or correct it; feedback is logged for future retraining.

---

## 1. Overview

Wire up the rover hardware (ESP32 DevKit V1 30-pin, L298N dual H-bridge, MPU6050 IMU, SSD1306 OLED, 2× DC motors) and flash firmware that:

1. Drives 2 motors (left / right) via L298N at configurable PWM
2. Reads MPU6050 accelerometer at 100 Hz
3. Computes vibration features (std, rms, p2p, zcr, speed) over 1-second windows
4. Displays live status on a 0.96″ OLED (mode, terrain, features, runtime)
5. Hosts a WiFi Access Point with a web dashboard for full control
6. Operates in **Training Mode** or **Testing Mode**, switchable at any time
7. Sends feature rows over Serial to the PC for offline logging / ML work

---

## 2. Wiring Diagram

### Power Supply

> [!IMPORTANT]
> The L298N requires a separate motor power supply (7–12 V battery). Do **not** power motors from the ESP32's 3.3 V or 5 V pin — it will brownout.

| What | Connection |
|------|-----------|
| **Battery +** (7–12 V) | L298N `+12V` terminal |
| **Battery −** | L298N `GND` terminal |
| L298N `5V` output (onboard regulator) | ESP32 `VIN` pin (**only if** the 5 V jumper on the L298N is in place) |
| L298N `GND` | ESP32 `GND` (**must share ground**) |

> [!NOTE]
> If you have a USB cable plugged into the ESP32 for Serial, it gets power from USB. In that case, remove the 5 V jumper on the L298N (don't feed 5 V back into VIN while USB is also powering it). Keep the GND connection.

---

### L298N → ESP32 (Motor Control)

| L298N Pin | ESP32 GPIO | Purpose |
|-----------|-----------|---------|
| `IN1` | **GPIO 27** | Left motor direction A |
| `IN2` | **GPIO 26** | Left motor direction B |
| `IN3` | **GPIO 25** | Right motor direction A |
| `IN4` | **GPIO 33** | Right motor direction B |
| `ENA` | **GPIO 14** | Left motor PWM speed (remove jumper!) |
| `ENB` | **GPIO 12** | Right motor PWM speed (remove jumper!) |

> [!WARNING]
> **Remove the ENA and ENB jumpers** on the L298N board. These jumpers lock the enable pins to HIGH (full speed). You must remove them and connect ENA/ENB to ESP32 PWM pins for variable speed control.

#### Motor terminal connections

| L298N Terminal | Wire to |
|---------------|---------|
| `OUT1` | Left motor terminal A |
| `OUT2` | Left motor terminal B |
| `OUT3` | Right motor terminal A |
| `OUT4` | Right motor terminal B |

> [!TIP]
> If a motor spins the wrong direction, swap its two terminal wires (e.g., swap OUT1↔OUT2).

---

### MPU6050 → ESP32 (I²C)

| MPU6050 Pin | ESP32 GPIO | Purpose |
|-------------|-----------|---------|
| `VCC` | **3V3** | Power (MPU6050 works at 3.3 V) |
| `GND` | **GND** | Ground |
| `SDA` | **GPIO 21** | I²C data (ESP32 default SDA) |
| `SCL` | **GPIO 22** | I²C clock (ESP32 default SCL) |
| `AD0` | **GND** (or leave unconnected) | I²C address = 0x68 |
| `INT` | Not connected | (optional, not used for polling) |

---

### SSD1306 OLED (0.96″, 128×64, I²C) → ESP32

The OLED **shares the same I²C bus** as the MPU6050 (different addresses: OLED = `0x3C`, MPU6050 = `0x68`).

| OLED Pin | ESP32 GPIO | Purpose |
|----------|-----------|--------|
| `VCC` | **3V3** | Power (3.3 V) |
| `GND` | **GND** | Ground |
| `SDA` | **GPIO 21** | I²C data (same wire as MPU6050) |
| `SCL` | **GPIO 22** | I²C clock (same wire as MPU6050) |

---

### Complete Wiring Summary

```
                    ┌──────────────┐
  Battery 7-12V ──▶│   L298N      │
  Battery GND   ──▶│              │
                    │  OUT1 ──▶ Left Motor A
                    │  OUT2 ──▶ Left Motor B
                    │  OUT3 ──▶ Right Motor A
                    │  OUT4 ──▶ Right Motor B
                    │              │
                    │  IN1  ◀── GPIO 27
                    │  IN2  ◀── GPIO 26
                    │  IN3  ◀── GPIO 25
                    │  IN4  ◀── GPIO 33
                    │  ENA  ◀── GPIO 14  (remove jumper!)
                    │  ENB  ◀── GPIO 12  (remove jumper!)
                    │  GND  ──▶ ESP32 GND (shared)
                    └──────────────┘

        I²C Bus (shared: GPIO 21 SDA, GPIO 22 SCL)
            ┌──────────────┐   ┌──────────────┐
            │   MPU6050    │   │  SSD1306     │
            │  addr: 0x68  │   │  OLED 0.96″  │
            │  VCC  ◀── 3V3│   │  addr: 0x3C  │
            │  GND  ◀── GND│   │  VCC  ◀── 3V3│
            │  SDA  ◀──┐   │   │  GND  ◀── GND│
            │  SCL  ◀─┐│   │   │  SDA  ◀──┐   │
            │  AD0  ◀─┼┼GND│   │  SCL  ◀─┐│   │
            └─────────┼┼───┘   └─────────┼┼───┘
                      ││                  ││
                      │└── GPIO 21 (SDA) ─┘│
                      └─── GPIO 22 (SCL) ──┘

                    ┌──────────────┐
          USB ──▶   │   ESP32      │  ◀── Serial to PC (data logging)
                    │  DevKit V1   │
                    │  WiFi AP     │  ◀── Phone/PC connects to dashboard
                    │  (30-pin)    │
                    └──────────────┘
```

---

## 3. The Two Operating Modes

### Mode 1 — Training Mode 🟦

**Purpose:** Collect labelled ground-truth data to build and improve the ML classifier.

**How it works:**
- The user selects the current terrain surface (Tile / Mat / Carpet / Gravel) via the WiFi dashboard or Serial command
- The rover drives forward; the firmware tags every feature window with the selected label
- Every labelled row is appended to `train_dataset.csv` on the PC (via Serial logger) and/or stored in a browser-downloadable session CSV on the dashboard
- The OLED shows `[TRAIN]` mode indicator and the currently selected terrain in large text

**Data flow:**
```
User selects "carpet" via dashboard
       ↓
ESP32 tags label = "carpet" on every 1s feature window
       ↓
Serial:  std,rms,p2p,zcr,speed,pwm,carpet
WS:      {"mode":"train","actual":"carpet","std":...}
       ↓
PC logger appends row to train_dataset.csv
```

---

### Mode 2 — Testing Mode 🟩

**Purpose:** Evaluate how well the classifier performs on real terrain, and collect corrective feedback for future retraining.

**How it works:**
1. Classifier runs on the ESP32 and **predicts** the terrain label every 1 second
2. The OLED and dashboard both show the predicted terrain prominently
3. The user taps **✓ YES** (prediction was correct) or **✗ NO** (prediction was wrong)
4. If **NO**, a terrain selector appears so the user can tap the **correct** terrain
5. Both the prediction and the correction (if any) are logged to `feedback_log.csv`

**Data flow:**
```
ESP32 classifier predicts "mat"
       ↓
OLED shows:  Predicted: MAT  [YES?] [NO?]
Dashboard shows same + big YES / NO buttons
       ↓
User taps NO → taps CARPET (the real terrain)
       ↓
Serial:  std,rms,p2p,zcr,speed,pwm,predicted=mat,actual=carpet,correct=0
WS:      {"mode":"test","predicted":"mat","actual":"carpet","correct":false}
       ↓
PC logger appends to feedback_log.csv
```

> [!IMPORTANT]
> Feedback rows where `correct=0` are the most valuable training signal — they are the cases where the model is wrong and needs improvement.

---

## 4. Firmware Architecture

### [`rover_firmware/rover_firmware.ino`](file:///c:/Users/sridh/OneDrive/Documents/terrain-aware/rover_firmware/rover_firmware.ino)

#### Global state variables

```cpp
// Mode
enum Mode { TRAINING, TESTING };
Mode currentMode = TRAINING;

// Labels
const char* TERRAINS[] = {"tile", "mat", "carpet", "gravel"};
String actualLabel    = "tile";   // user-selected (Training) or user-corrected (Testing)
String predictedLabel = "";       // classifier output (Testing only)
bool   feedbackGiven  = false;    // has user pressed YES or NO this window?
bool   predCorrect    = false;    // YES=true, NO=false

// IMU buffer
float accelBuf[100];
int   bufIdx = 0;
int   sampleCount = 0;

// Features (updated every 100 samples)
float feat_std, feat_rms, feat_p2p, feat_zcr, feat_speed;

// Motor
int  currentPwm  = 0;
bool motorsRunning = false;

// Recording
bool recording = false;
int  sampleLogged = 0;
```

#### Setup sequence

```
1. Serial.begin(115200)
2. Wire.begin()  →  MPU6050 init (±4 g, 100 Hz ODR)
3. SSD1306 OLED init  (addr 0x3C, 128×64)
4. L298N PWM channels init  (LEDC, 1 kHz, GPIO 14, 12)
5. WiFi.softAP("TerrainRover", "rover1234")
6. HTTP server: GET / → serve dashboard HTML (from dashboard.h)
7. WebSocket server: port 81
8. Show boot screen on OLED
```

#### Main loop (targets 100 Hz)

```
every iteration (~10 ms):
    read MPU6050 Z-accel → gravity-removed → push to accelBuf[bufIdx]
    bufIdx = (bufIdx+1) % 100
    sampleCount++

    if sampleCount == 100:
        sampleCount = 0
        compute_features()         // std, rms, p2p, zcr, speed
        if mode == TESTING:
            predictedLabel = classify()   // run classifier
            feedbackGiven  = false        // reset for this new window
        update_oled()
        broadcast_websocket()
        if recording:
            print_serial_row()
            sampleLogged++

    webSocket.loop()
    server.handleClient()
```

#### Feature computation (matches `terrain_sim.py`)

```cpp
void compute_features() {
    float mean = 0, sum_sq = 0, rms_sq = 0;
    float minV = accelBuf[0], maxV = accelBuf[0];
    int zcr = 0;
    for (int i = 0; i < 100; i++) {
        mean    += accelBuf[i];
        sum_sq  += accelBuf[i] * accelBuf[i];
        minV = min(minV, accelBuf[i]);
        maxV = max(maxV, accelBuf[i]);
        if (i > 0 && accelBuf[i-1] * accelBuf[i] < 0) zcr++;
    }
    mean   /= 100.0;
    feat_std   = sqrt((sum_sq / 100.0) - mean * mean);
    feat_rms   = sqrt(sum_sq / 100.0);
    feat_p2p   = maxV - minV;
    feat_zcr   = zcr;
    feat_speed = currentPwm * (15.0 / 255.0) * 0.035;
}
```

#### Classifier (Phase 1 → Phase 2)

| Phase | What | When |
|-------|------|------|
| **Phase 1 (stub)** | `predicted = actual` (always "correct" until model trained) | Before MATLAB classifier is ready |
| **Phase 2 (decision tree)** | Hard-coded if/else tree derived from MATLAB's trained model; runs fully on ESP32, no PC needed | After classifier training complete |

```cpp
// Phase 1 stub — predicted mirrors actual
String classify() { return actualLabel; }

// Phase 2 example — replace with real thresholds from MATLAB export
String classify() {
    if (feat_std < 0.05)  return "tile";
    if (feat_p2p > 0.8)   return "gravel";
    if (feat_zcr > 45)    return "carpet";
    return "mat";
}
```

> [!NOTE]
> The decision tree thresholds will be determined after running MATLAB's Classification Learner on `train_dataset.csv`. Export the best model's rules as C++ if/else branches.

---

#### Serial commands (still work alongside WiFi)

| Command | Effect |
|---------|--------|
| `MODE TRAIN` | Switch to Training Mode |
| `MODE TEST` | Switch to Testing Mode |
| `LABEL <name>` | Set actual terrain label (Training) or correction (Testing) |
| `PWM <value>` | Set motor speed (0–255) |
| `GO` | Start motors |
| `STOP` | Emergency stop |
| `REC ON` / `REC OFF` | Start / stop recording to Serial CSV |
| `CORRECT YES` | Mark last prediction as correct (Testing) |
| `CORRECT NO <label>` | Mark last prediction as wrong, provide actual (Testing) |

---

## 5. OLED Display Layouts

### Training Mode OLED (128×64)

```
┌────────────────────────────────┐
│ [TRAIN]          00:02:34      │  ← Mode badge + runtime
├────────────────────────────────┤
│ Surface:  CARPET               │  ← Currently selected terrain (large)
├────────────────────────────────┤
│ RMS: 0.141   ZCR: 57          │  ← Live vibration features
│ STD: 0.142   P2P: 1.37        │
├────────────────────────────────┤
│ PWM:180  0.29m/s  REC●  N:47  │  ← Motor, speed, recording, sample count
└────────────────────────────────┘
```

### Testing Mode OLED (128×64)

```
┌────────────────────────────────┐
│ [TEST]           00:05:10      │  ← Mode badge + runtime
├────────────────────────────────┤
│ Predicted: GRAVEL   ?          │  ← Model's guess (large) + awaiting feedback
├────────────────────────────────┤
│ RMS: 0.141   ZCR: 57          │  ← Live features
│ STD: 0.142   P2P: 1.37        │
├────────────────────────────────┤
│ PWM:180  0.29m/s  WiFi:1      │  ← Motor + connection info
└────────────────────────────────┘
```

**After feedback is given (Testing Mode, mismatch):**

```
┌────────────────────────────────┐
│ [TEST]           00:05:11      │
├────────────────────────────────┤
│ Predicted: GRAVEL  ✗           │  ← Wrong — inverted text (white on black)
│ Actual:    CARPET              │  ← User's correction shown below
├────────────────────────────────┤
│ RMS: 0.141   ZCR: 57          │
│ STD: 0.142   P2P: 1.37        │
├────────────────────────────────┤
│ PWM:180  0.29m/s  WiFi:1      │
└────────────────────────────────┘
```

**After feedback (correct prediction):**

```
┌────────────────────────────────┐
│ [TEST]           00:05:11      │
├────────────────────────────────┤
│ Predicted: CARPET  ✓           │  ← Correct — normal text
├────────────────────────────────┤
│ RMS: 0.141   ZCR: 57          │
│ STD: 0.142   P2P: 1.37        │
├────────────────────────────────┤
│ PWM:180  0.29m/s  WiFi:1      │
└────────────────────────────────┘
```

> [!NOTE]
> The `?` icon is shown for the **current window** while waiting for user feedback. It resets to `?` on every new 1-second window so the user always knows if the current prediction has been validated.

---

## 6. Web Dashboard

### [`rover_firmware/dashboard.h`](file:///c:/Users/sridh/OneDrive/Documents/terrain-aware/rover_firmware/dashboard.h)

HTML/CSS/JS embedded as a C string, served at `http://192.168.4.1`.

---

### Training Mode Dashboard Layout

```
┌─────────────────────────────────────────────────┐
│          🚗 TERRAIN-AWARE ROVER                 │
│           🟦 TRAINING MODE                      │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌─── SELECT TERRAIN SURFACE ─────────────────┐ │
│  │                                             │ │
│  │   [ 🪨 TILE ]   [ 🟫 MAT ]                  │ │
│  │   [ 🧶 CARPET ] [ ⚫ GRAVEL ]               │ │
│  │                                             │ │
│  │   Active: ● CARPET  (tap to change)         │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─── MOTOR CONTROL ─────────────────────────┐  │
│  │  PWM: ═════●═══════════════  [120]         │  │
│  │        0                255                │  │
│  │  [ ▶ GO ]                [ ⬛ STOP ]        │  │
│  │  Speed: 0.16 m/s                           │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─── LIVE VIBRATION FEATURES ───────────────┐  │
│  │  STD:  0.142  ████░░░░░░                   │  │
│  │  RMS:  0.141  ████░░░░░░                   │  │
│  │  P2P:  1.365  ██████████                   │  │
│  │  ZCR:  57     █████████░                   │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─── DATA LOGGING ─────────────────────────┐   │
│  │  [ ● REC ]  Recording...  47 samples      │   │
│  │  [ ⬇ Download CSV ]                       │   │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─── MODE SWITCHER ────────────────────────┐   │
│  │  [ 🟦 TRAINING (active) ] [ 🟩 TESTING ] │   │
│  └────────────────────────────────────────────┘  │
│                                                  │
│    Status: Connected ●  |  Uptime: 2m 34s        │
└─────────────────────────────────────────────────┘
```

---

### Testing Mode Dashboard Layout

```
┌─────────────────────────────────────────────────┐
│          🚗 TERRAIN-AWARE ROVER                 │
│           🟩 TESTING MODE                       │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌─── TERRAIN PREDICTION ─────────────────────┐ │
│  │                                             │ │
│  │     Rover thinks it's on:                   │ │
│  │                                             │ │
│  │            ⚫ GRAVEL                         │ │
│  │        (Confidence: 74%)                    │ │
│  │                                             │ │
│  │   ──────── Was that correct? ────────────   │ │
│  │                                             │ │
│  │        [ ✓ YES ]      [ ✗ NO ]             │ │
│  │                                             │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─── CORRECTION (shown only after NO) ───────┐  │
│  │  What was the actual terrain?               │  │
│  │   [ 🪨 TILE ]   [ 🟫 MAT ]                  │  │
│  │   [ 🧶 CARPET ] [ ⚫ GRAVEL ]               │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─── MOTOR CONTROL ─────────────────────────┐  │
│  │  PWM: ═════════●═══════════  [180]         │  │
│  │  [ ▶ GO ]                [ ⬛ STOP ]        │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─── LIVE VIBRATION FEATURES ───────────────┐  │
│  │  STD:  0.142  ████░░░░░░                   │  │
│  │  RMS:  0.141  ████░░░░░░                   │  │
│  │  P2P:  1.365  ██████████                   │  │
│  │  ZCR:  57     █████████░                   │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─── SESSION STATS ─────────────────────────┐  │
│  │  Total predictions:  63                    │  │
│  │  Correct (YES):      51  (81%)             │  │
│  │  Wrong   (NO):       12  (19%)             │  │
│  │  [ ⬇ Download feedback_log.csv ]          │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─── MODE SWITCHER ────────────────────────┐   │
│  │  [ 🟦 TRAINING ] [ 🟩 TESTING (active) ] │   │
│  └────────────────────────────────────────────┘  │
│                                                  │
│    Status: Connected ●  |  Uptime: 5m 10s        │
└─────────────────────────────────────────────────┘
```

---

## 7. WebSocket Protocol

### ESP32 → Dashboard (every 1 s)

**Training Mode:**
```json
{
  "mode": "train",
  "actual": "carpet",
  "std":   0.142,
  "rms":   0.141,
  "p2p":   1.365,
  "zcr":   57,
  "speed": 0.163,
  "pwm":   120,
  "uptime": 154,
  "samples_logged": 47
}
```

**Testing Mode:**
```json
{
  "mode":      "test",
  "predicted": "gravel",
  "confidence": 0.74,
  "actual":    "carpet",
  "correct":   false,
  "feedback_pending": false,
  "std":   0.142,
  "rms":   0.141,
  "p2p":   1.365,
  "zcr":   57,
  "speed": 0.288,
  "pwm":   180,
  "uptime": 310,
  "total_predictions": 63,
  "total_correct": 51
}
```

> `feedback_pending: true` means the current window has not yet been confirmed by the user.  
> `actual` in Testing Mode is the user-corrected label (empty string if no correction given yet).

---

### Dashboard → ESP32 (on user interaction)

```json
{"cmd": "mode",    "value": "train"}
{"cmd": "mode",    "value": "test"}
{"cmd": "label",   "value": "carpet"}
{"cmd": "pwm",     "value": 200}
{"cmd": "go"}
{"cmd": "stop"}
{"cmd": "rec",     "value": true}
{"cmd": "rec",     "value": false}
{"cmd": "feedback","correct": true}
{"cmd": "feedback","correct": false, "actual": "carpet"}
```

---

## 8. Output File Schemas

### `train_dataset.csv` (Training Mode output)

Logged from Serial by `collect_data.py`, or downloaded from dashboard after a session.

```
std,rms,p2p,zcr,speed,pwm,label,timestamp_ms
0.142,0.141,1.365,57,0.163,120,carpet,154023
0.138,0.137,1.310,54,0.163,120,carpet,155041
...
```

| Column | Description |
|--------|-------------|
| `std` | Standard deviation of 100-sample window |
| `rms` | Root mean square of window |
| `p2p` | Peak-to-peak (max − min) |
| `zcr` | Zero-crossing rate (sign changes in window) |
| `speed` | Derived from PWM: `pwm × (15/255) × 0.035` |
| `pwm` | Current motor PWM value |
| `label` | User-selected terrain name |
| `timestamp_ms` | millis() since boot |

---

### `feedback_log.csv` (Testing Mode output)

```
std,rms,p2p,zcr,speed,pwm,predicted,actual,correct,timestamp_ms
0.142,0.141,1.365,57,0.288,180,gravel,carpet,0,310041
0.139,0.138,1.320,55,0.288,180,carpet,carpet,1,311058
...
```

| Column | Description |
|--------|-------------|
| `predicted` | Classifier's terrain guess |
| `actual` | User-confirmed terrain (same as `predicted` if `correct=1`, user-supplied correction if `correct=0`) |
| `correct` | `1` = YES (prediction was right), `0` = NO (prediction was wrong) |

> [!TIP]
> Rows where `correct=0` should be merged into your training dataset to retrain the classifier. This is the **active learning** loop: the model improves the more you use Testing Mode and correct its mistakes.

---

## 9. Data Collection Script

### [`rover_firmware/collect_data.py`](file:///c:/Users/sridh/OneDrive/Documents/terrain-aware/rover_firmware/collect_data.py)

Python script running on PC. Connects to ESP32 via Serial (COM port). Automatically splits incoming rows into the correct file based on mode prefix in each Serial line.

**Serial line formats:**

```
# Training Mode
TRAIN,std,rms,p2p,zcr,speed,pwm,label,timestamp_ms

# Testing Mode
TEST,std,rms,p2p,zcr,speed,pwm,predicted,actual,correct,timestamp_ms
```

The script appends Training lines to `train_dataset.csv` and Testing lines to `feedback_log.csv`.

**CLI usage:**

```bash
python collect_data.py --port COM5 --baud 115200
```

---

## 10. Arduino Libraries Required

| Library | Install via | Purpose |
|---------|-----------|---------|-|
| `WiFi.h` | Built-in (ESP32 core) | WiFi Access Point |
| `WebServer.h` | Built-in (ESP32 core) | HTTP server for dashboard |
| `WebSocketsServer.h` | Library Manager → "WebSockets" by Markus Sattler | Real-time bidirectional comms |
| `Wire.h` | Built-in | I²C for MPU6050 + OLED |
| `Adafruit_SSD1306.h` | Library Manager → "Adafruit SSD1306" | OLED display driver |
| `Adafruit_GFX.h` | Auto-installed with SSD1306 | Graphics primitives |
| `ArduinoJson.h` | Library Manager → "ArduinoJson" by Benoît Blanchon | JSON serialize/deserialize |

---

## 11. Files to Create

| File | Purpose |
|------|---------|
| `rover_firmware/rover_firmware.ino` | Main sketch — IMU, OLED, motors, WiFi AP, WebSocket, dual-mode logic |
| `rover_firmware/dashboard.h` | Embedded HTML/CSS/JS for the web dashboard (C string) |
| `rover_firmware/collect_data.py` | PC-side Serial logger; splits rows into `train_dataset.csv` and `feedback_log.csv` |

---

## 12. Phased Build Sequence

### Phase 1 — Hardware Bring-Up
1. Wire ESP32 + L298N + MPU6050 + OLED per wiring diagram
2. Flash minimal sketch: read MPU6050, print raw Z-accel to Serial, confirm non-zero values
3. Test OLED: boot message, runtime counter
4. Test motors: both spin forward at PWM 150, stop on command

### Phase 2 — Feature Extraction
5. Implement 100-sample circular buffer + feature computation (std, rms, p2p, zcr, speed)
6. Print feature CSV rows to Serial in Training format
7. Confirm values match `terrain_sim.py` output for same terrain conditions

### Phase 3 — WiFi + Dashboard (Phase 1 classifier stub)
8. Start WiFi AP (`TerrainRover` / `rover1234`)
9. Serve `dashboard.h` on HTTP port 80
10. Open WebSocket on port 81
11. Implement **Training Mode** dashboard panel (terrain selector, motor control, live gauges, REC/Download)
12. Implement **Testing Mode** dashboard panel (prediction display, YES/NO buttons, correction selector, session stats)
13. Connect OLED layouts to current mode

### Phase 4 — Data Collection Run
14. Run `collect_data.py` on PC
15. Drive rover on each terrain surface using Training Mode; collect ≥100 rows per terrain × PWM level
16. Export `train_dataset.csv`
17. Train classifier in MATLAB's Classification Learner; pick best algorithm (target > 85% accuracy)

### Phase 5 — Deploy Classifier to ESP32
18. Export winning model's decision rules as C++ if/else tree
19. Replace Phase 1 stub `classify()` function with real thresholds
20. Flash updated firmware
21. Switch to Testing Mode; drive rover on each surface and measure real-world accuracy
22. Correct wrong predictions via dashboard → `feedback_log.csv`
23. Merge `feedback_log.csv` corrections into `train_dataset.csv` and retrain if needed

---

## 13. Open Questions

> [!IMPORTANT]
> **GPIO 12 caution**: On some ESP32 boards, GPIO 12 is a strapping pin. If the board fails to boot with ENB connected to GPIO 12, switch ENB to **GPIO 13** instead.

> [!NOTE]
> **Motor voltage**: What voltage battery are you using? (e.g., 2S LiPo = 7.4 V, 3S = 11.1 V, 4× AA = 6 V). This affects whether the L298N's onboard 5 V regulator is active (needs > 7 V input).

> [!NOTE]
> **Classifier deployment (Phase 5)**: After training in MATLAB, do you want to:
> - **(A)** Hard-code the decision tree directly on the ESP32 (no PC needed, fully autonomous)
> - **(B)** Send features to a PC Python script running the sklearn/MATLAB model (easier to iterate)
>
> Recommendation: start with **B** for Testing Mode (quick to iterate), then move to **A** once the model is stable.

---

## 14. Verification Checklist

### Hardware
- [ ] Both motors spin forward on `GO` at PWM 150
- [ ] OLED shows boot screen and runtime counting up
- [ ] MPU6050 Z-accel shows spikes when physically tapping the board
- [ ] Phone connects to `TerrainRover` WiFi and dashboard loads at `http://192.168.4.1`
- [ ] WebSocket connects (green dot in dashboard status bar)

### Training Mode
- [ ] Tap each terrain button on dashboard → OLED "Surface:" row updates correctly
- [ ] Slide PWM → motor speed changes in real-time
- [ ] Tap REC → Serial rows appear in correct format → `collect_data.py` writes to `train_dataset.csv`
- [ ] Download CSV from dashboard → file contains correct terrain labels

### Testing Mode
- [ ] Dashboard shows a predicted terrain every 1 second
- [ ] YES button logs `correct=1` row → serial confirms
- [ ] NO button reveals correction panel → tapping a terrain logs `correct=0,actual=<chosen>` row
- [ ] Session stats (Total / Correct / Wrong %) update correctly
- [ ] OLED shows ✓ after YES, ✗ + actual after NO
- [ ] Download `feedback_log.csv` → file contains `predicted`, `actual`, `correct` columns
- [ ] `collect_data.py` correctly routes Testing rows to `feedback_log.csv`

### Classifier (Phase 5)
- [ ] Hard-coded decision tree returns plausible terrain for known features
- [ ] Confidence value in JSON is non-zero and ≤ 1.0
- [ ] Misclassified samples (correct=0) can be merged back into training data and retrained
