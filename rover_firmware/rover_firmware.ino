/*
 * rover_firmware.ino
 * Terrain-Aware Rover — ESP32 firmware (v2)
 *
 * Chassis: 3-wheel differential drive
 *   - Rear-LEFT  yellow TT DC motor  (L298N channel A)
 *   - Rear-RIGHT yellow TT DC motor  (L298N channel B)
 *   - Front      free-swivelling caster wheel (no motor)
 *
 * Steering is achieved by differential PWM:
 *   - Forward / Backward : both motors same speed, same direction
 *   - Turn Left          : right motor faster (or left slower / reverse)
 *   - Turn Right         : left motor faster  (or right slower / reverse)
 *   - Spin in place      : motors same speed, opposite directions
 *
 * Two operating modes:
 *   TRAINING — user selects terrain label; features tagged and logged.
 *   TESTING  — classifier guesses terrain; user confirms YES / corrects NO.
 *
 * Hardware:
 *   ESP32 DevKit V1 (30-pin)
 *   L298N dual H-bridge  → GPIO 27,26 (IN1/IN2 left), GPIO 25,33 (IN3/IN4 right)
 *                          GPIO 14 (ENA left PWM), GPIO 12 (ENB right PWM)
 *   MPU6050 IMU          → I²C GPIO 21 (SDA), GPIO 22 (SCL), addr 0x68
 *   SSD1306 OLED 128×64  → I²C GPIO 21 (SDA), GPIO 22 (SCL), addr 0x3C
 *
 * Libraries required (install via Arduino Library Manager):
 *   - WebSockets by Markus Sattler
 *   - Adafruit SSD1306
 *   - Adafruit GFX Library
 *   - ArduinoJson by Benoît Blanchon
 *   (WiFi.h, WebServer.h, Wire.h are built-in to ESP32 core)
 */

#include <Wire.h>
#include <WiFi.h>
#include <WebServer.h>
#include <WebSocketsServer.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include "dashboard.h"
#include "terrain_classifier.h"

// ═══════════════════════════════════════════════════════════════════════════════
// WiFi Access Point credentials
// ═══════════════════════════════════════════════════════════════════════════════
const char* AP_SSID     = "TerrainRover";
const char* AP_PASSWORD = "rover1234";

// ═══════════════════════════════════════════════════════════════════════════════
// L298N motor driver pins
// Chassis: rear-LEFT = channel A, rear-RIGHT = channel B
//          front caster wheel is passive (no motor connection)
// ═══════════════════════════════════════════════════════════════════════════════
#define PIN_IN1  27   // Rear-LEFT  motor direction A
#define PIN_IN2  26   // Rear-LEFT  motor direction B
#define PIN_IN3  25   // Rear-RIGHT motor direction A
#define PIN_IN4  33   // Rear-RIGHT motor direction B
#define PIN_ENA  14   // Rear-LEFT  motor PWM speed  (ENA jumper MUST be removed)
#define PIN_ENB  13   // Rear-RIGHT motor PWM speed  (ENB jumper MUST be removed; moved from GPIO12)
//   NOTE: if ESP32 fails to boot with ENB on GPIO12, move ENB to GPIO13.

// LEDC (v3.x API — ledcAttach uses pin directly, no channel numbers needed)
#define LEDC_FREQ_HZ   1000
#define LEDC_BITS      8

// ═══════════════════════════════════════════════════════════════════════════════
// OLED
// ═══════════════════════════════════════════════════════════════════════════════
#define OLED_ADDR  0x3C
#define SCREEN_W   128
#define SCREEN_H   64
Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);

// ═══════════════════════════════════════════════════════════════════════════════
// MPU6050
// ═══════════════════════════════════════════════════════════════════════════════
#define MPU_ADDR  0x68

// ═══════════════════════════════════════════════════════════════════════════════
// Mode
// ═══════════════════════════════════════════════════════════════════════════════
enum RoverMode { TRAINING, TESTING };
RoverMode currentMode = TRAINING;

// ═══════════════════════════════════════════════════════════════════════════════
// Terrain labels
// ═══════════════════════════════════════════════════════════════════════════════
String actualLabel    = "tile";   // ground-truth: user-selected (TRAIN) or corrected (TEST)
String predictedLabel = "tile";   // classifier output (TEST only)
bool   feedbackGiven  = false;    // has user confirmed this window yet?
bool   predCorrect    = false;    // YES → true, NO → false

// ═══════════════════════════════════════════════════════════════════════════════
// IMU circular buffer  (1 second @ 100 Hz)
// ═══════════════════════════════════════════════════════════════════════════════
#define WIN_SIZE 100
float accelBuf[WIN_SIZE];
int   bufIdx      = 0;
int   sampleCount = 0;

// ═══════════════════════════════════════════════════════════════════════════════
// Features — updated every WIN_SIZE samples
// ═══════════════════════════════════════════════════════════════════════════════
float feat_std   = 0.0f;
float feat_rms   = 0.0f;
float feat_p2p   = 0.0f;
float feat_zcr   = 0.0f;
float feat_speed = 0.0f;

// ═══════════════════════════════════════════════════════════════════════════════
// Motor state
// ═══════════════════════════════════════════════════════════════════════════════
int  currentPwm    = 0;
bool motorsRunning = false;

// ═══════════════════════════════════════════════════════════════════════════════
// Data logging
// ═══════════════════════════════════════════════════════════════════════════════
bool recording     = false;
int  samplesLogged = 0;

// ═══════════════════════════════════════════════════════════════════════════════
// Testing mode statistics
// ═══════════════════════════════════════════════════════════════════════════════
int totalPredictions = 0;
int totalCorrect     = 0;

// ═══════════════════════════════════════════════════════════════════════════════
// Servers
// ═══════════════════════════════════════════════════════════════════════════════
WebServer        httpServer(80);
WebSocketsServer wsServer(81);

// ═══════════════════════════════════════════════════════════════════════════════
// Timing
// ═══════════════════════════════════════════════════════════════════════════════
unsigned long lastSampleUs = 0;
unsigned long bootMs       = 0;


// ─────────────────────────────────────────────────────────────────────────────
// MPU6050 helpers
// ─────────────────────────────────────────────────────────────────────────────
void initMPU6050() {
    // Wake up
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x6B);  // PWR_MGMT_1
    Wire.write(0x00);  // clear sleep bit
    Wire.endTransmission(true);

    // Set accelerometer range to ±4g (AFS_SEL = 1)
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x1C);  // ACCEL_CONFIG
    Wire.write(0x08);  // AFS_SEL = 1 → ±4g, LSB = 8192
    Wire.endTransmission(true);

    // Set DLPF to ~94 Hz bandwidth (CONFIG register)
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x1A);  // CONFIG
    Wire.write(0x02);  // DLPF_CFG = 2 → 94 Hz BW
    Wire.endTransmission(true);

    // Set sample rate divider: ODR = 1000 / (1 + SMPLRT_DIV) → 100 Hz
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x19);  // SMPLRT_DIV
    Wire.write(0x09);  // 1000/(1+9) = 100 Hz
    Wire.endTransmission(true);
}

float readAccelZ() {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x3F);  // ACCEL_ZOUT_H
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)2, (uint8_t)true);
    int16_t raw = ((int16_t)Wire.read() << 8) | Wire.read();
    float g = raw / 8192.0f;  // ±4g range
    return g - 1.0f;           // remove 1g gravity bias (sensor faces up)
}


// ─────────────────────────────────────────────────────────────────────────────
// Feature computation  (identical formulas to terrain_sim.py)
// ─────────────────────────────────────────────────────────────────────────────
void computeFeatures() {
    float sum   = 0.0f;
    float sumSq = 0.0f;
    float minV  = accelBuf[0];
    float maxV  = accelBuf[0];
    int   zcr   = 0;

    for (int i = 0; i < WIN_SIZE; i++) {
        sum   += accelBuf[i];
        sumSq += accelBuf[i] * accelBuf[i];
        if (accelBuf[i] < minV) minV = accelBuf[i];
        if (accelBuf[i] > maxV) maxV = accelBuf[i];
        if (i > 0 && accelBuf[i-1] * accelBuf[i] < 0.0f) zcr++;
    }

    float mean = sum / (float)WIN_SIZE;
    feat_std   = sqrtf((sumSq / (float)WIN_SIZE) - (mean * mean));
    feat_rms   = sqrtf(sumSq / (float)WIN_SIZE);
    feat_p2p   = maxV - minV;
    feat_zcr   = (float)zcr;
    // MuJoCo-calibrated: speed_ms = PWM_SPEED_SLOPE * pwm + PWM_SPEED_INTERCEPT
    feat_speed = pwmToSpeed(currentPwm);
}


// ─────────────────────────────────────────────────────────────────────────────
// On-board classifier
// ─────────────────────────────────────────────────────────────────────────────
//
// PHASE 1 (stub): threshold-based placeholder.
//   Replace with real if/else tree from MATLAB after training.
//
// PHASE 2: Export the MATLAB Classification Learner model as a decision tree,
//   translate each split into C++ if/else blocks, paste below.
//
// classify() now delegates to the MuJoCo-trained decision tree in terrain_classifier.h.
// g_last_confidence is set as a side-effect before the function returns.
String classify() {
    return classifyTerrain();
}

// classifyConfidence() returns the leaf-node confidence from the last classify() call.
// g_last_confidence is written by classifyTerrain() in terrain_classifier.h.
float classifyConfidence() {
    return g_last_confidence;
}


// ─────────────────────────────────────────────────────────────────────────────
// Motor control — differential drive (3-wheel chassis)
//
// Layout (top view):
//
//        [caster wheel]  ← front, swivels freely
//
//   [LEFT motor] ... [RIGHT motor]  ← rear drive wheels
//
// Differential steering:
//   Forward  — both motors forward, same PWM
//   Backward — both motors backward, same PWM
//   Turn L   — right faster (or left reversed)
//   Turn R   — left faster  (or right reversed)
//   Spin     — opposite directions, same PWM
// ─────────────────────────────────────────────────────────────────────────────

// Set individual motor: positive pwm = forward, negative = backward, 0 = stop
void setLeftMotor(int pwm) {
    bool fwd = (pwm >= 0);
    int  spd = abs(pwm);
    digitalWrite(PIN_IN1, fwd ? HIGH : LOW);
    digitalWrite(PIN_IN2, fwd ? LOW  : HIGH);
    analogWrite(PIN_ENA, constrain(spd, 0, 255));
}

void setRightMotor(int pwm) {
    bool fwd = (pwm >= 0);
    int  spd = abs(pwm);
    digitalWrite(PIN_IN3, fwd ? HIGH : LOW);
    digitalWrite(PIN_IN4, fwd ? LOW  : HIGH);
    analogWrite(PIN_ENB, constrain(spd, 0, 255));
}

// Drive both motors — same PWM, same direction (forward/backward)
void setMotors(int pwm, bool forward) {
    int v = forward ? pwm : -pwm;
    setLeftMotor(v);
    setRightMotor(v);
}

// Turn: reduce inner wheel, keep outer at full PWM
// direction: -1 = turn left, +1 = turn right
void turnMotors(int pwm, int direction) {
    // inner wheel gets 40% of outer to produce a smooth arc
    int outer = pwm;
    int inner = pwm * 4 / 10;
    if (direction < 0) {          // turn left: slow down left motor
        setLeftMotor(inner);
        setRightMotor(outer);
    } else {                      // turn right: slow down right motor
        setLeftMotor(outer);
        setRightMotor(inner);
    }
}

// Spin in place (left motor back, right motor forward)
void spinMotors(int pwm, int direction) {
    if (direction < 0) {          // spin left
        setLeftMotor(-pwm);
        setRightMotor(pwm);
    } else {                      // spin right
        setLeftMotor(pwm);
        setRightMotor(-pwm);
    }
}

void stopMotors() {
    motorsRunning = false;
    setLeftMotor(0);
    setRightMotor(0);
}


// ─────────────────────────────────────────────────────────────────────────────
// Serial row output
// ─────────────────────────────────────────────────────────────────────────────
//
// TRAIN row: TRAIN,std,rms,p2p,zcr,speed,pwm,label,timestamp_ms
// TEST  row: TEST,std,rms,p2p,zcr,speed,pwm,predicted,actual,correct,timestamp_ms
//
void printSerialRow() {
    if (currentMode == TRAINING) {
        Serial.printf("TRAIN,%.4f,%.4f,%.4f,%.0f,%.4f,%d,%s,%lu\n",
            feat_std, feat_rms, feat_p2p, feat_zcr, feat_speed,
            currentPwm, actualLabel.c_str(), millis());
    } else {
        Serial.printf("TEST,%.4f,%.4f,%.4f,%.0f,%.4f,%d,%s,%s,%d,%lu\n",
            feat_std, feat_rms, feat_p2p, feat_zcr, feat_speed,
            currentPwm,
            predictedLabel.c_str(),
            actualLabel.c_str(),
            predCorrect ? 1 : 0,
            millis());
    }
}


// ─────────────────────────────────────────────────────────────────────────────
// WebSocket broadcast  (every feature window + on command)
// ─────────────────────────────────────────────────────────────────────────────
void broadcastState() {
    StaticJsonDocument<512> doc;
    doc["mode"]           = (currentMode == TRAINING) ? "train" : "test";
    doc["std"]            = feat_std;
    doc["rms"]            = feat_rms;
    doc["p2p"]            = feat_p2p;
    doc["zcr"]            = feat_zcr;
    doc["speed"]          = feat_speed;
    doc["pwm"]            = currentPwm;
    doc["uptime"]         = (millis() - bootMs) / 1000UL;
    doc["samples_logged"] = samplesLogged;
    doc["running"]        = motorsRunning;

    if (currentMode == TRAINING) {
        doc["actual"] = actualLabel;

    } else {
        doc["predicted"]         = predictedLabel;
        doc["confidence"]        = classifyConfidence();
        doc["actual"]            = actualLabel;
        doc["correct"]           = predCorrect;
        doc["feedback_pending"]  = !feedbackGiven;
        doc["total_predictions"] = totalPredictions;
        doc["total_correct"]     = totalCorrect;
    }

    String json;
    serializeJson(doc, json);
    wsServer.broadcastTXT(json);
}


// ─────────────────────────────────────────────────────────────────────────────
// OLED update
// ─────────────────────────────────────────────────────────────────────────────
void updateOLED() {
    unsigned long upSec = (millis() - bootMs) / 1000UL;
    int hh = upSec / 3600;
    int mm = (upSec % 3600) / 60;
    int ss = upSec % 60;

    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);

    // ── Row 1: mode badge + runtime ──────────────────────────────────────────
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.print(currentMode == TRAINING ? "[TRAIN]" : "[TEST] ");
    char timeBuf[10];
    snprintf(timeBuf, sizeof(timeBuf), "%02d:%02d:%02d", hh, mm, ss);
    display.setCursor(72, 0);
    display.print(timeBuf);
    display.drawLine(0, 9, 127, 9, SSD1306_WHITE);

    // ── Row 2–3: terrain / prediction ────────────────────────────────────────
    if (currentMode == TRAINING) {
        display.setCursor(0, 12);
        display.print("Surface:");
        display.setTextSize(2);
        String lbl = actualLabel;
        lbl.toUpperCase();
        display.setCursor(0, 21);
        display.print(lbl);
        display.setTextSize(1);

    } else {
        display.setCursor(0, 12);
        display.print("Predicted:");
        display.setTextSize(2);
        String lbl = predictedLabel;
        lbl.toUpperCase();
        display.setCursor(0, 21);
        display.print(lbl);
        display.setTextSize(1);

        if (!feedbackGiven) {
            // Awaiting feedback
            display.setCursor(112, 21);
            display.print("?");
        } else if (predCorrect) {
            display.setCursor(108, 21);
            display.print("\x18");  // up-arrow as checkmark proxy
        } else {
            // Mismatch: invert block for predicted, show actual below
            display.fillRect(108, 20, 20, 13, SSD1306_WHITE);
            display.setTextColor(SSD1306_BLACK);
            display.setCursor(111, 23);
            display.print("X");
            display.setTextColor(SSD1306_WHITE);
            display.setCursor(0, 35);
            display.print("Act:");
            String actLbl = actualLabel;
            actLbl.toUpperCase();
            display.print(actLbl);
        }
    }

    display.drawLine(0, 37, 127, 37, SSD1306_WHITE);

    // ── Row 4–5: vibration features ──────────────────────────────────────────
    display.setCursor(0, 39);
    char fbuf[32];
    snprintf(fbuf, sizeof(fbuf), "RMS:%.3f  ZCR:%.0f", feat_rms, feat_zcr);
    display.print(fbuf);
    display.setCursor(0, 47);
    snprintf(fbuf, sizeof(fbuf), "STD:%.3f  P2P:%.2f", feat_std, feat_p2p);
    display.print(fbuf);

    display.drawLine(0, 55, 127, 55, SSD1306_WHITE);

    // ── Row 6: bottom status bar ─────────────────────────────────────────────
    display.setCursor(0, 57);
    snprintf(fbuf, sizeof(fbuf), "PWM:%3d %.2fm/s", currentPwm, feat_speed);
    display.print(fbuf);
    if (currentMode == TRAINING && recording) {
        display.setCursor(106, 57);
        display.print("REC");
    } else {
        int clients = wsServer.connectedClients();
        display.setCursor(108, 57);
        char cbuf[8];
        snprintf(cbuf, sizeof(cbuf), "W:%d", clients);
        display.print(cbuf);
    }

    display.display();
}


// ─────────────────────────────────────────────────────────────────────────────
// WebSocket event handler
// ─────────────────────────────────────────────────────────────────────────────
void onWebSocketEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
    if (type != WStype_TEXT) return;

    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) return;

    const char* cmd = doc["cmd"] | "";

    if (strcmp(cmd, "mode") == 0) {
        const char* val = doc["value"] | "";
        if (strcmp(val, "train") == 0) currentMode = TRAINING;
        else if (strcmp(val, "test") == 0) currentMode = TESTING;
        feedbackGiven = false;

    } else if (strcmp(cmd, "label") == 0) {
        const char* val = doc["value"] | "";
        if (strlen(val) > 0) actualLabel = String(val);

    } else if (strcmp(cmd, "pwm") == 0) {
        currentPwm = constrain((int)doc["value"], 0, 255);
        if (motorsRunning) setMotors(currentPwm, true);

    } else if (strcmp(cmd, "go") == 0) {
        motorsRunning = true;
        if (currentPwm == 0) currentPwm = 150;
        setMotors(currentPwm, true);

    } else if (strcmp(cmd, "stop") == 0) {
        stopMotors();

    } else if (strcmp(cmd, "turn") == 0) {
        // {"cmd":"turn","dir":"left"|"right"}
        const char* dir = doc["dir"] | "left";
        int d = (strcmp(dir, "left") == 0) ? -1 : 1;
        motorsRunning = true;
        if (currentPwm == 0) currentPwm = 150;
        turnMotors(currentPwm, d);

    } else if (strcmp(cmd, "spin") == 0) {
        // {"cmd":"spin","dir":"left"|"right"}
        const char* dir = doc["dir"] | "left";
        int d = (strcmp(dir, "left") == 0) ? -1 : 1;
        motorsRunning = true;
        if (currentPwm == 0) currentPwm = 150;
        spinMotors(currentPwm, d);

    } else if (strcmp(cmd, "rec") == 0) {
        recording = (bool)doc["value"];
        if (!recording) samplesLogged = 0;

    } else if (strcmp(cmd, "feedback") == 0) {
        // Testing mode: user pressed YES or NO
        bool correct = (bool)doc["correct"];
        feedbackGiven = true;
        predCorrect   = correct;
        totalPredictions++;
        if (correct) {
            actualLabel = predictedLabel;
            totalCorrect++;
        } else {
            const char* act = doc["actual"] | "";
            if (strlen(act) > 0) actualLabel = String(act);
        }
        // Log this row immediately on feedback (Testing mode)
        if (recording) {
            printSerialRow();
            samplesLogged++;
        }
    }

    updateOLED();
    broadcastState();
}


// ─────────────────────────────────────────────────────────────────────────────
// Serial command parser (PC control fallback)
// ─────────────────────────────────────────────────────────────────────────────
void handleSerial() {
    if (!Serial.available()) return;
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) return;

    if      (line == "MODE TRAIN")           { currentMode = TRAINING; feedbackGiven = false; }
    else if (line == "MODE TEST")            { currentMode = TESTING;  feedbackGiven = false; }
    else if (line.startsWith("LABEL "))      { actualLabel = line.substring(6); }
    else if (line.startsWith("PWM ")) {
        currentPwm = constrain(line.substring(4).toInt(), 0, 255);
        if (motorsRunning) setMotors(currentPwm, true);
    }
    else if (line == "GO") {
        motorsRunning = true;
        if (currentPwm == 0) currentPwm = 150;
        setMotors(currentPwm, true);
    }
    else if (line == "BACK") {
        motorsRunning = true;
        if (currentPwm == 0) currentPwm = 150;
        setMotors(currentPwm, false);
    }
    else if (line == "TURN LEFT")  { motorsRunning=true; if(!currentPwm) currentPwm=150; turnMotors(currentPwm,-1); }
    else if (line == "TURN RIGHT") { motorsRunning=true; if(!currentPwm) currentPwm=150; turnMotors(currentPwm, 1); }
    else if (line == "SPIN LEFT")  { motorsRunning=true; if(!currentPwm) currentPwm=150; spinMotors(currentPwm,-1); }
    else if (line == "SPIN RIGHT") { motorsRunning=true; if(!currentPwm) currentPwm=150; spinMotors(currentPwm, 1); }
    else if (line == "STOP")       { stopMotors(); }
    else if (line == "REC ON")               { recording = true; }
    else if (line == "REC OFF")              { recording = false; samplesLogged = 0; }
    else if (line == "CORRECT YES") {
        feedbackGiven = true; predCorrect = true;
        actualLabel = predictedLabel;
        totalPredictions++; totalCorrect++;
        if (recording) { printSerialRow(); samplesLogged++; }
    }
    else if (line.startsWith("CORRECT NO ")) {
        feedbackGiven = true; predCorrect = false;
        actualLabel = line.substring(11);
        totalPredictions++;
        if (recording) { printSerialRow(); samplesLogged++; }
    }
    else if (line == "STATUS") {
        Serial.printf("Mode:%s Actual:%s Predicted:%s PWM:%d Running:%d Rec:%d\n",
            currentMode == TRAINING ? "TRAIN" : "TEST",
            actualLabel.c_str(), predictedLabel.c_str(),
            currentPwm, motorsRunning, recording);
    }

    updateOLED();
    broadcastState();
}


// ─────────────────────────────────────────────────────────────────────────────
// setup()
// ─────────────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Wire.begin();

    // ── MPU6050 ──────────────────────────────────────────────────────────────
    initMPU6050();
    Serial.println("[MPU6050] initialised");

    // ── OLED ─────────────────────────────────────────────────────────────────
    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
        Serial.println("[OLED] ERROR: SSD1306 not found at 0x3C");
    } else {
        Serial.println("[OLED] initialised");
    }
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(8, 14); display.print("TERRAIN-AWARE ROVER");
    display.setCursor(28, 28); display.print("Initialising...");
    display.display();

    // ── Motor pins ───────────────────────────────────────────────────────────
    pinMode(PIN_IN1, OUTPUT); pinMode(PIN_IN2, OUTPUT);
    pinMode(PIN_IN3, OUTPUT); pinMode(PIN_IN4, OUTPUT);
    pinMode(PIN_ENA, OUTPUT); pinMode(PIN_ENB, OUTPUT);
    stopMotors();
    Serial.println("[MOTORS] initialised");

    // ── WiFi Access Point ─────────────────────────────────────────────────────
    WiFi.softAP(AP_SSID, AP_PASSWORD);
    IPAddress ip = WiFi.softAPIP();
    Serial.printf("[WiFi] AP started: SSID=%s  IP=%s\n", AP_SSID, ip.toString().c_str());

    // ── HTTP server ───────────────────────────────────────────────────────────
    httpServer.on("/", []() {
        httpServer.send_P(200, "text/html", DASHBOARD_HTML);
    });
    httpServer.begin();
    Serial.println("[HTTP] server started on port 80");

    // ── WebSocket server ──────────────────────────────────────────────────────
    wsServer.begin();
    wsServer.onEvent(onWebSocketEvent);
    Serial.println("[WS] server started on port 81");

    bootMs = millis();

    // ── Boot screen ───────────────────────────────────────────────────────────
    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(8,  10); display.print("TERRAIN-AWARE ROVER");
    display.setCursor(0,  24); display.print("WiFi: TerrainRover");
    display.setCursor(0,  34); display.print("Pass: rover1234");
    display.setCursor(0,  44); display.print("Dash: 192.168.4.1");
    display.setCursor(0,  54); display.print("Mode: TRAINING");
    display.display();
    delay(3000);
    Serial.println("[BOOT] Ready");
}


// ─────────────────────────────────────────────────────────────────────────────
// loop()
// ─────────────────────────────────────────────────────────────────────────────
void loop() {
    wsServer.loop();
    httpServer.handleClient();
    handleSerial();

    // ── IMU sampling at 100 Hz ───────────────────────────────────────────────
    unsigned long nowUs = micros();
    if (nowUs - lastSampleUs >= 10000UL) {   // 10 000 µs = 10 ms = 100 Hz
        lastSampleUs = nowUs;

        accelBuf[bufIdx] = readAccelZ();
        bufIdx = (bufIdx + 1) % WIN_SIZE;
        sampleCount++;

        // ── Every full window (1 second) ─────────────────────────────────────
        if (sampleCount >= WIN_SIZE) {
            sampleCount = 0;
            computeFeatures();

            if (currentMode == TESTING) {
                predictedLabel = classify();  // also sets g_last_confidence
                feedbackGiven  = false;        // new window — reset feedback state

                // Apply terrain-specific driving profile from MuJoCo calibration.
                // Find the matching profile index (TERRAIN_NAMES[] is alphabetical).
                for (int ti = 0; ti < 4; ti++) {
                    if (predictedLabel == TERRAIN_NAMES[ti]) {
                        // Clamp currentPwm to the terrain's safe maximum.
                        if (motorsRunning && currentPwm > TERRAIN_PROFILES[ti].maxPwm) {
                            currentPwm = TERRAIN_PROFILES[ti].maxPwm;
                            setMotors(currentPwm, true);
                        }
                        break;
                    }
                }
            }

            updateOLED();
            broadcastState();

            // In TRAINING mode, log every window automatically when recording
            if (recording && currentMode == TRAINING) {
                printSerialRow();
                samplesLogged++;
            }
        }
    }
}
