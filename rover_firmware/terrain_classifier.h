/*
 * terrain_classifier.h
 * Decision tree trained on hardware data by terrain_classifier.py.
 * Feature order: ['std', 'p2p', 'zcr']
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
    uint8_t targetPwm;    // Optimal cruising PWM for this terrain
    uint8_t maxPwm;       // Hard safety ceiling
    float   accelRamp_s;
    float   turnGain;
};

// Ordered alphabetically: carpet, gravel, pavement, tile
// targetPwm: comfortable adaptive cruise speed per terrain
// maxPwm:    absolute ceiling (never exceed, even if user sets higher)
static const TerrainProfile TERRAIN_PROFILES[] = {
    {150, 170, 0.40f, 0.80f},  // carpet  — moderate grip, mid speed
    {110, 130, 0.60f, 0.60f},  // gravel  — loose surface, go slow
    {170, 200, 0.30f, 0.90f},  // pavement — best grip, fast but safe
    {200, 220, 0.20f, 1.00f},  // tile    — very smooth, highest speed
};
static const char* TERRAIN_NAMES[] = {"carpet", "gravel", "pavement", "tile"};

// ── Extern declarations (defined in rover_firmware.ino) ─────────────────────
extern float feat_std;
extern float feat_peak;
extern float feat_rms;
extern float feat_p2p;
extern float feat_zcr;
extern float feat_speed;

#pragma once
#include <cstdarg>
namespace Eloquent {
    namespace ML {
        namespace Port {
            class DecisionTree {
                public:
                    /**
                    * Predict class for features vector
                    */
                    int predict(float *x) {
                        if (x[1] <= 7.684326410293579) {
                            if (x[1] <= 3.5087890625) {
                                if (x[0] <= 0.40471500158309937) {
                                    if (x[1] <= 2.0302734971046448) {
                                        if (x[1] <= 0.4617920070886612) {
                                            return 1;
                                        }

                                        else {
                                            return 0;
                                        }
                                    }

                                    else {
                                        if (x[1] <= 2.971436023712158) {
                                            return 3;
                                        }

                                        else {
                                            return 1;
                                        }
                                    }
                                }

                                else {
                                    return 0;
                                }
                            }

                            else {
                                if (x[2] <= 36.5) {
                                    if (x[0] <= 0.7365415096282959) {
                                        if (x[0] <= 0.5489875078201294) {
                                            return 2;
                                        }

                                        else {
                                            return 0;
                                        }
                                    }

                                    else {
                                        if (x[1] <= 6.910033941268921) {
                                            return 3;
                                        }

                                        else {
                                            return 0;
                                        }
                                    }
                                }

                                else {
                                    if (x[1] <= 5.739745855331421) {
                                        if (x[0] <= 0.8487429916858673) {
                                            return 3;
                                        }

                                        else {
                                            return 1;
                                        }
                                    }

                                    else {
                                        if (x[1] <= 7.129883050918579) {
                                            return 1;
                                        }

                                        else {
                                            return 2;
                                        }
                                    }
                                }
                            }
                        }

                        else {
                            if (x[1] <= 8.627685546875) {
                                if (x[1] <= 8.536376476287842) {
                                    if (x[2] <= 46.5) {
                                        if (x[2] <= 34.5) {
                                            return 1;
                                        }

                                        else {
                                            return 1;
                                        }
                                    }

                                    else {
                                        return 2;
                                    }
                                }

                                else {
                                    return 2;
                                }
                            }

                            else {
                                if (x[2] <= 34.5) {
                                    if (x[2] <= 33.0) {
                                        return 1;
                                    }

                                    else {
                                        if (x[0] <= 1.7463604807853699) {
                                            return 2;
                                        }

                                        else {
                                            return 1;
                                        }
                                    }
                                }

                                else {
                                    return 1;
                                }
                            }
                        }
                    }

                    /**
                    * Predict readable class name
                    */
                    const char* predictLabel(float *x) {
                        return idxToLabel(predict(x));
                    }

                    /**
                    * Convert class idx to readable name
                    */
                    const char* idxToLabel(uint8_t classIdx) {
                        switch (classIdx) {
                            case 0:
                            return "carpet";
                            case 1:
                            return "gravel";
                            case 2:
                            return "pavement";
                            case 3:
                            return "tile";
                            default:
                            return "Houston we have a problem";
                        }
                    }

                protected:
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
