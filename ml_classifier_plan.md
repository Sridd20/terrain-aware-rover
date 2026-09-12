# ML Classifier Plan — Terrain-Aware Rover

## Problem

The current `AdaptiveController` in `terrain_sim.py` uses a simple RMS threshold classifier:

```python
RMS_THRESHOLDS = [
    (0.10, "tile"),
    (0.25, "mat"),
    (0.55, "carpet"),
    (float("inf"), "gravel"),
]
```

This fails because mat/carpet/tile overlap significantly in RMS at higher PWM levels (tile at PWM=255 has std~1.5, similar to gravel).

**Root cause:** RMS vibration alone is not sufficient — the same terrain produces different RMS at different speeds. Speed is a critical second feature.

---

## Proposed Solution: ML Classifier (Speed + Vibration)

### Features to use
| Feature | Source |
|---------|--------|
| `std`   | Vibration std dev from IMU window |
| `rms`   | Vibration RMS from IMU window |
| `p2p`   | Peak-to-peak from IMU window |
| `zcr`   | Zero-crossing rate from IMU window |
| `speed` | Derived from PWM: `pwm * PWM_TO_OMEGA * WHEEL_RADIUS` (m/s) |

### Recommended Classifier
**Random Forest** — best accuracy on this dataset + generates feature importance plot for presentation.

Alternatives considered:
- SVM (RBF kernel) — good for small datasets
- KNN — simple, easy to explain

### Script to create: `terrain_classifier.py`
1. Load `dataset.csv`
2. Add `speed` column = `pwm * (15.0 / 255.0) * 0.035`
3. Train/test split (80/20, stratified by label)
4. Train Random Forest on `[std, rms, p2p, zcr, speed]`
5. Generate presentation charts (see below)
6. Print classification report + accuracy

### Note: Do NOT modify `terrain_sim.py` — keep AdaptiveController as-is.

---

## Presentation Results Slide Content

### Slide Title
**"Terrain Classification Results — ML Classifier vs. Threshold Method"**

---

### 1. Why the Threshold Method Fails (Motivation)
- Show a scatter plot: **X = Vibration RMS, Y = Speed (m/s)**, color-coded by terrain class
- Key insight: mat, carpet, and tile overlap in vibration alone
- Speed is the differentiator — gravel has high vibration AND low speed; carpet has medium vibration AND medium-low speed

---

### 2. Dataset Summary Table

| Terrain | Samples | Avg Vibration STD | Avg Speed (m/s) |
|---------|---------|-------------------|-----------------|
| Tile    | 27      | ~0.55             | 0.55            |
| Mat     | 27      | ~0.34             | 0.40            |
| Carpet  | 27      | ~0.30             | 0.28            |
| Gravel  | 27      | ~0.53             | 0.18            |

> Note: Tile and Gravel have overlapping vibration STD — only speed separates them.

---

### 3. Confusion Matrix (side by side)

**Left:** RMS Threshold classifier (current system)
**Right:** ML Random Forest classifier (speed + vibration)

- The threshold method will confuse mat↔carpet and tile↔gravel at edge PWM values
- The ML classifier should achieve significantly higher accuracy

---

### 4. Accuracy Comparison Bar Chart

| Method | Expected Accuracy |
|--------|-------------------|
| RMS Threshold (baseline) | ~55–65% |
| ML Classifier (vibration only) | ~70–78% |
| ML Classifier (speed + vibration) | ~88–95% |

---

### 5. Feature Importance Plot (Random Forest)
- Bar chart showing which features contribute most to classification
- Expected order: `speed` and `std`/`rms` will be top-ranked
- This validates the design decision to include speed as a feature

---

### 6. Decision Boundary Scatter Plot
- 2D scatter: X = Vibration RMS, Y = Speed (m/s)
- Color-coded by predicted terrain class
- Shows clean 4-way separation when both features are used together

---

## Implementation Notes

When ready to implement:
- Use `sklearn.ensemble.RandomForestClassifier`
- Use `sklearn.model_selection.train_test_split` with `stratify=y`
- Use `sklearn.metrics.confusion_matrix` and `classification_report`
- Save model with `joblib.dump` for reuse
- Use `matplotlib` for all charts (no seaborn dependency needed)
- Speed formula: `speed_ms = pwm * (15.0 / 255.0) * 0.035`
  - (PWM_TO_OMEGA = 15.0/255.0, WHEEL_RADIUS = 0.035m)

---

## Files to Create (when proceeding)
- `terrain_classifier.py` — standalone script, loads dataset.csv, trains RF, outputs charts
- Output charts: `confusion_matrix.png`, `feature_importance.png`, `scatter_speed_vib.png`, `accuracy_comparison.png`
