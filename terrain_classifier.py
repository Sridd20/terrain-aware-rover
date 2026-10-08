"""Train the terrain classifier on real rover CSVs.

Changes vs. the earlier version:
  * reads every CSV in data/ (real hardware data) instead of ml_dataset.csv
  * drops idle windows and repeated (stale-buffer) windows
  * validates run-by-run (leave-one-run-out) instead of a random 80/20 split,
    so windows from the same run never sit in both train and test
  * 'peak' and 'speed' are optional: used only if present / not constant
  * exports the decision tree to a C++ header, but only when the feature order
    matches the firmware's 5-D vector (std, peak, rms, p2p, zcr)
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier, export_text

DATA_GLOB = "data/*.csv"
# Header goes straight into rover_firmware/ (next to the .ino) if that folder exists.
OUT_HEADER = "rover_firmware/terrain_classifier.h" if os.path.isdir("rover_firmware") else "terrain_classifier.h"
# Order the firmware must build its feature vector in.
#  * 'peak' is left out: the collected data has no peak column.
#  * 'rms' is left out: in the tile file rms sits ~1 g above std (gravity not removed), while in
#    carpet/gravel/pavement rms ~= std. The three features below don't depend on that offset.
# To change this, change it here AND in the firmware's extractFeatures(), same order.
FIRMWARE_FEATURES = ["std", "p2p", "zcr"]
FEATURE_POOL = ["std", "peak", "rms", "p2p", "zcr"]   # columns the script is allowed to use
IDLE_STD = 0.02        # windows below this are the rover standing still
RUN_GAP_MS = 5000      # a gap bigger than this between windows = new run
SIMPLICITY_TOL = 0.02  # pick the simplest model within 2% macro-F1 of the best

# ---------------------------------------------------------------- load
files = sorted(glob.glob(DATA_GLOB))
if not files:
    sys.exit(f"No CSVs found for {DATA_GLOB} - put the collected datasets in data/")

parts = []
for f in files:
    d = pd.read_csv(f)
    d["source"] = f
    parts.append(d)
df = pd.concat(parts, ignore_index=True)
# Surfaces collected under a different name than the project's class names.
# "smoother pavement" is the team's stand-in for the rubber mat class.
LABEL_MAP = {}   # final classes are used as logged: carpet, gravel, pavement, tile
df["label"] = df["label"].replace(LABEL_MAP)
print(f"Loaded {len(files)} files, {len(df)} rows (label map applied: {LABEL_MAP})")
print(df["label"].value_counts().to_string(), "\n")

# ---------------------------------------------------------------- run ids
# Use a 'session' column if the logger writes one; otherwise guess runs from time gaps.
if "session" in df.columns:
    df["run"] = df["source"] + "|" + df["session"].astype(str)
    print("Run IDs: from 'session' column")
else:
    new_run = df.groupby("source")["timestamp_ms"].diff().fillna(1e12) > RUN_GAP_MS
    df["run"] = df["source"] + "|" + new_run.groupby(df["source"]).cumsum().astype(str)
    print("Run IDs: guessed from timestamp gaps (add a 'session' column to the logger for real session-wise splits)")
print(df.groupby("label")["run"].nunique().rename("runs per class").to_string(), "\n")

# ---------------------------------------------------------------- clean
n0 = len(df)
idle = df["std"] < IDLE_STD
df = df[~idle]
feat_cols = [c for c in ["std", "peak", "rms", "p2p", "zcr"] if c in df.columns]
stale = (df.groupby("source")[feat_cols].diff().abs().sum(axis=1) == 0)
df = df[~stale].reset_index(drop=True)
print(f"Cleaning: dropped {int(idle.sum())} idle + {int(stale.sum())} repeated windows ({n0} -> {len(df)})")
print(df["label"].value_counts().to_string(), "\n")

# Classes with very few runs can't be validated run-by-run (holding out their only run leaves
# nothing to train on). For those, split each run into blocks of consecutive windows and hold
# blocks out instead. This is MORE OPTIMISTIC than real run-wise validation.
MIN_RUNS, BLOCK_WINDOWS = 3, 10
few = [c for c, n in df.groupby("label")["run"].nunique().items() if n < MIN_RUNS]
if few:
    m = df["label"].isin(few)
    df.loc[m, "run"] = df.loc[m, "run"] + "#" + (df[m].groupby("run").cumcount() // BLOCK_WINDOWS).astype(str)
    print(f"WARNING: {few} have < {MIN_RUNS} runs - validated with {BLOCK_WINDOWS}-window blocks, not whole runs. "
          "Their scores are upper bounds.\n")

# ---------------------------------------------------------------- features
features = [c for c in FIRMWARE_FEATURES if c in df.columns]
missing = [c for c in FIRMWARE_FEATURES if c not in df.columns]
if missing:
    print(f"WARNING: missing feature(s) {missing} - training without them")
unused = [c for c in FEATURE_POOL if c in df.columns and c not in FIRMWARE_FEATURES]
if unused:
    print(f"Not used (see FIRMWARE_FEATURES comment): {unused}")
if "speed" in df.columns and df["speed"].nunique() > 1:
    features.append("speed")
    print("'speed' varies in the data - included as a feature")
else:
    print("'speed' is constant (single PWM) - excluded; collect more PWM levels to use it")
print("Features used:", features, "\n")

X = df[features]
y = df["label"]
groups = df["run"]

# ---------------------------------------------------------------- validate (leave-one-run-out)
models = {  # ordered simplest -> most complex
    "Decision Tree": DecisionTreeClassifier(max_depth=5, random_state=42),
    "KNN": make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=5)),
    "Random Forest": RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42),
}
labels = sorted(y.unique())
cv = LeaveOneGroupOut()
results = {}
for name, model in models.items():
    y_pred = cross_val_predict(model, X, y, groups=groups, cv=cv)
    acc = accuracy_score(y, y_pred)
    f1 = f1_score(y, y_pred, average="macro")
    results[name] = f1
    print(f"=== {name} (leave-one-run-out: accuracy {acc:.3f}, macro-F1 {f1:.3f}) ===")
    print(classification_report(y, y_pred, digits=3))
    print("Confusion matrix (rows=true, cols=predicted):")
    print(pd.DataFrame(confusion_matrix(y, y_pred, labels=labels), index=labels, columns=labels), "\n")

best = max(results.values())
pick = next(n for n in models if results[n] >= best - SIMPLICITY_TOL)
print(f"Simplest model within {SIMPLICITY_TOL:.0%} of best macro-F1: {pick}\n")

# ---------------------------------------------------------------- final tree + export
le = LabelEncoder().fit(y)
tree = DecisionTreeClassifier(max_depth=5, random_state=42).fit(X, le.transform(y))
print("Final decision tree (trained on all cleaned data):")
print(export_text(tree, feature_names=features))

if features != FIRMWARE_FEATURES:
    print(f"NOT exporting {OUT_HEADER}: features {features} != firmware order {FIRMWARE_FEATURES}.")
    print("The generated header indexes features by position, so a mismatch would silently misclassify on the ESP32.")
    print("Log 'peak' in the dataset (or change the firmware vector) first.")
else:
    classmap = {int(i): name for i, name in enumerate(le.classes_)}

    def tree_to_header(clf, names):
        """Fallback exporter (no micromlgen needed). Same interface the firmware uses:
        Eloquent::ML::Port::DecisionTree clf; clf.predictLabel(features) -> const char*"""
        t = clf.tree_
        body = []

        def rec(node, depth):
            ind = "    " * (depth + 2)
            if t.children_left[node] == -1:
                body.append(f"{ind}return {int(np.argmax(t.value[node]))};")
                return
            body.append(f"{ind}if (x[{int(t.feature[node])}] <= {float(t.threshold[node]):.6f}f) {{")
            rec(t.children_left[node], depth + 1)
            body.append(f"{ind}}} else {{")
            rec(t.children_right[node], depth + 1)
            body.append(f"{ind}}}")

        rec(0, 0)
        label_list = ", ".join(f'"{names[i]}"' for i in sorted(names))
        return (
            "#pragma once\n"
            f"// Generated by terrain_classifier.py - do not hand-edit. Feature order: {features}\n"
            "namespace Eloquent { namespace ML { namespace Port {\n"
            "class DecisionTree {\n"
            "  public:\n"
            "    int predict(float *x) {\n" + "\n".join(body) + "\n    }\n"
            "    const char* predictLabel(float *x) {\n"
            f"        static const char* labels[] = {{{label_list}}};\n"
            "        return labels[predict(x)];\n"
            "    }\n"
            "};\n"
            "}}}\n"
        )

    try:
        from micromlgen import port
        header = port(tree, classmap=classmap)
        how = "micromlgen"
    except ImportError:
        header = tree_to_header(tree, classmap)
        how = "built-in exporter (micromlgen not installed)"
    with open(OUT_HEADER, "w") as fh:
        fh.write(header)
    print(f"Wrote {OUT_HEADER} via {how}; classes {classmap}")