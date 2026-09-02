"""
terrain_sim.py
Physics-based synthetic IMU/vibration generator for the terrain-aware rover.

Replaces the hand-tuned waveform synth with an actual rigid-body simulation:
a 4-wheel rover drives over a procedurally generated heightfield terrain in
MuJoCo, and a simulated accelerometer (mounted the same way the dev doc
specifies -- rigidly, near a wheel mount) records the resulting vibration.

Pipeline:
  terrain heightfield (band-limited noise, one profile per class)
      -> MuJoCo rigid-body contact simulation (wheel vs terrain)
      -> accelerometer site sensor, resampled to 100 Hz
      -> gravity-bias removed -> 1s / 100-sample windows
      -> 5-D feature vector (std, peak, rms, p2p, zcr)  [Table 3 / 4.2 formulas]
      -> labelled CSV, same schema as the training pipeline expects

Install:
    pip install mujoco numpy matplotlib

Run:
    python terrain_sim.py                # generates dataset.csv + example_plots.png
    python terrain_sim.py --view tile     # opens the interactive MuJoCo viewer
                                          # (desktop only -- needs a display)
"""

import argparse
import numpy as np
import mujoco

SR = 100          # accelerometer sample rate we resample to (Hz), matches doc 3.1
WIN = 100         # samples per window (1s), matches doc 3.1/3.2
PHYSICS_DT = 0.002  # MuJoCo integration timestep (s)

# ----------------------------------------------------------------------
# 1. Terrain profiles
# ----------------------------------------------------------------------
# Each terrain is a band-limited noise heightfield: center_freq controls the
# "grain size" of the bumps (cycles across the whole field), elev_m controls
# their height in meters. carpet/mat are deliberately close (doc calls that
# pair "the most confusable"); gravel is high-frequency and tall; tile is
# almost flat.
TERRAIN_PARAMS = {
    "tile":   dict(center_freq=0.010, bandwidth=0.008, elev_m=0.0004, seed=1),
    "mat":    dict(center_freq=0.045, bandwidth=0.020, elev_m=0.0020, seed=2),
    "carpet": dict(center_freq=0.038, bandwidth=0.018, elev_m=0.0026, seed=3),
    "gravel": dict(center_freq=0.130, bandwidth=0.060, elev_m=0.0080, seed=4),
}

HF_NROW = 128
HF_NCOL = 256
HF_SIZE_X = 3.0   # half-extent, meters -> field spans 6m in travel direction
HF_SIZE_Y = 0.8   # half-extent, meters -> field spans 1.6m across

# 3 PWM levels per class for the data-collection protocol (doc 4.1), spread
# around the nominal per-terrain PWM from Table 7.
PWM_LEVELS = {
    "tile":   [180, 220, 255],
    "mat":    [150, 190, 230],
    "carpet": [135, 170, 205],
    "gravel": [100, 130, 165],
}
PWM_TO_OMEGA = 15.0 / 255.0  # rad/s per PWM unit (wheel radius 0.035m -> ~0.9 m/s top speed)


def band_limited_heightfield(nrow, ncol, center_freq, bandwidth, seed):
    """White noise, band-passed in the 2D spatial-frequency domain, normalized to [0,1]."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal((nrow, ncol))
    F = np.fft.fft2(noise)
    fy = np.fft.fftfreq(nrow).reshape(-1, 1)
    fx = np.fft.fftfreq(ncol).reshape(1, -1)
    fmag = np.sqrt(fx**2 + fy**2)
    mask = np.exp(-0.5 * ((fmag - center_freq) / bandwidth) ** 2)
    filtered = np.fft.ifft2(F * mask).real
    filtered -= filtered.min()
    filtered /= (filtered.max() + 1e-9)
    return filtered.astype(np.float64)


# ----------------------------------------------------------------------
# 2. Rover model (4-wheel, skid-steer style, left/right coupled -- mirrors
#    the doc's single L298N per side)
# ----------------------------------------------------------------------
MJCF_TEMPLATE = """
<mujoco model="terrain_rover">
  <option timestep="{dt}" gravity="0 0 -9.81" integrator="implicitfast" cone="elliptic"/>
  <default>
    <geom solref="0.008 1" solimp="0.9 0.95 0.001"/>
  </default>
  <asset>
    <hfield name="terrain" nrow="{nrow}" ncol="{ncol}" size="{hx} {hy} {elev} 0.02"/>
    <material name="mat_terrain" rgba="0.55 0.5 0.42 1"/>
    <material name="mat_chassis" rgba="0.2 0.55 0.35 1"/>
    <material name="mat_wheel" rgba="0.15 0.15 0.15 1"/>
  </asset>
  <worldbody>
    <light directional="true" pos="0 0 3" dir="0 0 -1"/>
    <geom name="ground" type="hfield" hfield="terrain" material="mat_terrain" friction="1.0 0.06 0.01"/>

    <body name="chassis" pos="{start_x} 0 0.16">
      <freejoint/>
      <geom name="chassis_geom" type="box" size="0.09 0.06 0.02" mass="0.4" material="mat_chassis"/>
      <site name="imu_site" pos="0.05 0.04 0.02" size="0.005"/>

      <body name="wheel_fl" pos="0.07 0.075 -0.05">
        <joint name="j_fl" type="hinge" axis="0 1 0" damping="0.02"/>
        <geom name="g_fl" type="cylinder" size="0.035 0.014" euler="90 0 0"
              mass="0.05" material="mat_wheel" friction="1.0 0.06 0.01"/>
      </body>
      <body name="wheel_fr" pos="0.07 -0.075 -0.05">
        <joint name="j_fr" type="hinge" axis="0 1 0" damping="0.02"/>
        <geom name="g_fr" type="cylinder" size="0.035 0.014" euler="90 0 0"
              mass="0.05" material="mat_wheel" friction="1.0 0.06 0.01"/>
      </body>
      <body name="wheel_rl" pos="-0.07 0.075 -0.05">
        <joint name="j_rl" type="hinge" axis="0 1 0" damping="0.02"/>
        <geom name="g_rl" type="cylinder" size="0.035 0.014" euler="90 0 0"
              mass="0.05" material="mat_wheel" friction="1.0 0.06 0.01"/>
      </body>
      <body name="wheel_rr" pos="-0.07 -0.075 -0.05">
        <joint name="j_rr" type="hinge" axis="0 1 0" damping="0.02"/>
        <geom name="g_rr" type="cylinder" size="0.035 0.014" euler="90 0 0"
              mass="0.05" material="mat_wheel" friction="1.0 0.06 0.01"/>
      </body>
    </body>
  </worldbody>

  <actuator>
    <velocity name="act_left"  joint="j_fl" kv="0.05"/>
    <velocity name="act_left2" joint="j_rl" kv="0.05"/>
    <velocity name="act_right" joint="j_fr" kv="0.05"/>
    <velocity name="act_right2" joint="j_rr" kv="0.05"/>
  </actuator>

  <sensor>
    <accelerometer name="imu_acc" site="imu_site"/>
  </sensor>
</mujoco>
"""


def build_model(terrain_key, start_x):
    p = TERRAIN_PARAMS[terrain_key]
    hfield = band_limited_heightfield(HF_NROW, HF_NCOL, p["center_freq"], p["bandwidth"], p["seed"])
    xml = MJCF_TEMPLATE.format(
        dt=PHYSICS_DT, nrow=HF_NROW, ncol=HF_NCOL,
        hx=HF_SIZE_X, hy=HF_SIZE_Y, elev=p["elev_m"], start_x=start_x,
    )
    model = mujoco.MjModel.from_xml_string(xml)
    model.hfield_data[:] = hfield.flatten()
    return model


# ----------------------------------------------------------------------
# 3. Rollout: drive the rover, record the accelerometer
# ----------------------------------------------------------------------
def run_rollout(terrain_key, pwm, duration_s=6.0, settle_s=0.5):
    start_x = -HF_SIZE_X + 0.4  # start near the left edge of the field, drive +x
    model = build_model(terrain_key, start_x)
    data = mujoco.MjData(model)

    omega = pwm * PWM_TO_OMEGA
    data.ctrl[:] = [omega, omega, omega, omega]

    steps_per_sample = int(round(1.0 / SR / PHYSICS_DT))
    n_total_steps = int(duration_s / PHYSICS_DT)
    settle_steps = int(settle_s / PHYSICS_DT)

    accel_trace = []
    for step in range(n_total_steps):
        mujoco.mj_step(model, data)
        if step > settle_steps and step % steps_per_sample == 0:
            accel_trace.append(data.sensordata.copy())  # [ax, ay, az] local frame

    return np.array(accel_trace)  # shape (n_samples, 3)


# ----------------------------------------------------------------------
# 4. Feature extraction -- identical formulas to Table 3 / 4.2
# ----------------------------------------------------------------------
def extract_features(sig):
    sig = np.asarray(sig, dtype=np.float64)
    std = sig.std()
    rms = np.sqrt((sig**2).mean())
    peak = np.abs(sig).max() / rms if rms > 1e-3 else 0.0
    p2p = sig.max() - sig.min()
    zcr = int(((sig[:-1] * sig[1:]) < 0).sum())
    return dict(std=std, peak=peak, rms=rms, p2p=p2p, zcr=zcr)


def windows_from_trace(accel_z, win=WIN, overlap=0.5):
    """Gravity-bias removed (mean of the whole trace, i.e. static g), then
    sliced into windows -- mirrors the doc's own note that this is a proper-
    force accelerometer, so vibration = raw z minus its resting bias."""
    bias = np.median(accel_z)
    v = accel_z - bias
    step = int(win * (1 - overlap))
    out = []
    for start in range(0, len(v) - win + 1, max(step, 1)):
        out.append(v[start:start + win])
    return out


# ----------------------------------------------------------------------
# 5. Dataset build
# ----------------------------------------------------------------------
def build_dataset(duration_s=6.0, overlap=0.5, out_csv="dataset.csv"):
    rows = ["std,peak,rms,p2p,zcr,pwm,label"]
    summary = {}
    for terrain in TERRAIN_PARAMS:
        for pwm in PWM_LEVELS[terrain]:
            trace = run_rollout(terrain, pwm, duration_s=duration_s)
            az = trace[:, 2]  # vertical axis in local (chassis-aligned) frame
            wins = windows_from_trace(az, overlap=overlap)
            for w in wins:
                f = extract_features(w)
                rows.append(f"{f['std']:.6f},{f['peak']:.6f},{f['rms']:.6f},"
                            f"{f['p2p']:.6f},{f['zcr']},{pwm},{terrain}")
            summary.setdefault(terrain, []).append((pwm, len(wins)))
            print(f"{terrain:8s} pwm={pwm:3d}  windows={len(wins):3d}  "
                  f"std~{np.mean([extract_features(w)['std'] for w in wins]):.4f}")

    with open(out_csv, "w") as f:
        f.write("\n".join(rows))
    print(f"\nwrote {len(rows)-1} rows -> {out_csv}")
    return out_csv


# ----------------------------------------------------------------------
# 6. Optional: interactive viewer (desktop, needs a display)
# ----------------------------------------------------------------------
def view_terrain(terrain_key, pwm=80):
    import mujoco.viewer
    model = build_model(terrain_key, -HF_SIZE_X + 0.4)
    data = mujoco.MjData(model)
    omega = pwm * PWM_TO_OMEGA
    data.ctrl[:] = [omega, omega, omega, omega]
    with mujoco.viewer.launch_passive(model, data) as viewer:
        while viewer.is_running():
            mujoco.mj_step(model, data)
            viewer.sync()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", choices=list(TERRAIN_PARAMS.keys()), default=None,
                     help="open interactive viewer on this terrain instead of building a dataset")
    ap.add_argument("--pwm", type=int, default=80,
                     help="PWM level for the viewer (0-255, lower = slower). Default: 80")
    ap.add_argument("--duration", type=float, default=6.0, help="seconds of driving per (terrain, pwm) run")
    ap.add_argument("--out", default="dataset.csv")
    args = ap.parse_args()

    if args.view:
        view_terrain(args.view, pwm=args.pwm)
    else:
        build_dataset(duration_s=args.duration, out_csv=args.out)
