"""
collect_data.py
Terrain-Aware Rover — PC-side Serial data logger

Reads Serial output from the ESP32 at 115200 baud and routes:
  TRAIN rows  →  train_dataset.csv
  TEST  rows  →  feedback_log.csv

Serial line formats (produced by rover_firmware.ino):
  TRAIN,std,rms,p2p,zcr,speed,pwm,label,timestamp_ms
  TEST,std,rms,p2p,zcr,speed,pwm,predicted,actual,correct,timestamp_ms

Usage:
  python collect_data.py --port COM5
  python collect_data.py --port /dev/ttyUSB0 --baud 115200

Controls (type in terminal while running):
  mode train       — switch firmware to Training Mode
  mode test        — switch firmware to Testing Mode
  label <name>     — set terrain label (tile/mat/carpet/gravel)
  pwm <value>      — set motor PWM (0-255)
  go               — start motors
  stop             — stop motors
  rec on / rec off — start/stop recording
  correct yes      — mark last prediction as correct (Testing Mode)
  correct no <lbl> — mark last prediction wrong with correction
  status           — print firmware status
  quit / q         — exit and save CSVs
"""

import argparse
import csv
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import serial
except ImportError:
    print("[ERROR] pyserial not installed. Run:  pip install pyserial")
    sys.exit(1)

# ─── CSV column headers ────────────────────────────────────────────────────────
TRAIN_HEADER    = ["std", "rms", "p2p", "zcr", "speed", "pwm", "label", "timestamp_ms"]
FEEDBACK_HEADER = ["std", "rms", "p2p", "zcr", "speed", "pwm",
                   "predicted", "actual", "correct", "timestamp_ms"]

# ─── In-memory buffers ─────────────────────────────────────────────────────────
train_rows    = []   # Training Mode feature rows
feedback_rows = []   # Testing Mode feedback rows

# ─── Stats ────────────────────────────────────────────────────────────────────
stats = {
    "train_total":    0,
    "test_total":     0,
    "test_correct":   0,
    "test_incorrect": 0,
}

recording = True   # record by default; toggle with 'rec on/off'


def parse_args():
    p = argparse.ArgumentParser(description="Terrain-Aware Rover Serial Logger")
    p.add_argument("--port",  default="COM5",   help="Serial port (e.g. COM5 or /dev/ttyUSB0)")
    p.add_argument("--baud",  default=115200,   type=int, help="Baud rate (default 115200)")
    p.add_argument("--out",   default=".",      help="Output directory for CSV files")
    return p.parse_args()


def output_paths(out_dir: str):
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    train_path    = d / "train_dataset.csv"
    feedback_path = d / "feedback_log.csv"
    return train_path, feedback_path


def load_existing(path: Path, header: list) -> list:
    """Load existing CSV rows so we append rather than overwrite."""
    rows = []
    if path.exists():
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append([row.get(h, "") for h in header])
        print(f"[LOG] Loaded {len(rows)} existing rows from {path.name}")
    return rows


def save_csv(path: Path, header: list, rows: list):
    """Write (overwrite) the CSV with header + all rows."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"[SAVE] {path.name}  ({len(rows)} rows)")


def handle_train_row(parts: list):
    """Parse and store a TRAIN CSV line."""
    global recording
    # TRAIN,std,rms,p2p,zcr,speed,pwm,label,timestamp_ms
    if len(parts) < 9:
        return
    _, std, rms, p2p, zcr, speed, pwm, label, ts = parts[:9]
    row = [std, rms, p2p, zcr, speed, pwm, label.strip(), ts.strip()]

    if recording:
        train_rows.append(row)
        stats["train_total"] += 1
        print(f"  [TRAIN] label={label.strip():8s}  std={std}  rms={rms}  p2p={p2p}  "
              f"zcr={zcr}  spd={speed}  pwm={pwm}  "
              f"  total={stats['train_total']}")


def handle_test_row(parts: list):
    """Parse and store a TEST CSV line."""
    global recording
    # TEST,std,rms,p2p,zcr,speed,pwm,predicted,actual,correct,timestamp_ms
    if len(parts) < 11:
        return
    _, std, rms, p2p, zcr, speed, pwm, predicted, actual, correct, ts = parts[:11]
    row = [std, rms, p2p, zcr, speed, pwm,
           predicted.strip(), actual.strip(), correct.strip(), ts.strip()]

    if recording:
        feedback_rows.append(row)
        stats["test_total"] += 1
        c = int(correct.strip())
        if c == 1:
            stats["test_correct"] += 1
        else:
            stats["test_incorrect"] += 1

        acc = (stats["test_correct"] / stats["test_total"] * 100) if stats["test_total"] > 0 else 0
        marker = "✓" if c == 1 else "✗"
        print(f"  [TEST]  pred={predicted.strip():8s}  actual={actual.strip():8s}  {marker}  "
              f"  accuracy={acc:.1f}%  ({stats['test_correct']}/{stats['test_total']})")


def reader_thread(ser: serial.Serial):
    """Background thread: reads Serial lines from ESP32."""
    while True:
        try:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            parts = line.split(",")
            tag   = parts[0].upper()

            if tag == "TRAIN":
                handle_train_row(parts)
            elif tag == "TEST":
                handle_test_row(parts)
            else:
                # Print other firmware messages (debug, boot messages, etc.)
                print(f"  [ESP32] {line}")

        except serial.SerialException:
            print("[ERROR] Serial connection lost.")
            break
        except Exception as e:
            print(f"[WARN] Parse error: {e}  raw={raw!r}")


def input_thread(ser: serial.Serial, train_path: Path, feedback_path: Path):
    """Foreground: reads keyboard commands and sends them to ESP32 via Serial."""
    global recording
    print("\n── Commands ──────────────────────────────────────────────────────")
    print("  mode train/test   label <name>   pwm <0-255>   go   stop")
    print("  rec on/off        correct yes / correct no <label>   status")
    print("  quit / q  (saves CSVs and exits)")
    print("──────────────────────────────────────────────────────────────────\n")

    while True:
        try:
            cmd = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd:
            continue

        if cmd in ("quit", "q", "exit"):
            break

        elif cmd == "status":
            print(f"  Train rows : {stats['train_total']}")
            print(f"  Test rows  : {stats['test_total']}")
            print(f"  Accuracy   : {stats['test_correct']}/{stats['test_total']}")
            ser.write(b"STATUS\n")

        elif cmd == "rec on":
            recording = True
            print("  [REC] Recording ON")
            ser.write(b"REC ON\n")

        elif cmd == "rec off":
            recording = False
            print("  [REC] Recording OFF")
            ser.write(b"REC OFF\n")

        elif cmd.startswith("mode "):
            val = cmd[5:].strip().upper()
            ser.write(f"MODE {val}\n".encode())
            print(f"  [CMD] MODE {val}")

        elif cmd.startswith("label "):
            val = cmd[6:].strip()
            ser.write(f"LABEL {val}\n".encode())
            print(f"  [CMD] LABEL {val}")

        elif cmd.startswith("pwm "):
            val = cmd[4:].strip()
            ser.write(f"PWM {val}\n".encode())
            print(f"  [CMD] PWM {val}")

        elif cmd == "go":
            ser.write(b"GO\n")
            print("  [CMD] GO")

        elif cmd == "stop":
            ser.write(b"STOP\n")
            print("  [CMD] STOP")

        elif cmd == "correct yes":
            ser.write(b"CORRECT YES\n")
            print("  [CMD] CORRECT YES")

        elif cmd.startswith("correct no "):
            val = cmd[11:].strip()
            ser.write(f"CORRECT NO {val}\n".encode())
            print(f"  [CMD] CORRECT NO {val}")

        elif cmd == "save":
            save_csv(train_path,    TRAIN_HEADER,    train_rows)
            save_csv(feedback_path, FEEDBACK_HEADER, feedback_rows)

        else:
            print(f"  [WARN] Unknown command: '{cmd}'")


def main():
    args = parse_args()
    train_path, feedback_path = output_paths(args.out)

    # Load existing data (append mode)
    train_rows.extend(load_existing(train_path,    TRAIN_HEADER))
    feedback_rows.extend(load_existing(feedback_path, FEEDBACK_HEADER))

    print(f"\n── Terrain-Aware Rover Data Logger ──────────────────────────────")
    print(f"  Port       : {args.port}  @ {args.baud} baud")
    print(f"  Train CSV  : {train_path}")
    print(f"  Feedback   : {feedback_path}")
    print(f"  Started at : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"─────────────────────────────────────────────────────────────────\n")

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
        time.sleep(2)  # let ESP32 boot / reset
    except serial.SerialException as e:
        print(f"[ERROR] Cannot open {args.port}: {e}")
        print(f"  Available ports: ", end="")
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
            print(", ".join(ports) if ports else "none found")
        except Exception:
            print("(could not enumerate ports)")
        sys.exit(1)

    # Start background reader
    t = threading.Thread(target=reader_thread, args=(ser,), daemon=True)
    t.start()

    # Foreground: keyboard commands
    try:
        input_thread(ser, train_path, feedback_path)
    except KeyboardInterrupt:
        pass

    # ── Save on exit ──────────────────────────────────────────────────────────
    print("\n[EXIT] Saving CSV files…")
    save_csv(train_path,    TRAIN_HEADER,    train_rows)
    save_csv(feedback_path, FEEDBACK_HEADER, feedback_rows)

    print(f"\n── Session Summary ───────────────────────────────────────────────")
    print(f"  Training rows logged : {stats['train_total']}")
    print(f"  Test predictions     : {stats['test_total']}")
    if stats["test_total"] > 0:
        acc = stats["test_correct"] / stats["test_total"] * 100
        print(f"  Correct (YES)        : {stats['test_correct']}  ({acc:.1f}%)")
        print(f"  Wrong   (NO)         : {stats['test_incorrect']}")
    print(f"─────────────────────────────────────────────────────────────────")
    print(f"  Saved: {train_path.name}  ({len(train_rows)} rows)")
    print(f"  Saved: {feedback_path.name}  ({len(feedback_rows)} rows)\n")

    ser.close()


if __name__ == "__main__":
    main()
