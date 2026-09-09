"""
generate_ml_dataset.py
Generate a richer MuJoCo simulation dataset for ML terrain classification.

Differences from terrain_sim.py's build_dataset():
  - 5 PWM levels per terrain (instead of 3)  ->  more samples per class
  - Longer rollouts (10 s instead of 6 s)    ->  more windows per rollout
  - Adds 'speed' column (m/s)                ->  key feature for ML classifier
  - Saves to ml_dataset.csv

Run:
    python generate_ml_dataset.py

Output:
    ml_dataset.csv   (std, peak, rms, p2p, zcr, speed, label)
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import numpy as np
import mujoco

# Reuse constants and helpers from terrain_sim
from terrain_sim import (
    TERRAIN_PARAMS, PWM_TO_OMEGA, WHEEL_RADIUS,
    SR, WIN, PHYSICS_DT, HF_SIZE_X,
    build_model, extract_features, windows_from_trace,
)

# ------------------------------------------------------------------
# Extended PWM levels per terrain: 5 levels spread across usable range
# ------------------------------------------------------------------
PWM_LEVELS_ML = {
    "tile":   [140, 170, 200, 230, 255],
    "mat":    [120, 150, 175, 200, 225],
    "carpet": [100, 130, 155, 180, 205],
    "gravel": [ 80, 100, 120, 140, 165],
}

ROLLOUT_DURATION = 10.0   # seconds  (was 6.0 in original)
OVERLAP          = 0.5    # 50% window overlap


def run_rollout_for_ml(terrain_key, pwm, duration_s=ROLLOUT_DURATION, settle_s=0.5):
    """Drive the rover and return (accel_z_trace, speed_ms)."""
    start_x = -HF_SIZE_X + 0.4
    model   = build_model(terrain_key, start_x)
    data    = mujoco.MjData(model)

    omega = pwm * PWM_TO_OMEGA          # rad/s
    speed = omega * WHEEL_RADIUS        # m/s
    data.ctrl[:] = [omega, omega, omega, omega]

    steps_per_sample = int(round(1.0 / SR / PHYSICS_DT))
    n_total_steps    = int(duration_s / PHYSICS_DT)
    settle_steps     = int(settle_s   / PHYSICS_DT)

    accel_trace = []
    for step in range(n_total_steps):
        mujoco.mj_step(model, data)
        if step > settle_steps and step % steps_per_sample == 0:
            accel_trace.append(data.sensordata.copy())   # [ax, ay, az]

    return np.array(accel_trace), speed


def build_ml_dataset(out_csv="ml_dataset.csv"):
    header = "std,peak,rms,p2p,zcr,speed,label"
    rows   = [header]
    totals = {}

    print("\nGenerating MuJoCo simulation data for ML classifier...")
    print(f"{'Terrain':8s}  {'PWM':>4s}  {'Speed':>7s}  {'Windows':>7s}  {'RMS mean':>9s}")
    print("-" * 50)

    for terrain in TERRAIN_PARAMS:
        totals[terrain] = 0
        for pwm in PWM_LEVELS_ML[terrain]:
            trace, speed_ms = run_rollout_for_ml(terrain, pwm)
            az   = trace[:, 2]                          # vertical axis
            wins = windows_from_trace(az, win=WIN, overlap=OVERLAP)

            rms_vals = []
            for w in wins:
                f = extract_features(w)
                rows.append(
                    f"{f['std']:.6f},{f['peak']:.6f},{f['rms']:.6f},"
                    f"{f['p2p']:.6f},{f['zcr']},{speed_ms:.5f},{terrain}"
                )
                rms_vals.append(f["rms"])

            totals[terrain] += len(wins)
            mean_rms = float(np.mean(rms_vals)) if rms_vals else 0.0
            print(f"{terrain:8s}  {pwm:>4d}  {speed_ms:>7.3f}  {len(wins):>7d}  {mean_rms:>9.4f}")

    print("-" * 50)
    print(f"{'TOTAL':8s}", end="  ")
    grand = sum(totals.values())
    for t, n in totals.items():
        print(f"  {t}: {n}", end="")
    print(f"  |  grand total: {grand} windows")

    with open(out_csv, "w") as f:
        f.write("\n".join(rows))

    print(f"\nSaved {len(rows) - 1} rows -> {out_csv}")
    return out_csv


if __name__ == "__main__":
    build_ml_dataset()
