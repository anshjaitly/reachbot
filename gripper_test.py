#!/usr/bin/env python3
"""
ReachBot — ORCA Hand Gripper Standalone Test

Tests the ORCA Hand without running the full ReachBot stack.
Use this during assembly to validate tendon routing and servo range.

Usage:
    python gripper_test.py               # Interactive menu
    python gripper_test.py --sweep       # Full open→close→open sweep
    python gripper_test.py --open        # Set to fully open (0°)
    python gripper_test.py --close       # Set to fully closed (90°)
    python gripper_test.py --angle 45    # Set to specific angle
    python gripper_test.py --width 80    # Set adaptive grip for 80mm object

On Raspberry Pi with PCA9685:
    pip install adafruit-circuitpython-servokit
    python gripper_test.py --sweep

Without hardware (simulation mode):
    Runs automatically — prints what angles would be sent.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import SERVO_GRIPPER, SERVO_LIMITS

# Adaptive close angle: matches arm_control.py formula
# angle = 90 * (1 - (width_mm - 32) / 168)
MIN_OBJ_MM = 32     # narrowest grippable object (pen)
MAX_OBJ_MM = 200    # widest grippable object (water bottle)
OPEN_ANGLE = 0
CLOSE_ANGLE = 90

GRIPPER_LO, GRIPPER_HI = SERVO_LIMITS.get(SERVO_GRIPPER, (0, 180))


def adaptive_angle(width_mm: float) -> float:
    """Return servo angle for a given object width (mm)."""
    width_mm = max(MIN_OBJ_MM, min(MAX_OBJ_MM, width_mm))
    ratio = (width_mm - MIN_OBJ_MM) / (MAX_OBJ_MM - MIN_OBJ_MM)
    angle = CLOSE_ANGLE * (1.0 - ratio)
    return max(GRIPPER_LO, min(GRIPPER_HI, angle))


def _init_servo():
    """Return a servo-setter function and a cleanup function."""
    try:
        from adafruit_servokit import ServoKit
        kit = ServoKit(channels=16)
        print("✓ PCA9685 detected — hardware mode")

        def set_angle(angle: float):
            kit.servo[SERVO_GRIPPER].angle = angle

        def cleanup():
            pass  # Leave servo at last position

        return set_angle, cleanup

    except Exception:
        print("⚠ adafruit_servokit not available — simulation mode")

        def set_angle(angle: float):
            print(f"  [SIM] Channel {SERVO_GRIPPER} → {angle:.1f}°")

        def cleanup():
            pass

        return set_angle, cleanup


def cmd_open(set_angle):
    print(f"Opening gripper → {OPEN_ANGLE}°")
    set_angle(OPEN_ANGLE)


def cmd_close(set_angle):
    print(f"Closing gripper → {CLOSE_ANGLE}°")
    set_angle(CLOSE_ANGLE)


def cmd_angle(set_angle, angle: float):
    clamped = max(GRIPPER_LO, min(GRIPPER_HI, angle))
    if clamped != angle:
        print(f"⚠ Angle {angle}° clamped to {clamped}° (limits {GRIPPER_LO}–{GRIPPER_HI}°)")
    print(f"Setting angle → {clamped:.1f}°")
    set_angle(clamped)


def cmd_width(set_angle, width_mm: float):
    angle = adaptive_angle(width_mm)
    print(f"Adaptive grip for {width_mm:.0f}mm object → {angle:.1f}°")
    set_angle(angle)


def cmd_sweep(set_angle):
    """Slow open → close → open sweep to check tendon routing."""
    print("Starting sweep: open → close → open")
    print("Watch that ALL fingers curl together uniformly.\n")

    # Open → close
    print("Phase 1: Opening fully...")
    set_angle(OPEN_ANGLE)
    time.sleep(1.0)

    print("Phase 2: Slowly closing...")
    for a in range(OPEN_ANGLE, CLOSE_ANGLE + 1, 3):
        set_angle(a)
        time.sleep(0.05)
    print(f"  ✓ Fully closed at {CLOSE_ANGLE}°")
    time.sleep(1.0)

    print("Phase 3: Slowly opening...")
    for a in range(CLOSE_ANGLE, OPEN_ANGLE - 1, -3):
        set_angle(a)
        time.sleep(0.05)
    print(f"  ✓ Fully open at {OPEN_ANGLE}°")

    print("\nSweep complete.")
    print("Expected: all 5 fingers curl to fist then fully extend.")
    print("If one finger lags → re-tension that tendon at servo horn.\n")


def cmd_interactive(set_angle):
    """Interactive menu for assembly testing."""
    print("\n=== ORCA Hand Gripper Test ===")
    print(f"Servo channel: {SERVO_GRIPPER}  |  Limits: {GRIPPER_LO}°–{GRIPPER_HI}°\n")

    objects = [
        ("Pen / pencil",      18),
        ("Phone",             70),
        ("TV remote",         50),
        ("Cup",               80),
        ("Water bottle",     160),
        ("Glasses case",      65),
    ]

    while True:
        print("Commands:")
        print("  o  — Open (0°)")
        print("  c  — Close (90°)")
        print("  s  — Slow sweep (assembly check)")
        print("  a  — Set angle manually")
        print("  w  — Set by object width")
        print("  g  — Grip test sequence (common objects)")
        print("  q  — Quit")
        cmd = input("\n> ").strip().lower()

        if cmd == "q":
            print("Setting to open before exit.")
            set_angle(OPEN_ANGLE)
            break
        elif cmd == "o":
            cmd_open(set_angle)
        elif cmd == "c":
            cmd_close(set_angle)
        elif cmd == "s":
            cmd_sweep(set_angle)
        elif cmd == "a":
            try:
                angle = float(input("  Angle (deg): "))
                cmd_angle(set_angle, angle)
            except ValueError:
                print("  Invalid angle.")
        elif cmd == "w":
            try:
                width = float(input("  Object width (mm): "))
                cmd_width(set_angle, width)
            except ValueError:
                print("  Invalid width.")
        elif cmd == "g":
            print("\nGrip test sequence — log successes for research data:")
            for name, width_mm in objects:
                angle = adaptive_angle(width_mm)
                print(f"\n  {name} ({width_mm}mm) → {angle:.1f}°")
                set_angle(OPEN_ANGLE)
                time.sleep(0.5)
                input(f"  Place {name.lower()}, press Enter to grip...")
                set_angle(angle)
                time.sleep(0.8)
                result = input("  Grip success? (y/n): ").strip().lower()
                print(f"  {'✓ SUCCESS' if result == 'y' else '✗ FAILED'} — {name}")
                set_angle(OPEN_ANGLE)
                time.sleep(0.4)
            print("\nGrip test complete. Log results in engineering notebook.")
        else:
            print("  Unknown command.")


def main():
    parser = argparse.ArgumentParser(
        description="ORCA Hand gripper standalone test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--sweep",  action="store_true", help="Run full sweep")
    parser.add_argument("--open",   action="store_true", help="Set to open (0°)")
    parser.add_argument("--close",  action="store_true", help="Set to closed (90°)")
    parser.add_argument("--angle",  type=float, metavar="DEG", help="Set to angle")
    parser.add_argument("--width",  type=float, metavar="MM",  help="Adaptive grip width")
    args = parser.parse_args()

    set_angle, cleanup = _init_servo()

    try:
        if args.sweep:
            cmd_sweep(set_angle)
        elif args.open:
            cmd_open(set_angle)
        elif args.close:
            cmd_close(set_angle)
        elif args.angle is not None:
            cmd_angle(set_angle, args.angle)
        elif args.width is not None:
            cmd_width(set_angle, args.width)
        else:
            cmd_interactive(set_angle)
    except KeyboardInterrupt:
        print("\nInterrupted — setting gripper to open.")
        set_angle(OPEN_ANGLE)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
