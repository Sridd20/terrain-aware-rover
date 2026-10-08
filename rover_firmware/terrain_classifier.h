/*
 * terrain_classifier.h
 * Decision tree trained on REAL hardware data (data/*.csv) by terrain_classifier.py.
 * Feature order: ['std', 'p2p', 'zcr']
 * Classes: 0=carpet, 1=gravel, 2=pavement, 3=tile
 */

#pragma once
#include <math.h>

// ── Firmware interface globals ───────────────────────────────────────────────
float g_last_confidence = 0.0f;

// ── PWM → speed calibration (fitted from MuJoCo rollouts) ───────────────────
constexpr float PWM_SPEED_SLOPE     = 0.00147083f;
constexpr float PWM_SPEED_INTERCEPT = -0.00026536f;

inline float pwmToSpeed(int pwm) {
    float v = PWM_SPEED_SLOPE * (float)pwm + PWM_SPEED_INTERCEPT;
    return (v < 0.0f) ? 0.0f : v;
}

// ── Terrain driving profiles (from sim ADAPTIVE_POLICY) ─────────────────────
struct TerrainProfile {
    uint8_t maxPwm;
    float   accelRamp_s;
    float   turnGain;
};

// Ordered alphabetically: carpet, gravel, pavement, tile
static const TerrainProfile TERRAIN_PROFILES[] = {
    {170, 0.40f, 0.80f},  // carpet
    {130, 0.60f, 0.60f},  // gravel
    {190, 0.30f, 0.90f},  // pavement
    {220, 0.20f, 1.00f},  // tile
};
static const char* TERRAIN_NAMES[] = {"carpet", "gravel", "pavement", "tile"};

// ── Extern declarations (defined in rover_firmware.ino) ─────────────────────
extern float feat_std;
extern float feat_peak;
extern float feat_rms;
extern float feat_p2p;
extern float feat_zcr;
extern float feat_speed;

// ── Hardware-trained decision tree (Eloquent ML format) ─────────────────────
namespace Eloquent {
    namespace ML {
        namespace Port {
            class DecisionTree {
                public:
                    int predict(float *x) {
                        if (x[0] <= 0.749192f) {
                            if (x[2] <= 4.500000f) {
                                return 3;
                            } else {
                                return 0;
                            }
                        } else {
                            if (x[1] <= 7.537841f) {
                                if (x[2] <= 40.500000f) {
                                    if (x[2] <= 38.500000f) {
                                        if (x[0] <= 0.894860f) {
                                            return 3;
                                        } else {
                                            return 3;
                                        }
                                    } else {
                                        if (x[1] <= 6.136109f) {
                                            return 3;
                                        } else {
                                            return 1;
                                        }
                                    }
                                } else {
                                    if (x[0] <= 1.598208f) {
                                        if (x[2] <= 46.000000f) {
                                            return 2;
                                        } else {
                                            return 2;
                                        }
                                    } else {
                                        if (x[1] <= 7.071778f) {
                                            return 1;
                                        } else {
                                            return 1;
                                        }
                                    }
                                }
                            } else {
                                if (x[2] <= 31.000000f) {
                                    return 3;
                                } else {
                                    if (x[0] <= 1.561242f) {
                                        if (x[1] <= 7.782166f) {
                                            return 1;
                                        } else {
                                            return 2;
                                        }
                                    } else {
                                        return 1;
                                    }
                                }
                            }
                        }
                    }

                    const char* predictLabel(float *x) {
                        static const char* labels[] = {"carpet", "gravel", "pavement", "tile"};
                        return labels[predict(x)];
                    }
            };
        }
    }
}

// ── Firmware-facing wrapper ──────────────────────────────────────────────────
// Bridges the Eloquent ML tree to the interface rover_firmware.ino expects.
// Features: std, p2p, zcr
inline String classifyTerrain() {
    static Eloquent::ML::Port::DecisionTree _tree;
    float features[3] = { feat_std, feat_p2p, feat_zcr };
    const char* label = _tree.predictLabel(features);
    g_last_confidence = 1.0f;
    return String(label);
}
