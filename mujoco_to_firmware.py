"""
mujoco_to_firmware.py
======================
Uses MuJoCo physics rollouts (via terrain_sim.py) to:

  1. Generate a labelled dataset  (5 PWM levels x 4 terrains x 10-s rollouts).
  2. Train a shallow decision tree (max_depth=5) on [std, rms, p2p, zcr, speed].
  3. Calibrate the PWM->speed map from actual simulated wheel velocity.
  4. Export everything to:
       rover_firmware/terrain_classifier.h   -- C++ if/else tree + calibration constants
       mujoco_classifier_report.txt          -- accuracy + per-class metrics

Run:
    python mujoco_to_firmware.py

Requirements:
    pip install mujoco numpy scikit-learn
"""

import sys
import csv
import math
from pathlib import Path

import numpy as np

# -- Import terrain_sim from project root ------------------------------------
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import terrain_sim as sim

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DURATION_S = 10.0   # seconds per (terrain, pwm) rollout
SETTLE_S   = 0.5    # warm-up before recording
OVERLAP    = 0.5    # window overlap

# Five PWM levels per terrain
PWM_LEVELS_ML = {
    "tile":   [140, 175, 210, 235, 255],
    "mat":    [120, 150, 180, 205, 225],
    "carpet": [100, 130, 160, 185, 205],
    "gravel": [ 80, 105, 130, 150, 165],
}

OUT_HEADER = ROOT / "rover_firmware" / "terrain_classifier.h"
OUT_REPORT = ROOT / "mujoco_classifier_report.txt"
OUT_CSV    = ROOT / "ml_dataset_fresh.csv"

TERRAIN_CLASSES = ["carpet", "gravel", "mat", "tile"]  # alphabetical for sklearn


# ---------------------------------------------------------------------------
# 1. Generate dataset via MuJoCo rollouts
# ---------------------------------------------------------------------------
def generate_dataset():
    import mujoco

    rows      = []
    speed_map = {t: {} for t in sim.TERRAIN_PARAMS}

    for terrain in sim.TERRAIN_PARAMS:
        for pwm in PWM_LEVELS_ML[terrain]:
            print(f"  Simulating {terrain:8s} pwm={pwm:3d} ...", end="", flush=True)

            start_x = -sim.HF_SIZE_X + 0.4
            model   = sim.build_model(terrain, start_x)
            data    = mujoco.MjData(model)

            omega = pwm * sim.PWM_TO_OMEGA
            data.ctrl[:] = [omega, omega, omega, omega]

            steps_per_sample = int(round(1.0 / sim.SR / sim.PHYSICS_DT))
            n_total  = int(DURATION_S / sim.PHYSICS_DT)
            settle   = int(SETTLE_S   / sim.PHYSICS_DT)

            accel_trace, speeds = [], []
            for step in range(n_total):
                mujoco.mj_step(model, data)
                if step > settle and step % steps_per_sample == 0:
                    accel_trace.append(float(data.sensordata[2]))
                    speeds.append(abs(float(data.qvel[0])))

            az         = np.array(accel_trace)
            mean_speed = float(np.mean(speeds[10:])) if len(speeds) > 10 else 0.0
            speed_map[terrain][pwm] = mean_speed

            wins = sim.windows_from_trace(az, overlap=OVERLAP)
            for w in wins:
                f = sim.extract_features(w)
                rows.append({
                    "std":   f["std"],
                    "rms":   f["rms"],
                    "p2p":   f["p2p"],
                    "zcr":   float(f["zcr"]),
                    "speed": mean_speed,
                    "label": terrain,
                    "pwm":   pwm,
                })

            print(f"  {len(wins):3d} windows  speed={mean_speed:.3f} m/s")

    return rows, speed_map


# ---------------------------------------------------------------------------
# 2. Train a shallow decision tree
# ---------------------------------------------------------------------------
def train_tree(rows):
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.metrics import classification_report, confusion_matrix

    FEATURES = ["std", "rms", "p2p", "zcr", "speed"]
    X = np.array([[r[f] for f in FEATURES] for r in rows], dtype=np.float32)
    y_str = [r["label"] for r in rows]
    label_to_idx = {c: i for i, c in enumerate(TERRAIN_CLASSES)}
    y = np.array([label_to_idx[s] for s in y_str], dtype=np.int32)

    clf = DecisionTreeClassifier(max_depth=5, random_state=42)
    clf.fit(X, y)

    cv     = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(clf, X, y, cv=cv, scoring="accuracy")
    report = classification_report(y, clf.predict(X), target_names=TERRAIN_CLASSES)
    cm     = confusion_matrix(y, clf.predict(X))

    return clf, X, y, scores, report, cm


# ---------------------------------------------------------------------------
# 3. Export the tree as a C++ if/else function
# ---------------------------------------------------------------------------
def tree_to_cpp(clf, indent="    "):
    from sklearn.tree import _tree

    tree_ = clf.tree_
    feat_names  = ["feat_std", "feat_rms", "feat_p2p", "feat_zcr", "feat_speed"]
    class_names = TERRAIN_CLASSES
    lines = []

    def recurse(node, depth):
        pad = indent * depth
        if tree_.feature[node] != _tree.TREE_UNDEFINED:
            feat = feat_names[tree_.feature[node]]
            thr  = tree_.threshold[node]
            lines.append(f"{pad}if ({feat} <= {thr:.6f}f) {{")
            recurse(tree_.children_left[node],  depth + 1)
            lines.append(f"{pad}}} else {{")
            recurse(tree_.children_right[node], depth + 1)
            lines.append(f"{pad}}}")
        else:
            counts = tree_.value[node][0]
            total  = counts.sum()
            best   = int(counts.argmax())
            conf   = counts[best] / total
            label  = class_names[best]
            cnt_s  = ", ".join(f"{c:.0f}" for c in counts)
            lines.append(f"{pad}// leaf: {label}  conf={conf:.2f}  ({cnt_s})")
            lines.append(f"{pad}g_last_confidence = {conf:.4f}f;")
            lines.append(f'{pad}return "{label}";')

    recurse(0, 0)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Fit PWM->speed linear calibration
# ---------------------------------------------------------------------------
def fit_pwm_speed(speed_map):
    xs, ys = [], []
    for terrain_dict in speed_map.values():
        for pwm, spd in terrain_dict.items():
            xs.append(pwm)
            ys.append(spd)
    xs = np.array(xs, dtype=float)
    ys = np.array(ys, dtype=float)
    slope, intercept = np.polyfit(xs, ys, 1)
    residuals = ys - (slope * xs + intercept)
    rmse = math.sqrt((residuals**2).mean())
    return slope, intercept, rmse


# ---------------------------------------------------------------------------
# 5. Write terrain_classifier.h
# ---------------------------------------------------------------------------
def write_header(clf, score_mean, score_std, n_samples,
                 slope, intercept, pwm_rmse, out_path):

    tree_body = tree_to_cpp(clf, indent="    ")
    tree_body_indented = "\n".join("    " + ln for ln in tree_body.splitlines())

    content = (
        "/*\n"
        " * terrain_classifier.h\n"
        " * AUTO-GENERATED by mujoco_to_firmware.py -- do not edit by hand.\n"
        " *\n"
        f" * Decision tree trained on MuJoCo rigid-body physics rollouts.\n"
        f" * {n_samples} training windows  5-fold CV accuracy {score_mean*100:.1f}% +/- {score_std*100:.1f}%\n"
        " * Features: std, rms, p2p, zcr, speed  (same formulas as terrain_sim.py)\n"
        " *\n"
        " * Usage in rover_firmware.ino:\n"
        ' *   #include "terrain_classifier.h"\n'
        " *   String label = classifyTerrain();\n"
        " *   float  conf  = g_last_confidence;\n"
        " */\n"
        "\n"
        "#pragma once\n"
        "#include <math.h>\n"
        "\n"
        "// Confidence of the last classifyTerrain() call (0.0-1.0).\n"
        "float g_last_confidence = 0.0f;\n"
        "\n"
        "// -- PWM -> speed calibration (fitted from MuJoCo rollouts) --------\n"
        "// speed_ms = PWM_SPEED_SLOPE * currentPwm + PWM_SPEED_INTERCEPT\n"
        f"// RMSE: {pwm_rmse:.4f} m/s\n"
        f"constexpr float PWM_SPEED_SLOPE     = {slope:.8f}f;\n"
        f"constexpr float PWM_SPEED_INTERCEPT = {intercept:.8f}f;\n"
        "\n"
        "inline float pwmToSpeed(int pwm) {\n"
        "    float v = PWM_SPEED_SLOPE * (float)pwm + PWM_SPEED_INTERCEPT;\n"
        "    return (v < 0.0f) ? 0.0f : v;\n"
        "}\n"
        "\n"
        "// -- Terrain driving profiles (from sim ADAPTIVE_POLICY) ------------\n"
        "struct TerrainProfile {\n"
        "    uint8_t maxPwm;\n"
        "    float   accelRamp_s;\n"
        "    float   turnGain;\n"
        "};\n"
        "\n"
        "// Ordered alphabetically: carpet, gravel, mat, tile\n"
        "static const TerrainProfile TERRAIN_PROFILES[] = {\n"
        "    {170, 0.40f, 0.80f},  // carpet\n"
        "    {130, 0.60f, 0.60f},  // gravel\n"
        "    {190, 0.30f, 0.90f},  // mat\n"
        "    {220, 0.20f, 1.00f},  // tile\n"
        "};\n"
        'static const char* TERRAIN_NAMES[] = {"carpet", "gravel", "mat", "tile"};\n'
        "\n"
        "// -- Extern declarations (defined in rover_firmware.ino) ------------\n"
        "extern float feat_std;\n"
        "extern float feat_rms;\n"
        "extern float feat_p2p;\n"
        "extern float feat_zcr;\n"
        "extern float feat_speed;\n"
        "\n"
        f"// -- Decision tree (depth {clf.get_depth()}) -------------------------\n"
        "inline String classifyTerrain() {\n"
        f"{tree_body_indented}\n"
        "}\n"
    )

    out_path.write_text(content, encoding="utf-8")
    print(f"\nWrote {out_path}")


# ---------------------------------------------------------------------------
# 6. Write plain-text report
# ---------------------------------------------------------------------------
def write_report(scores, report_str, cm, speed_map,
                 slope, intercept, pwm_rmse, out_path):
    lines = [
        "=" * 70,
        "MuJoCo -> Firmware Classifier Report",
        "=" * 70,
        "",
        f"5-fold CV accuracy : {scores.mean()*100:.2f}% +/- {scores.std()*100:.2f}%",
        "",
        "Per-class report (training set):",
        report_str,
        "",
        "Confusion matrix (rows=true, cols=pred):",
        "  " + "  ".join(f"{c:8s}" for c in TERRAIN_CLASSES),
    ]
    for i, row in enumerate(cm):
        lines.append(f"  {TERRAIN_CLASSES[i]:10s}  " +
                     "  ".join(f"{v:8d}" for v in row))

    lines += [
        "",
        "PWM -> Speed calibration:",
        f"  slope     = {slope:.6f} m/s per PWM unit",
        f"  intercept = {intercept:.6f} m/s",
        f"  RMSE      = {pwm_rmse:.4f} m/s",
        "",
        "Per-terrain speed table (sim vs. linear model):",
        f"  {'terrain':8s}  {'pwm':>5s}  {'sim_speed':>10s}  {'pred_speed':>10s}",
    ]
    for terrain, d in speed_map.items():
        for pwm, spd in sorted(d.items()):
            pred = slope * pwm + intercept
            lines.append(f"  {terrain:8s}  {pwm:5d}  {spd:10.4f} m/s  {pred:10.4f} m/s")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("MuJoCo -> Firmware pipeline")
    print("=" * 60)

    print("\n[1/4] Running MuJoCo rollouts ...")
    rows, speed_map = generate_dataset()
    print(f"      Total windows: {len(rows)}")

    FIELDS = ["std", "rms", "p2p", "zcr", "speed", "pwm", "label"]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"      Saved dataset -> {OUT_CSV}")

    print("\n[2/4] Training decision tree ...")
    clf, X, y, scores, report_str, cm = train_tree(rows)
    print(f"      5-fold CV accuracy: {scores.mean()*100:.2f}% +/- {scores.std()*100:.2f}%")
    print(f"      Tree depth: {clf.get_depth()}")

    print("\n[3/4] Fitting PWM->speed calibration ...")
    slope, intercept, pwm_rmse = fit_pwm_speed(speed_map)
    print(f"      slope={slope:.6f}  intercept={intercept:.6f}  RMSE={pwm_rmse:.4f} m/s")

    print("\n[4/4] Writing firmware header and report ...")
    write_header(clf, scores.mean(), scores.std(), len(rows),
                 slope, intercept, pwm_rmse, OUT_HEADER)
    write_report(scores, report_str, cm, speed_map,
                 slope, intercept, pwm_rmse, OUT_REPORT)

    print("\n Done.")
    print(f"  Header  : {OUT_HEADER}")
    print(f"  Report  : {OUT_REPORT}")
    print(f"  Dataset : {OUT_CSV}")
    print()
    print("Next step: the firmware already has  #include terrain_classifier.h")
    print("           Just rebuild and flash.")


if __name__ == "__main__":
    main()
