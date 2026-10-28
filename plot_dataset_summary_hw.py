import matplotlib
matplotlib.use("Agg")
import glob, os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

data_frames = []
for f in glob.glob("data/*.csv"):
    data_frames.append(pd.read_csv(f))
df = pd.concat(data_frames, ignore_index=True)

idle = df["std"] < 0.02
df = df[~idle]
stale = (df.groupby("label")[["std", "p2p", "zcr"]].diff().abs().sum(axis=1) == 0)
df = df[~stale].reset_index(drop=True)

TERRAIN_ORDER = ["tile", "pavement", "carpet", "gravel"]
COLORS = {"tile": "#26BFFF", "pavement": "#33CC4D", "carpet": "#FFB31A", "gravel": "#E63333"}

rows_data = []
for key in TERRAIN_ORDER:
    pts = df[df["label"] == key]
    stds = pts["std"].values
    p2ps = pts["p2p"].values
    zcrs = pts["zcr"].values
    rows_data.append({
        "label": key.capitalize(),
        "samples": len(pts),
        "std_mean": np.mean(stds) if len(stds) > 0 else 0,
        "p2p_mean": np.mean(p2ps) if len(p2ps) > 0 else 0,
        "zcr_mean": np.mean(zcrs) if len(zcrs) > 0 else 0,
        "color": COLORS[key],
    })

COL_HEADERS = ["Terrain", "Samples", "Avg Vib STD\n(m/s²)", "Avg P2P\n(m/s²)", "Avg ZCR"]
N_COLS = len(COL_HEADERS)
N_ROWS = len(rows_data)

fig_w, fig_h = 10, 3.8
fig, ax = plt.subplots(figsize=(fig_w, fig_h))
fig.patch.set_facecolor("#0F1117")
ax.set_facecolor("#0F1117")
ax.axis("off")

COL_WIDTHS = [0.20, 0.15, 0.20, 0.20, 0.25]
total_w = 0.96
col_xs = [0.02]
for cw in COL_WIDTHS[:-1]:
    col_xs.append(col_xs[-1] + cw * total_w)

TOP, BOTTOM, LEFT, RIGHT = 0.88, 0.08, 0.02, 0.98
row_h = (TOP - BOTTOM) / (N_ROWS + 1.6)
header_y = TOP
data_ys = [TOP - row_h * (i + 1.6) for i in range(N_ROWS)]

def cell_x(col_idx):
    return col_xs[col_idx] + COL_WIDTHS[col_idx] * total_w / 2

for ci, hdr in enumerate(COL_HEADERS):
    ax.text(cell_x(ci), header_y, hdr, ha="center", va="top", color="white", fontsize=9.5, fontweight="bold", transform=ax.transAxes, multialignment="center")

ax.axhline(TOP - row_h * 0.85, color="#444466", linewidth=1.2)

for ri, r in enumerate(rows_data):
    y = data_ys[ri]
    bg_color = "#1A1D27" if ri % 2 == 0 else "#131520"
    ax.add_patch(FancyBboxPatch((LEFT, y - row_h * 0.35), total_w, row_h * 0.95, boxstyle="round,pad=0.005", facecolor=bg_color, edgecolor="none", transform=ax.transAxes, zorder=0))

    ax.add_patch(FancyBboxPatch((col_xs[0] + 0.005, y - row_h * 0.27), COL_WIDTHS[0] * total_w - 0.018, row_h * 0.68, boxstyle="round,pad=0.005", facecolor=r["color"] + "33", edgecolor=r["color"], linewidth=1.5, transform=ax.transAxes, zorder=1))
    ax.text(cell_x(0), y + row_h * 0.05, r["label"], ha="center", va="center", color=r["color"], fontsize=10, fontweight="bold", transform=ax.transAxes, zorder=2)

    cell_vals = [f"{r['samples']}", f"{r['std_mean']:.3f}", f"{r['p2p_mean']:.3f}", f"{r['zcr_mean']:.1f}"]
    for ci, val in enumerate(cell_vals, start=1):
        ax.text(cell_x(ci), y + row_h * 0.05, val, ha="center", va="center", color="white", fontsize=9, transform=ax.transAxes, zorder=2)

for ri in range(N_ROWS - 1):
    ax.axhline((data_ys[ri] + data_ys[ri + 1]) / 2, color="#2A2D3A", linewidth=0.6)
for ci in range(1, N_COLS):
    ax.axvline(col_xs[ci], color="#2A2D3A", linewidth=0.6)

fig.text(0.5, 0.97, "Real Hardware Dataset Summary — Terrain Classes", ha="center", va="top", color="white", fontsize=13, fontweight="bold")
fig.text(0.5, 0.91, "Features used: std, p2p, zcr (speed omitted as PWM is constant)", ha="center", va="top", color="#AAAACC", fontsize=9)
plt.tight_layout(rect=[0, 0, 1, 0.90])
plt.savefig("dataset_summary_table_hw.png", dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
print("Saved dataset_summary_table_hw.png")
