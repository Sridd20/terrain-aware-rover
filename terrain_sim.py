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
from collections import deque
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

# ----------------------------------------------------------------------
# Adaptive control policy: terrain roughness -> (target speed m/s, motor kv)
# Rougher terrain gets slower speed + softer motor gain to avoid QACC instability.
# ----------------------------------------------------------------------
ADAPTIVE_POLICY = {
    "tile":   (0.55, 0.08),
    "mat":    (0.40, 0.06),
    "carpet": (0.28, 0.05),
    "gravel": (0.18, 0.04),
}

# Rolling RMS thresholds (gravity-bias-removed Z accel, m/s²) for blind classification.
# Boundaries are midpoints between adjacent class means from dataset_summary.csv,
# sorted by ascending vibration intensity: carpet(0.255) < mat(0.291) < tile(0.416) < gravel(0.477).
RMS_THRESHOLDS = [
    (0.273, "carpet"),   # midpoint(carpet=0.255, mat=0.291)
    (0.354, "mat"),      # midpoint(mat=0.291,  tile=0.416)
    (0.447, "tile"),     # midpoint(tile=0.416, gravel=0.477)
    (float("inf"), "gravel"),
]

# Chassis RGBA colours per terrain label (shown live in the MuJoCo viewer)
TERRAIN_COLORS = {
    "tile":   [0.15, 0.75, 1.00, 1.0],   # cyan-blue  — fast, smooth
    "mat":    [0.20, 0.80, 0.30, 1.0],   # green      — moderate
    "carpet": [1.00, 0.70, 0.10, 1.0],   # amber      — cautious
    "gravel": [0.90, 0.20, 0.20, 1.0],   # red        — slow, rough
}


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

# Multi-terrain template: {seg_assets} and {seg_geoms} are injected per segment.
MJCF_MULTI_TERRAIN = """
<mujoco model="terrain_rover">
  <option timestep="{dt}" gravity="0 0 -9.81" integrator="implicitfast" cone="elliptic"/>
  <default>
    <geom solref="0.008 1" solimp="0.9 0.95 0.001"/>
  </default>
  <asset>
{seg_assets}
    <material name="mat_chassis" rgba="0.2 0.55 0.35 1"/>
    <material name="mat_wheel"   rgba="0.15 0.15 0.15 1"/>
  </asset>
  <worldbody>
    <light directional="true" pos="0 0 3" dir="0 0 -1"/>
{seg_geoms}
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


def build_mixed_terrain_model(segment_order, start_x=-HF_SIZE_X + 0.4):
    """Build a MuJoCo model with N separately colored hfield geoms, one per terrain
    segment, placed end-to-end along the X axis. Each segment uses its terrain's
    TERRAIN_COLOR so the surface is visually color-coded in the viewer.

    All segments share max_elev as their elevation scale so boundary heights are
    physically compatible — the rover won't get trapped at segment transitions.
    """
    n_seg    = len(segment_order)
    blend_w  = 3
    seg_hx   = HF_SIZE_X / n_seg
    max_elev = max(TERRAIN_PARAMS[k]["elev_m"] for k in segment_order)

    seg_assets     = ""
    seg_geoms      = ""
    seg_data       = []
    prev_right_col = None  # last column of previous segment, in metres

    for i, key in enumerate(segment_order):
        p    = TERRAIN_PARAMS[key]
        col_start = i * (HF_NCOL // n_seg)
        col_end   = ((i + 1) * (HF_NCOL // n_seg)) if i < n_seg - 1 else HF_NCOL
        ncol = col_end - col_start

        # Noise in [0,1] scaled to this terrain's actual height in metres
        hf = band_limited_heightfield(HF_NROW, ncol, p["center_freq"],
                                      p["bandwidth"], p["seed"] + i * 31)
        hf = hf * p["elev_m"]

        # Blend in metre space — heights across seams are physically continuous
        if prev_right_col is not None:
            for b in range(min(blend_w, ncol)):
                alpha    = (b + 1) / (blend_w + 1)
                hf[:, b] = (1 - alpha) * prev_right_col + alpha * hf[:, b]
        prev_right_col = hf[:, -1].copy()

        # Normalise relative to shared max_elev (MuJoCo multiplies data by max_elev)
        hf_norm = np.clip(hf / max_elev, 0.0, 1.0)
        seg_data.append((hf_norm, ncol))

        c    = TERRAIN_COLORS[key]
        rgba = f"{c[0]} {c[1]} {c[2]} {c[3]}"
        cx   = -HF_SIZE_X + seg_hx * (2 * i + 1)

        seg_assets += (
            f'    <hfield name="hf_{i}" nrow="{HF_NROW}" ncol="{ncol}"'
            f' size="{seg_hx:.4f} {HF_SIZE_Y} {max_elev} 0.02"/>\n'
            f'    <material name="mat_seg_{i}" rgba="{rgba}"/>\n'
        )
        seg_geoms += (
            f'    <geom name="ground_{i}" type="hfield" hfield="hf_{i}"'
            f' material="mat_seg_{i}" friction="1.0 0.06 0.01"'
            f' pos="{cx:.4f} 0 0"/>\n'
        )

    xml = MJCF_MULTI_TERRAIN.format(
        dt=PHYSICS_DT, start_x=start_x,
        seg_assets=seg_assets, seg_geoms=seg_geoms,
    )
    model = mujoco.MjModel.from_xml_string(xml)

    for i, (hf_norm, ncol) in enumerate(seg_data):
        hf_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_HFIELD, f"hf_{i}")
        adr   = model.hfield_adr[hf_id]
        model.hfield_data[adr: adr + HF_NROW * ncol] = hf_norm.flatten()

    return model


# ----------------------------------------------------------------------
# 3. Rollout: drive the rover, record the accelerometer
# ----------------------------------------------------------------------
WHEEL_RADIUS = 0.035  # meters, matches geom size in MJCF_TEMPLATE


def run_rollout(terrain_key, pwm, duration_s=6.0, settle_s=0.5, speed_ms=None):
    start_x = -HF_SIZE_X + 0.4  # start near the left edge of the field, drive +x
    model = build_model(terrain_key, start_x)
    data = mujoco.MjData(model)

    if speed_ms is not None:
        omega = speed_ms / WHEEL_RADIUS  # v = omega * r  ->  omega = v / r
    else:
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
def view_terrain(terrain_key, pwm=80, speed_ms=None, sim_speed=1):
    import mujoco.viewer
    model = build_model(terrain_key, -HF_SIZE_X + 0.4)
    data = mujoco.MjData(model)
    if speed_ms is not None:
        omega = speed_ms / WHEEL_RADIUS
    else:
        omega = pwm * PWM_TO_OMEGA
    data.ctrl[:] = [omega, omega, omega, omega]
    with mujoco.viewer.launch_passive(model, data) as viewer:
        while viewer.is_running():
            for _ in range(sim_speed):   # multiple steps per render frame
                mujoco.mj_step(model, data)
            viewer.sync()


# ----------------------------------------------------------------------
# 7. Blind adaptive controller (reads only IMU, knows nothing about terrain)
# ----------------------------------------------------------------------
# Number of physics steps between IMU samples: matches dataset SR=100 Hz
# PHYSICS_DT=0.002 s  ->  1/SR/PHYSICS_DT = 1/100/0.002 = 5 steps per sample
_IMU_SAMPLE_EVERY = int(round(1.0 / SR / PHYSICS_DT))   # = 5


class AdaptiveController:
    """
    Closed-loop terrain-adaptive speed and torque controller.

    Every `control_every` physics steps it:
      1. Computes a rolling RMS of the gravity-bias-removed Z accelerometer signal
         sampled at SR=100 Hz (matching the dataset pipeline exactly)
      2. Low-pass smooths to suppress transition spikes
      3. Classifies terrain from RMS alone (tile / mat / carpet / gravel)
      4. Applies the matching speed + motor-gain from ADAPTIVE_POLICY

    The controller is entirely blind — it never receives the terrain label.
    """

    def __init__(self, model, data, window=100, alpha=0.20, control_every=50,
                 settle_steps=250):
        self.data = data
        self.model = model
        self.window = window
        self.alpha = alpha           # low-pass smoothing factor for smooth_rms
        self.control_every = control_every
        self.settle_steps = settle_steps  # physics steps before control activates (~0.5 s)
        self._buf = deque(maxlen=window)  # 100 samples @ 100 Hz = 1 s of data
        self._smooth_rms = 0.0
        self._step_count = 0
        # Long-term EMA bias: tracks the DC gravity component in local-Z accel.
        # alpha_bias=0.005 -> time constant ~200 samples @ 100 Hz = ~2 s, so it
        # ignores transient spikes and slowly-changing tilt, unlike local median.
        self._bias = 0.0
        self._bias_alpha = 0.005
        self._bias_initialised = False
        self.label = "tile"          # current terrain estimate
        self.speed = ADAPTIVE_POLICY["tile"][0]
        self._apply("tile")          # safe starting defaults

    def step(self):
        """Call once per physics step. Records IMU at 100 Hz, ticks control. Returns label."""
        self._step_count += 1

        # Subsample IMU at 100 Hz (every _IMU_SAMPLE_EVERY physics steps) to
        # match the dataset pipeline: avoids 500 Hz noise inflating the RMS.
        if self._step_count % _IMU_SAMPLE_EVERY == 0:
            z = float(self.data.sensordata[2])  # Z-axis accel, local frame
            # Seed the EMA bias on first sample to avoid a huge initial error.
            if not self._bias_initialised:
                self._bias = z
                self._bias_initialised = True
            else:
                self._bias = (1.0 - self._bias_alpha) * self._bias + self._bias_alpha * z
            self._buf.append(z)

        # Settle period: rover lands on terrain; don't classify yet to avoid spike
        if self._step_count < self.settle_steps:
            return self.label

        # Immediately after settle: reset buffer and bias so landing spike is gone
        if self._step_count == self.settle_steps:
            self._buf.clear()
            self._smooth_rms = 0.0
            self._bias_initialised = False   # will re-seed from next sample
            return self.label

        if self._step_count % self.control_every == 0:
            rms = self._rms()
            self._smooth_rms = self.alpha * rms + (1.0 - self.alpha) * self._smooth_rms
            self.label = self._classify(self._smooth_rms)
            self.speed = ADAPTIVE_POLICY[self.label][0]
            self._apply(self.label)
        return self.label

    def _rms(self):
        if len(self._buf) < 10:
            return 0.0
        arr = np.array(self._buf, dtype=np.float64)
        # Use the long-term EMA bias instead of the local-window median.
        # The local median is corrupted by spikes and by gravity projection when
        # the chassis pitches over segment boundaries; the EMA is not.
        arr -= self._bias
        return float(np.sqrt((arr ** 2).mean()))

    def _classify(self, rms):
        for threshold, label in RMS_THRESHOLDS:
            if rms < threshold:
                return label
        return "gravel"

    def _apply(self, label):
        speed, kv = ADAPTIVE_POLICY[label]
        omega = speed / WHEEL_RADIUS
        self.data.ctrl[:] = [omega, omega, omega, omega]
        # Soften motor gain on rough terrain to prevent QACC blow-up.
        # For MuJoCo velocity actuators, gain is gainprm[0] and velocity damping is biasprm[2].
        for i in range(self.model.nu):
            self.model.actuator_gainprm[i, 0] = kv
            self.model.actuator_biasprm[i, 1] = 0.0   # clear accidental position spring
            self.model.actuator_biasprm[i, 2] = -kv   # correct velocity damping coefficient


class ManualController:
    """Manual WASD controller for the rover."""
    def __init__(self, model, data):
        self.model = model
        self.data = data
        self.speed = 0.0
        self.turn = 0.0
        self.kv = 0.05
        for i in range(self.model.nu):
            self.model.actuator_gainprm[i, 0] = self.kv
            self.model.actuator_biasprm[i, 1] = 0.0
            self.model.actuator_biasprm[i, 2] = -self.kv

    def on_key(self, keycode):
        if keycode == 87:    # W
            self.speed = 0.4
            self.turn = 0.0
        elif keycode == 83:  # S
            if self.speed > 0:
                self.speed = 0.0
            else:
                self.speed = -0.4
            self.turn = 0.0
        elif keycode == 65:  # A
            self.turn = 0.4
            self.speed = 0.0
        elif keycode == 68:  # D
            self.turn = -0.4
            self.speed = 0.0
        elif keycode == 32:  # Space
            self.speed = 0.0
            self.turn = 0.0

    def step(self):
        omega_l = (self.speed - self.turn) / WHEEL_RADIUS
        omega_r = (self.speed + self.turn) / WHEEL_RADIUS
        self.data.ctrl[:] = [omega_l, omega_l, omega_r, omega_r]
        if self.speed > 0: return "fwd"
        elif self.speed < 0: return "rev"
        elif self.turn > 0: return "left"
        elif self.turn < 0: return "right"
        return "stop"


def view_mixed_terrain(seed=None, n_segments=6, sim_speed=1, manual=False, slowdown=1.0):
    """Launch the MuJoCo viewer with a randomly ordered mixed-terrain track.
    The rover loops continuously; the adaptive controller adjusts speed/torque
    in real-time from IMU vibration alone.
    sim_speed: number of physics steps per render frame (>1 = faster than real-time).
    slowdown:  wall-clock multiplier (>1 = slower; e.g. 2.0 = half real-time speed)."""
    import mujoco.viewer
    import time

    rng = np.random.default_rng(seed)
    terrain_keys = list(TERRAIN_PARAMS.keys())
    segment_order = rng.choice(terrain_keys, size=n_segments, replace=True).tolist()

    print(f"\nTrack ({n_segments} segments): {' -> '.join(segment_order)}")

    start_x = -HF_SIZE_X + 0.4
    model = build_mixed_terrain_model(segment_order, start_x=start_x)
    data  = mujoco.MjData(model)

    if manual:
        ctrl = ManualController(model, data)
        print(f"Controller: MANUAL (WASD)  |  Looping: yes  |  Speed: {sim_speed}x\n")
    else:
        ctrl = AdaptiveController(model, data)
        print(f"Controller: BLIND (IMU only)  |  Looping: yes  |  Speed: {sim_speed}x\n")

    # ANSI colours for terminal label display
    _CLR = {"tile": "\033[96m", "mat": "\033[92m",
            "carpet": "\033[93m", "gravel": "\033[91m"}
    _RST = "\033[0m"
    _frame = 0

    kwargs = {}
    if manual:
        kwargs["key_callback"] = ctrl.on_key

    with mujoco.viewer.launch_passive(model, data, **kwargs) as viewer:
        while viewer.is_running():
            # Run sim_speed physics steps per rendered frame
            for _ in range(sim_speed):
                mujoco.mj_step(model, data)
                label = ctrl.step()

                # Loop: teleport rover back to start when it reaches the far end
                if data.qpos[0] > HF_SIZE_X - 0.3:
                    data.qpos[0]   = start_x
                    data.qpos[1]   = 0.0
                    data.qpos[2]   = 0.16
                    data.qpos[3:7] = [1.0, 0.0, 0.0, 0.0]  # identity quaternion
                    data.qvel[0:6] = 0.0                     # zero body velocity
                    mujoco.mj_forward(model, data)           # recompute contacts
                    ctrl._buf.clear()                         # flush teleport spike
                    ctrl._bias_initialised = False            # re-seed bias after landing

            # Throttle terminal print (every 25 frames) to avoid spam at high speed
            _frame += 1
            if _frame % 25 == 0:
                # Ground-truth terrain from rover x-position (which segment it's on)
                _seg_w = 2 * HF_SIZE_X / n_segments
                _seg_i = int((data.qpos[0] + HF_SIZE_X) / _seg_w)
                _seg_i = max(0, min(_seg_i, n_segments - 1))
                true_terrain = segment_order[_seg_i]
                # Actual forward speed from the freejoint linear velocity (m/s)
                actual_speed = abs(float(data.qvel[0]))

                if manual:
                    print(
                        f"\rt={data.time:7.2f}s | "
                        f"terrain={_CLR.get(true_terrain,'')}{true_terrain:7s}{_RST} | "
                        f"speed={actual_speed:.2f} m/s  (mode={label})",
                        end="", flush=True,
                    )
                else:
                    print(
                        f"\rt={data.time:7.2f}s | "
                        f"terrain={_CLR.get(true_terrain,'')}{true_terrain:7s}{_RST} "
                        f"pred={ctrl.label:7s} | "
                        f"RMS={ctrl._smooth_rms:.3f} | "
                        f"speed={actual_speed:.2f} m/s (target={ctrl.speed:.2f})",
                        end="", flush=True,
                    )
            viewer.sync()
            # Slow down below real-time if requested (sleep extra wall-clock time)
            if slowdown > 1.0:
                time.sleep(PHYSICS_DT * sim_speed * (slowdown - 1.0))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Terrain-aware rover simulator. Use --view for a single terrain, "
                    "--view-adaptive for a random mixed-terrain track with live adaptive control."
    )
    ap.add_argument("--view", choices=list(TERRAIN_PARAMS.keys()), default=None,
                     help="Open interactive viewer on a single terrain (fixed speed).")
    ap.add_argument("--pwm", type=int, default=80,
                     help="PWM level for --view mode (0-255). Default: 80.")
    ap.add_argument("--speed", type=float, default=None,
                     help="Target wheel speed in m/s for --view mode (overrides --pwm).")
    ap.add_argument("--view-adaptive", action="store_true",
                     help="Launch mixed random-terrain track with blind adaptive control.")
    ap.add_argument("--view-wasd", action="store_true",
                     help="Launch mixed random-terrain track with manual WASD keyboard control.")
    ap.add_argument("--segments", type=int, default=6,
                     help="Number of terrain segments in the adaptive/wasd track. Default: 6.")
    ap.add_argument("--seed", type=int, default=None,
                     help="Random seed for segment order (omit for a different track each run).")
    ap.add_argument("--sim-speed", type=int, default=1, metavar="N",
                     help="Physics steps per render frame (default 1 = real-time). "
                          "Use 4-10 to run faster than real-time.")
    ap.add_argument("--slowdown", type=float, default=1.0, metavar="X",
                     help="Wall-clock slowdown multiplier (default 1.0 = real-time). "
                          "Use e.g. 2.0 for half speed, 4.0 for quarter speed.")
    ap.add_argument("--duration", type=float, default=6.0,
                     help="Seconds of driving per (terrain, pwm) run (dataset mode only).")
    ap.add_argument("--out", default="dataset.csv")
    args = ap.parse_args()

    if args.view_adaptive:
        view_mixed_terrain(seed=args.seed, n_segments=args.segments,
                           sim_speed=args.sim_speed, manual=False, slowdown=args.slowdown)
    elif args.view_wasd:
        view_mixed_terrain(seed=args.seed, n_segments=args.segments,
                           sim_speed=args.sim_speed, manual=True, slowdown=args.slowdown)
    elif args.view:
        view_terrain(args.view, pwm=args.pwm, speed_ms=args.speed,
                     sim_speed=args.sim_speed)
    else:
        build_dataset(duration_s=args.duration, out_csv=args.out)
