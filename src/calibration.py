"""
ReachBot — Camera-to-Arm Calibration

Solves for the pixel-to-mm transform between the Logitech C270 camera
and the arm's coordinate frame.

How it works:
  1. Move the arm to N known positions (you type the real-world coordinates).
  2. The script detects the gripper tip in the camera frame (red marker).
  3. A least-squares fit produces the scale (mm/pixel) and offset (mm).
  4. Writes the result to calibration.json, which config.py loads on startup.

Usage:
    python src/calibration.py              # Interactive calibration wizard
    python src/calibration.py --test       # Show live camera with overlay
    python src/calibration.py --print      # Print stored calibration values
"""

import argparse
import json
import logging
import math
import time
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

CALIBRATION_FILE = Path(__file__).parent.parent / "calibration.json"
MIN_POINTS = 4      # Minimum calibration points for a valid fit


try:
    import cv2
    import numpy as np
    CV_AVAILABLE = True
except ImportError:
    CV_AVAILABLE = False
    log.warning("OpenCV not available — calibration requires cv2")


# ---------------------------------------------------------------------------
# Calibration data model
# ---------------------------------------------------------------------------

class CalibrationResult:
    """Affine pixel-to-mm transform: arm_x = sx*px + ox, arm_y = sy*py + oy."""

    def __init__(self, sx: float, sy: float, ox: float, oy: float, z_offset: float, error_mm: float):
        self.sx = sx            # x scale mm/pixel
        self.sy = sy            # y scale mm/pixel
        self.ox = ox            # x offset mm
        self.oy = oy            # y offset mm
        self.z_offset = z_offset  # fixed camera height above floor (mm)
        self.error_mm = error_mm  # RMS reprojection error

    def pixel_to_arm(self, px: float, py: float) -> tuple[float, float, float]:
        return (
            self.sx * px + self.ox,
            self.sy * py + self.oy,
            -self.z_offset,
        )

    def to_dict(self) -> dict:
        return {
            "sx": self.sx, "sy": self.sy,
            "ox": self.ox, "oy": self.oy,
            "z_offset_mm": self.z_offset,
            "rms_error_mm": self.error_mm,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationResult":
        return cls(
            sx=d["sx"], sy=d["sy"],
            ox=d["ox"], oy=d["oy"],
            z_offset=d["z_offset_mm"],
            error_mm=d.get("rms_error_mm", 0.0),
        )

    def __str__(self) -> str:
        return (
            f"CalibrationResult(sx={self.sx:.4f} mm/px, sy={self.sy:.4f} mm/px, "
            f"offset=({self.ox:.1f}, {self.oy:.1f}) mm, z={self.z_offset:.1f} mm, "
            f"rms={self.error_mm:.2f} mm)"
        )


# ---------------------------------------------------------------------------
# Calibration solver
# ---------------------------------------------------------------------------

def solve_calibration(
    pixel_points: list[tuple[float, float]],
    arm_points: list[tuple[float, float]],
    z_offset_mm: float,
) -> CalibrationResult:
    """Fit affine transform from pixel coords to arm-frame mm.

    pixel_points: list of (px, py)
    arm_points:   list of (arm_x_mm, arm_y_mm) — ground truth from arm IK
    """
    if not CV_AVAILABLE:
        raise RuntimeError("OpenCV required for calibration solve")

    n = len(pixel_points)
    if n < MIN_POINTS:
        raise ValueError(f"Need at least {MIN_POINTS} points, got {n}")

    px = np.array([p[0] for p in pixel_points], dtype=float)
    py = np.array([p[1] for p in pixel_points], dtype=float)
    ax = np.array([p[0] for p in arm_points], dtype=float)
    ay = np.array([p[1] for p in arm_points], dtype=float)

    # Least-squares fit: arm_x = sx*px + ox
    A = np.column_stack([px, np.ones(n)])
    sx, ox = np.linalg.lstsq(A, ax, rcond=None)[0]

    A = np.column_stack([py, np.ones(n)])
    sy, oy = np.linalg.lstsq(A, ay, rcond=None)[0]

    # RMS reprojection error
    pred_ax = sx * px + ox
    pred_ay = sy * py + oy
    errs = np.sqrt((pred_ax - ax) ** 2 + (pred_ay - ay) ** 2)
    rms = float(np.sqrt(np.mean(errs ** 2)))

    log.info("Calibration solved: sx=%.4f sy=%.4f ox=%.1f oy=%.1f rms=%.2fmm",
             sx, sy, ox, oy, rms)

    return CalibrationResult(sx=sx, sy=sy, ox=ox, oy=oy,
                              z_offset=z_offset_mm, error_mm=rms)


# ---------------------------------------------------------------------------
# Red-marker detector (used to locate gripper tip in camera frame)
# ---------------------------------------------------------------------------

def detect_red_marker(frame) -> Optional[Tuple[float, float]]:
    """Find the centroid of the red calibration marker in a BGR frame."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Red wraps around hue=0/180
    mask1 = cv2.inRange(hsv, (0, 120, 70), (10, 255, 255))
    mask2 = cv2.inRange(hsv, (170, 120, 70), (180, 255, 255))
    mask = cv2.bitwise_or(mask1, mask2)

    mask = cv2.erode(mask, None, iterations=2)
    mask = cv2.dilate(mask, None, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 50:   # too small — probably noise
        return None

    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None

    cx = M["m10"] / M["m00"]
    cy = M["m01"] / M["m00"]
    return cx, cy


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------

def save_calibration(result: CalibrationResult) -> None:
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    log.info("Calibration saved to %s", CALIBRATION_FILE)


def load_calibration() -> Optional[CalibrationResult]:
    if not CALIBRATION_FILE.exists():
        return None
    with open(CALIBRATION_FILE) as f:
        return CalibrationResult.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# CLI wizard
# ---------------------------------------------------------------------------

def run_calibration_wizard() -> None:
    if not CV_AVAILABLE:
        print("OpenCV is required. Install with: pip install opencv-python")
        return

    print("\n=== ReachBot Camera Calibration Wizard ===")
    print("Attach a red sticker to the gripper tip.")
    print(f"You need at least {MIN_POINTS} calibration points.\n")

    z_offset = float(input("Camera height above floor (mm) [default 80]: ") or "80")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Could not open camera.")
        return

    pixel_points = []
    arm_points = []

    try:
        while True:
            print(f"\nPoint {len(pixel_points) + 1}:")
            input("  Move arm to a known position, then press Enter to capture...")

            for _ in range(5):
                cap.read()  # flush buffer
            ret, frame = cap.read()
            if not ret:
                print("  Camera read failed — try again.")
                continue

            marker = detect_red_marker(frame)
            if marker is None:
                print("  Red marker not detected. Check lighting and marker color.")
                continue

            px, py = marker
            print(f"  Marker detected at pixel ({px:.1f}, {py:.1f})")

            arm_x = float(input("  Enter arm X coordinate (mm): "))
            arm_y = float(input("  Enter arm Y coordinate (mm): "))

            pixel_points.append((px, py))
            arm_points.append((arm_x, arm_y))
            print(f"  Point recorded. Total: {len(pixel_points)}")

            if len(pixel_points) >= MIN_POINTS:
                more = input("\nAdd another point? (y/N): ").strip().lower()
                if more != "y":
                    break

    finally:
        cap.release()

    print("\nSolving calibration...")
    result = solve_calibration(pixel_points, arm_points, z_offset)
    print(f"Result: {result}")

    if result.error_mm > 15.0:
        print(f"WARNING: RMS error {result.error_mm:.1f}mm is high. "
              "Consider adding more points or checking marker detection.")

    save = input("\nSave calibration? (Y/n): ").strip().lower()
    if save != "n":
        save_calibration(result)
        print(f"Saved to {CALIBRATION_FILE}")


def run_live_test() -> None:
    if not CV_AVAILABLE:
        print("OpenCV required.")
        return

    cal = load_calibration()
    cap = cv2.VideoCapture(0)
    print("Live camera test — press Q to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        marker = detect_red_marker(frame)
        if marker:
            px, py = marker
            cv2.circle(frame, (int(px), int(py)), 8, (0, 255, 0), -1)
            if cal:
                ax, ay, az = cal.pixel_to_arm(px, py)
                cv2.putText(frame,
                            f"({ax:.0f}, {ay:.0f}, {az:.0f}) mm",
                            (int(px) + 12, int(py)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.imshow("ReachBot Calibration — Q to quit", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReachBot camera calibration")
    parser.add_argument("--test", action="store_true", help="Live camera overlay")
    parser.add_argument("--print", action="store_true", dest="print_cal",
                        help="Print stored calibration")
    args = parser.parse_args()

    if args.print_cal:
        cal = load_calibration()
        if cal:
            print(cal)
        else:
            print("No calibration file found. Run without flags to calibrate.")
    elif args.test:
        run_live_test()
    else:
        run_calibration_wizard()
