"""
plot_scatter.py
Generate a scatter plot of Vibration RMS vs Rover Speed from MuJoCo simulation data.
Speed is derived from the PWM column using the same formula as terrain_sim.py.

Run:
    python plot_scatter.py
Output:
    scatter_speed_vib.png
"""

import matplotlib
matplotlib.use("Agg")   # non-interactive backend — no GUI window needed
import csv
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# --------------------------------------------------------------------------
# Same constants as terrain_sim.py
# --------------------------------------------------------------------------
PWM_TO_OMEGA  = 15.0 / 255.0   # rad/s per PWM unit
WHEEL_RADIUS  = 0.035           # meters

# Terrain colors (matching TERRAIN_COLORS in terrain_sim.py, normalised to [0,1])
COLORS = {
    "tile":   "#26BFFF",   # cyan-blue
    "mat":    "#33CC4D",   # green
    "carpet": "#FFB31A",   # amber
    "gravel": "#E63333",   # red
}
MARKERS = {
    "tile":   "o",
    "mat":    "s",
    "carpet": "^",
    "gravel": "D",
}

# --------------------------------------------------------------------------
# Load ml_dataset.csv  (340 samples, speed column already included)
# --------------------------------------------------------------------------
rows = []
with open("ml_dataset.csv", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append({
            "std":   float(row["std"]),
            "rms":   float(row["rms"]),
            "p2p":   float(row["p2p"]),
            "zcr":   int(row["zcr"]),
            "speed": float(row["speed"]),   # already in ml_dataset.csv
            "label": row["label"].strip(),
        })

# --------------------------------------------------------------------------
# Build the scatter plot
# --------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9, 6))
fig.patch.set_facecolor("#0F1117")
ax.set_facecolor("#1A1D27")

terrains = ["tile", "mat", "carpet", "gravel"]

for terrain in terrains:
    pts = [r for r in rows if r["label"] == terrain]
    xs  = [r["rms"]   for r in pts]
    ys  = [r["speed"] for r in pts]
    ax.scatter(
        xs, ys,
        c=COLORS[terrain],
        marker=MARKERS[terrain],
        s=90,
        alpha=0.85,
        edgecolors="white",
        linewidths=0.4,
        label=terrain.capitalize(),
        zorder=3,
    )

# RMS threshold lines (current classifier's decision boundaries on X axis)
threshold_rms = [0.10, 0.25, 0.55]
labels_thresh = ["tile|mat", "mat|carpet", "carpet|gravel"]
for xv, lbl in zip(threshold_rms, labels_thresh):
    ax.axvline(x=xv, color="white", linewidth=0.8, linestyle="--", alpha=0.35)
    ax.text(xv + 0.005, ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 0.8,
            lbl, color="white", fontsize=7, alpha=0.50, va="top")

# --------------------------------------------------------------------------
# Styling
# --------------------------------------------------------------------------
ax.set_xlabel("Vibration RMS  (m/s²)", color="white", fontsize=12)
ax.set_ylabel("Rover Speed  (m/s)",    color="white", fontsize=12)
ax.set_title(
    "MuJoCo Simulation Data — Vibration RMS vs Speed\n"
    "Colour = terrain class  |  Dashed lines = current RMS thresholds",
    color="white", fontsize=13, fontweight="bold", pad=14,
)

ax.tick_params(colors="white", labelsize=9)
for spine in ax.spines.values():
    spine.set_edgecolor("#444455")
ax.grid(True, color="#2A2D3A", linestyle="--", linewidth=0.6, zorder=0)

legend = ax.legend(
    title="Terrain", title_fontsize=10,
    fontsize=9, framealpha=0.25,
    facecolor="#1A1D27", edgecolor="#444455",
    labelcolor="white",
)
legend.get_title().set_color("white")

# Annotation explaining the key insight
ax.annotate(
    "Tile & Gravel overlap in RMS →\nSpeed resolves the ambiguity",
    xy=(0.65, 0.45), xytext=(0.90, 0.30),
    xycoords="data", textcoords="data",
    color="#FFDD55", fontsize=8.5,
    arrowprops=dict(arrowstyle="->", color="#FFDD55", lw=1.2),
    bbox=dict(boxstyle="round,pad=0.3", fc="#1A1D27", ec="#FFDD55", lw=1, alpha=0.85),
)

plt.tight_layout()
out = "scatter_speed_vib.png"
plt.savefig(out, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
print(f"Saved -> {out}")
# plt.show() removed — using Agg backend (headless)
