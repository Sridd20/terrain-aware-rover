import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from terrain_sim import TERRAIN_PARAMS, band_limited_heightfield, run_rollout, HF_NROW, HF_NCOL

fig, axes = plt.subplots(2, 4, figsize=(16, 7))
fig.patch.set_facecolor('#0a0d0a')

for i, (name, p) in enumerate(TERRAIN_PARAMS.items()):
    hf = band_limited_heightfield(HF_NROW, HF_NCOL, p["center_freq"], p["bandwidth"], p["seed"])
    ax = axes[0, i]
    ax.imshow(hf[:, :80], cmap='bone', aspect='auto')
    ax.set_title(f"{name}\nheightfield (±{p['elev_m']*1000:.1f}mm)", color='#cfe6d6', fontsize=10)
    ax.set_xticks([]); ax.set_yticks([])

    trace = run_rollout(name, pwm=200, duration_s=4.0)
    az = trace[:, 2] - np.median(trace[:, 2])
    ax2 = axes[1, i]
    ax2.set_facecolor('#060906')
    ax2.plot(np.arange(len(az))/100.0, az, color='#4dffa0', linewidth=0.8)
    ax2.set_title("accelZ (bias-removed), PWM=200", color='#cfe6d6', fontsize=9)
    ax2.set_xlabel("time (s)", color='#6f8a76', fontsize=8)
    ax2.tick_params(colors='#6f8a76', labelsize=7)
    for spine in ax2.spines.values(): spine.set_color('#263226')
    ax2.set_ylim(-1.5, 1.5)

plt.tight_layout()
plt.savefig("example_plots.png", dpi=140, facecolor='#0a0d0a')
print("saved example_plots.png")
