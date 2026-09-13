# Transition-Aware Terrain Control — Feature Plan

## Problem

The current `AdaptiveController` produces a **hard speed lurch** every time the terrain
label changes. It only knows the *current* terrain — not where it came from or how
different the two surfaces are. Every transition is treated identically.

---

## Proposed Feature: Transition-Pair Ramp Control

Instead of instantly applying the new terrain's target speed, the controller:

1. **Detects** a label change: `previous_label → new_label`
2. **Looks up** a per-pair ramp profile from a transition table
3. **Interpolates** speed smoothly over a ramp window specific to that pair
4. **Confirms** the new label over K consecutive windows before committing
   (prevents false triggers at seam noise)

---

## Transition Table (12 unique pairs)

| From → To         | Ramp Rate (m/s²) | Hold Windows | Rationale                           |
|-------------------|-----------------|--------------|-------------------------------------|
| tile → gravel     | 0.04            | 4            | Sudden rough — brake hard, wait     |
| tile → carpet     | 0.08            | 3            | Moderate softening                  |
| tile → mat        | 0.10            | 2            | Subtle — quick ramp                 |
| mat → gravel      | 0.05            | 4            | Rough incoming — brake firmly       |
| mat → carpet      | 0.09            | 2            | Near-similar — gentle               |
| mat → tile        | 0.12            | 2            | Smoother — can ease up              |
| carpet → gravel   | 0.05            | 4            | Big jump in roughness               |
| carpet → mat      | 0.10            | 2            | Slight improvement                  |
| carpet → tile     | 0.14            | 1            | Much smoother — accelerate freely   |
| gravel → carpet   | 0.08            | 3            | Some improvement — ramp up gently   |
| gravel → mat      | 0.10            | 2            | Clear improvement                   |
| gravel → tile     | 0.15            | 1            | Suddenly smooth — allow quick ramp  |

> **Ramp Rate**: how fast speed changes per control tick (m/s per 0.1 s window).
> **Hold Windows**: consecutive matching labels required before committing the transition.

---

## Architecture Change

### Current flow
```
classify(rms) -> new_label -> _apply(new_label)   # instant step
```

### New flow
```
classify(rms) -> new_label
    |
    +-- same as current?  -> continue, reset hold counter
    |
    +-- different?
          increment hold counter
          if hold_count >= TRANSITION_RAMP[(prev, new)]["hold"]:
              _start_ramp(prev_speed, new_speed, rate)
              commit new_label
```

### New fields on `AdaptiveController`
```python
self._prev_label  = "tile"   # label before current transition
self._hold_count  = 0        # consecutive windows confirming new label
self._ramp_target = None     # target speed during ramp
self._ramp_rate   = 0.0      # m/s per control tick
self._in_ramp     = False    # ramp active flag
```

### `_tick_ramp()` — called every control window
```python
def _tick_ramp(self):
    if not self._in_ramp:
        return
    diff = self._ramp_target - self.speed
    step = min(abs(diff), self._ramp_rate) * np.sign(diff)
    self.speed += step
    self._apply_speed(self.speed)
    if abs(diff) < 1e-3:
        self._in_ramp = False
```

---

## Files to Modify

### `terrain_sim.py`
- Add `TRANSITION_RAMP` dict (12 pairs) near `ADAPTIVE_POLICY`
- Extend `AdaptiveController.__init__` with ramp state fields
- Replace direct `_apply()` call in `step()` with `_check_transition()` + `_tick_ramp()`
- Add `_check_transition(new_label)` and `_tick_ramp()` methods

---

## Verification Plan

### Simulation Test
- Run `--view-adaptive` on a seed with all 4 terrains present
- Visually confirm no hard lurch at seams
- Print ramp progress to terminal each control tick

### Metric: Jerk (rate of speed change)
```
jerk = |speed(t) - speed(t-1)| / dt
```
- **Before**: jerk spikes at every seam
- **After**: jerk stays bounded by ramp_rate at all times

### Edge Cases
- Rapid flickering at noisy seam: hold counter prevents false commits
- Same-to-same label: no ramp started, zero overhead
- Teleport (loop reset): ramp state cleared alongside `_buf`

---

## Future Extension

Once working, the 12-pair ramp table can be **learned from data** rather than
hand-tuned — run rollouts across all 12 transitions, measure the RMS settling time,
and fit the ramp rates automatically.
