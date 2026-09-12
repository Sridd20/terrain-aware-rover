"""
export_summary_csv.py
Compute per-terrain statistics from ml_dataset.csv and write to dataset_summary.csv.
"""

import csv
import numpy as np

data = {}
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

TERRAIN_ORDER = ["tile", "mat", "carpet", "gravel"]

out_rows = []
for key in TERRAIN_ORDER:
    pts = data[key]
    stds  = [p["std"]   for p in pts]
    rmss  = [p["rms"]   for p in pts]
    p2ps  = [p["p2p"]   for p in pts]
    zcrs  = [p["zcr"]   for p in pts]
    spds  = [p["speed"] for p in pts]
    out_rows.append({
        "terrain":        key,
        "samples":        len(pts),
        "avg_std":        round(float(np.mean(stds)),  4),
        "avg_rms":        round(float(np.mean(rmss)),  4),
        "std_rms":        round(float(np.std(rmss)),   4),
        "avg_p2p":        round(float(np.mean(p2ps)),  4),
        "avg_zcr":        round(float(np.mean(zcrs)),  2),
        "speed_min_ms":   round(float(np.min(spds)),   3),
        "speed_max_ms":   round(float(np.max(spds)),   3),
        "speed_mean_ms":  round(float(np.mean(spds)),  3),
    })

out_csv = "dataset_summary.csv"
fieldnames = list(out_rows[0].keys())
with open(out_csv, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(out_rows)

print(f"Saved -> {out_csv}")
for r in out_rows:
    print(r)
