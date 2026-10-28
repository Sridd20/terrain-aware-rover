import matplotlib
matplotlib.use("Agg")
import glob, os
import pandas as pd
import matplotlib.pyplot as plt

COLORS = {"tile": "#26BFFF", "pavement": "#33CC4D", "carpet": "#FFB31A", "gravel": "#E63333"}
MARKERS = {"tile": "o", "pavement": "s", "carpet": "^", "gravel": "D"}

parts = []
for f in glob.glob("data/*.csv"):
    parts.append(pd.read_csv(f))
df = pd.concat(parts, ignore_index=True)

idle = df["std"] < 0.02
df = df[~idle]
stale = (df.groupby("label")[["std", "p2p", "zcr"]].diff().abs().sum(axis=1) == 0)
df = df[~stale].reset_index(drop=True)

fig, ax = plt.subplots(figsize=(9, 6))
fig.patch.set_facecolor("#0F1117")
ax.set_facecolor("#1A1D27")

for terrain in ["tile", "pavement", "carpet", "gravel"]:
    pts = df[df["label"] == terrain]
    ax.scatter(pts["std"], pts["zcr"],
               c=COLORS.get(terrain, "white"), marker=MARKERS.get(terrain, "o"),
               s=90, alpha=0.85, edgecolors="white", linewidths=0.4,
               label=terrain.capitalize(), zorder=3)

ax.set_xlabel("Vibration STD (m/s²)", color="white", fontsize=12)
ax.set_ylabel("Zero-Crossing Rate (ZCR)", color="white", fontsize=12)
ax.set_title("Hardware Data — Vibration STD vs ZCR\nFeatures used by the new Decision Tree",
             color="white", fontsize=13, fontweight="bold", pad=14)

ax.tick_params(colors="white", labelsize=9)
for spine in ax.spines.values(): spine.set_edgecolor("#444455")
ax.grid(True, color="#2A2D3A", linestyle="--", linewidth=0.6, zorder=0)

legend = ax.legend(title="Terrain", title_fontsize=10, fontsize=9, framealpha=0.25,
                   facecolor="#1A1D27", edgecolor="#444455", labelcolor="white")
legend.get_title().set_color("white")
plt.tight_layout()
plt.savefig("scatter_std_zcr.png", dpi=180, facecolor=fig.get_facecolor())
print("Saved scatter_std_zcr.png")
