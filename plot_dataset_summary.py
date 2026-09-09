"""
plot_dataset_summary.py
Generate a styled dataset summary table from ml_dataset.csv using matplotlib.

Output:
    dataset_summary_table.png
"""

import matplotlib
matplotlib.use("Agg")
import csv
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

# --------------------------------------------------------------------------
# Load ml_dataset.csv
# --------------------------------------------------------------------------
data = {}   # terrain -> list of dicts
with open("ml_dataset.csv", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        label = row["label"].strip()
        if label not in data:
            data[label] = []
        data[label].append({
            "std":   float(row["std"]),
            "rms":   float(row["rms"]),
            "p2p":   float(row["p2p"]),
            "zcr":   int(row["zcr"]),
            "speed": float(row["speed"]),
        })

# --------------------------------------------------------------------------
# Compute per-terrain stats
# --------------------------------------------------------------------------
TERRAIN_ORDER  = ["tile", "mat", "carpet", "gravel"]
TERRAIN_LABELS = ["Tile", "Mat", "Carpet", "Gravel"]
COLORS = {
    "tile":   "#26BFFF",
    "mat":    "#33CC4D",
    "carpet": "#FFB31A",
    "gravel": "#E63333",
}

rows_data = []
for key in TERRAIN_ORDER:
    pts   = data[key]
    rmss  = [p["rms"]   for p in pts]
    stds  = [p["std"]   for p in pts]
    p2ps  = [p["p2p"]   for p in pts]
    zcrs  = [p["zcr"]   for p in pts]
    spds  = [p["speed"] for p in pts]
    rows_data.append({
        "label":      key.capitalize(),
        "samples":    len(pts),
        "rms_mean":   np.mean(rmss),
        "rms_std":    np.std(rmss),
        "std_mean":   np.mean(stds),
        "p2p_mean":   np.mean(p2ps),
        "zcr_mean":   np.mean(zcrs),
        "speed_min":  np.min(spds),
        "speed_max":  np.max(spds),
        "speed_mean": np.mean(spds),
        "color":      COLORS[key],
    })

# --------------------------------------------------------------------------
# Build the figure
# --------------------------------------------------------------------------
COL_HEADERS = [
    "Terrain", "Samples", "Avg Vib STD\n(m/s²)", "Avg Vib RMS\n(m/s²)",
    "Avg P2P\n(m/s²)", "Avg ZCR", "Speed Range\n(m/s)",
]
N_COLS = len(COL_HEADERS)
N_ROWS = len(rows_data)

fig_w = 14
fig_h = 3.8
fig, ax = plt.subplots(figsize=(fig_w, fig_h))
fig.patch.set_facecolor("#0F1117")
ax.set_facecolor("#0F1117")
ax.axis("off")

# --- layout ---
COL_WIDTHS = [0.13, 0.09, 0.15, 0.15, 0.13, 0.10, 0.17]   # fractions of width
assert abs(sum(COL_WIDTHS) - sum(COL_WIDTHS)) < 1e-9       # just to avoid unused warning

TOP    = 0.88
BOTTOM = 0.08
LEFT   = 0.02
RIGHT  = 0.98

total_w = RIGHT - LEFT
col_xs = [LEFT]
for cw in COL_WIDTHS[:-1]:
    col_xs.append(col_xs[-1] + cw * total_w)

row_h     = (TOP - BOTTOM) / (N_ROWS + 1.6)
header_y  = TOP
data_ys   = [TOP - row_h * (i + 1.6) for i in range(N_ROWS)]

def cell_x(col_idx):
    x = col_xs[col_idx]
    w = COL_WIDTHS[col_idx] * total_w
    return x + w / 2   # centre of cell

# ---- header row ----
for ci, hdr in enumerate(COL_HEADERS):
    ax.text(cell_x(ci), header_y, hdr,
            ha="center", va="top",
            color="white", fontsize=9.5, fontweight="bold",
            transform=ax.transAxes,
            multialignment="center")

# Header underline
ax.axhline(TOP - row_h * 0.85, color="#444466", linewidth=1.2)

# ---- data rows ----
for ri, r in enumerate(rows_data):
    y = data_ys[ri]

    # Alternating row background
    bg_color = "#1A1D27" if ri % 2 == 0 else "#131520"
    fancy = FancyBboxPatch(
        (LEFT, y - row_h * 0.35),
        total_w, row_h * 0.95,
        boxstyle="round,pad=0.005",
        facecolor=bg_color, edgecolor="none",
        transform=ax.transAxes, zorder=0,
    )
    ax.add_patch(fancy)

    # Coloured terrain pill (col 0)
    pill = FancyBboxPatch(
        (col_xs[0] + 0.005, y - row_h * 0.27),
        COL_WIDTHS[0] * total_w - 0.018, row_h * 0.68,
        boxstyle="round,pad=0.005",
        facecolor=r["color"] + "33",   # 20% opacity
        edgecolor=r["color"], linewidth=1.5,
        transform=ax.transAxes, zorder=1,
    )
    ax.add_patch(pill)
    ax.text(cell_x(0), y + row_h * 0.05, r["label"],
            ha="center", va="center",
            color=r["color"], fontsize=10, fontweight="bold",
            transform=ax.transAxes, zorder=2)

    cell_vals = [
        f"{r['samples']}",
        f"{r['std_mean']:.3f}",
        f"{r['rms_mean']:.3f} ± {r['rms_std']:.3f}",
        f"{r['p2p_mean']:.3f}",
        f"{r['zcr_mean']:.1f}",
        f"{r['speed_min']:.2f} – {r['speed_max']:.2f}",
    ]
    for ci, val in enumerate(cell_vals, start=1):
        # highlight speed range column
        fc = r["color"] if ci == 6 else "white"
        fw = "bold" if ci == 6 else "normal"
        ax.text(cell_x(ci), y + row_h * 0.05, val,
                ha="center", va="center",
                color=fc, fontsize=9, fontweight=fw,
                transform=ax.transAxes, zorder=2)

# Row separators
for ri in range(N_ROWS - 1):
    sep_y = (data_ys[ri] + data_ys[ri + 1]) / 2
    ax.axhline(sep_y, color="#2A2D3A", linewidth=0.6)

# Column separators (light)
for ci in range(1, N_COLS):
    ax.axvline(col_xs[ci], color="#2A2D3A", linewidth=0.6)

# Title
fig.text(0.5, 0.97,
         "MuJoCo Dataset Summary — Terrain Classes",
         ha="center", va="top",
         color="white", fontsize=13, fontweight="bold")
fig.text(0.5, 0.91,
         "340 windows total  |  85 per class  |  Features: std, peak, rms, p2p, zcr, speed",
         ha="center", va="top",
         color="#AAAACC", fontsize=9)

plt.tight_layout(rect=[0, 0, 1, 0.90])
out = "dataset_summary_table.png"
plt.savefig(out, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
print(f"Saved -> {out}")
