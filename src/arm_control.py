"""
ReachBot — Arm Controller

Controls the 4-axis arm (base rotation, shoulder, elbow, wrist) plus the
ORCA-modified single-servo gripper via a PCA9685 PWM driver.

Key improvements over the stub:
  - Smooth motion: servos move in small angle steps, not instant snaps
  - Wrist levelling: wrist roll adjusts so the gripper stays horizontal
  - Position tracking: current joint angles are remembered
  - Gripper width control: partial close based on detected object size
  - NEMA 17 stepper support for the base rotation axis (Phase 2)
  - move_to_user_hand() uses IK, not hardcoded angles
"""

import logging
import math
import time
from typing import Dict, Optional, Tuple

from config import (
    HOME_POSITION,
    LINK_BASE_TO_SHOULDER_MM,
    LINK_ELBOW_TO_WRIST_MM,
    LINK_SHOULDER_TO_ELBOW_MM,
    LINK_WRIST_TO_GRIPPER_MM,
    MAX_REACH_MM,
    SERVO_BASE_ROTATION,
    SERVO_ELBOW,
    SERVO_GRIPPER,
    SERVO_LIMITS,
    SERVO_SHOULDER,
    SERVO_WRIST_ROLL,
    GRIPPER_CLOSE_TIME_S,
)

log = logging.getLogger(__name__)

# Smooth motion settings
STEP_DEG = 3.0          # Max degrees per step during smooth motion
STEP_DELAY_S = 0.012    # Delay between steps (~80 steps/sec)

# User-hand delivery position in arm coordinates (mm)
DELIVERY_X_MM = 0.0     # Straight ahead
DELIVERY_Y_MM = 0.0
DELIVERY_Z_MM = 300.0   # ~30cm above shoulder (user can grab it here)

try:
    from adafruit_servokit import ServoKit
    SERVOKIT_AVAILABLE = True
except ImportError:
    SERVOKIT_AVAILABLE = False
    log.warning("adafruit_servokit not available — simulation mode")

try:
    # NEMA 17 driven via a stepper driver (e.g. DRV8825) connected to Pi GPIO
    import RPi.GPIO as GPIO
    STEPPER_AVAILABLE = True
except ImportError:
    STEPPER_AVAILABLE = False


class StepperDriver:
    """Simple step/dir stepper driver for NEMA 17 base rotation (Phase 2).

    Wired to the Pi with a DRV8825 or A4988 driver board.
    step_pin: GPIO BCM number for the STEP signal
    dir_pin:  GPIO BCM number for the DIR signal
    steps_per_rev: full steps per mechanical revolution (default 200)
    microstep: microstepping divisor set on the driver board (default 8)
    """

    def __init__(
        self,
        step_pin: int = 20,
        dir_pin: int = 21,
        steps_per_rev: int = 200,
        microstep: int = 8,
    ):
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self._steps_per_deg = (steps_per_rev * microstep) / 360.0
        self._current_deg = 180.0   # Home is at 180°
        self._available = STEPPER_AVAILABLE

        if self._available:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(step_pin, GPIO.OUT)
            GPIO.setup(dir_pin, GPIO.OUT)
            log.info("NEMA 17 stepper: step=%d dir=%d", step_pin, dir_pin)
        else:
            log.warning("NEMA 17 stepper: GPIO unavailable — simulation mode")

    def move_to(self, target_deg: float, rpm: float = 60.0) -> None:
        """Rotate to target_deg at the given RPM."""
        delta = target_deg - self._current_deg
        if abs(delta) < 0.1:
            return

        steps = int(abs(delta) * self._steps_per_deg)
        step_delay = 60.0 / (rpm * 200 * 8) / 2   # Half-period

        log.info(
            "[stepper] %.1f° → %.1f° (%d steps @ %.0f RPM)",
            self._current_deg, target_deg, steps, rpm,
        )

        if self._available:
            GPIO.output(self.dir_pin, GPIO.HIGH if delta > 0 else GPIO.LOW)
            for _ in range(steps):
                GPIO.output(self.step_pin, GPIO.HIGH)
                time.sleep(step_delay)
                GPIO.output(self.step_pin, GPIO.LOW)
                time.sleep(step_delay)
        else:
            time.sleep(steps * step_delay * 2)  # Simulate timing

        self._current_deg = target_deg

    def cleanup(self) -> None:
        if self._available:
            GPIO.cleanup([self.step_pin, self.dir_pin])


class ArmController:
    """High-level controller for ReachBot's 4-axis arm + gripper."""

    def __init__(self, simulate: bool = False):
        self.simulate = simulate or not SERVOKIT_AVAILABLE
        self.kit = None
        self._stepper: Optional[StepperDriver] = None

        # Track current angles so smooth motion knows where to start from
        self._current: Dict[int, float] = dict(HOME_POSITION)

        if self.simulate:
            log.info("ArmController: SIMULATION MODE")
        else:
            log.info("ArmController: hardware mode (PCA9685)")
            self.kit = ServoKit(channels=16)
            # Phase 2: instantiate stepper for base rotation
            # self._stepper = StepperDriver()

    # ------------------------------------------------------------------
    # Low-level servo control
    # ------------------------------------------------------------------

    def set_angle(self, channel: int, angle: float) -> None:
        """Set a servo to an angle, clamped to its defined limits."""
        lo, hi = SERVO_LIMITS.get(channel, (0, 180))
        clamped = max(lo, min(hi, angle))
        if abs(clamped - angle) > 0.5:
            log.warning(
                "Servo %d: %.1f° clamped to %.1f° (limits %d–%d)",
                channel, angle, clamped, lo, hi,
            )
        self._current[channel] = clamped
        if self.simulate:
            log.info("[sim] Servo %d → %.1f°", channel, clamped)
        else:
            self.kit.servo[channel].angle = clamped

    def set_angle_smooth(self, channel: int, target: float,
                         step: float = STEP_DEG) -> None:
        """Move a servo gradually from its current angle to target."""
        start = self._current.get(channel, target)
        delta = target - start
        if abs(delta) < step:
            self.set_angle(channel, target)
            return

        sign = 1 if delta > 0 else -1
        current = start
        while abs(target - current) > step:
            current += sign * step
            self.set_angle(channel, current)
            time.sleep(STEP_DELAY_S)
        self.set_angle(channel, target)

    # ------------------------------------------------------------------
    # High-level motion
    # ------------------------------------------------------------------

    def home(self) -> None:
        """Move all joints smoothly to their home positions."""
        log.info("Homing arm")
        # Open gripper first so it doesn't drag objects
        self.set_angle(SERVO_GRIPPER, HOME_POSITION[SERVO_GRIPPER])
        time.sleep(0.3)
        # Move the arm joints concurrently using small interleaved steps
        targets = {
            ch: ang for ch, ang in HOME_POSITION.items()
            if ch != SERVO_GRIPPER
        }
        self._move_joints_smooth(targets)

        # Home the stepper base if present
        if self._stepper:
            self._stepper.move_to(180.0)

    def shutdown(self) -> None:
        """Safely de-energise all servos."""
        log.info("Shutting down arm")
        if not self.simulate and self.kit is not None:
            for ch in SERVO_LIMITS:
                self.kit.servo[ch].angle = None
        if self._stepper:
            self._stepper.cleanup()

    def move_to(self, position) -> None:
        """Move the gripper to an ObjectPosition using 2-link planar IK.

        Also computes the wrist roll needed to keep the gripper horizontal
        (parallel to the floor) regardless of shoulder/elbow pose.
        """
        tx, ty, tz = position.x, position.y, position.z

        # --- Base rotation ---
        azimuth_deg = math.degrees(math.atan2(ty, tx))
        base_target = 180.0 + azimuth_deg   # Servo zero = facing forward

        if self._stepper:
            self._stepper.move_to(base_target)
            base_servo_target = 180.0        # Stepper handles rotation; servo neutral
        else:
            base_servo_target = base_target

        # --- 2-link IK (shoulder + elbow) ---
        radius_mm = math.sqrt(tx ** 2 + ty ** 2)
        height_mm = tz + LINK_BASE_TO_SHOULDER_MM

        L1 = LINK_SHOULDER_TO_ELBOW_MM
        L2 = LINK_ELBOW_TO_WRIST_MM + LINK_WRIST_TO_GRIPPER_MM
        d = math.sqrt(radius_mm ** 2 + height_mm ** 2)

        if d > MAX_REACH_MM:
            log.error("Target out of reach: %.0fmm > max %.0fmm", d, MAX_REACH_MM)
            return

        if d > L1 + L2:
            log.error("IK unreachable: distance %.0fmm > %.0fmm", d, L1 + L2)
            return

        if d < abs(L1 - L2):
            log.error("IK unreachable: target too close (%.0fmm)", d)
            return

        cos_elbow = (L1 ** 2 + L2 ** 2 - d ** 2) / (2 * L1 * L2)
        cos_elbow = max(-1.0, min(1.0, cos_elbow))
        elbow_rad = math.acos(cos_elbow)
        elbow_deg = math.degrees(elbow_rad)

        alpha = math.atan2(height_mm, radius_mm)
        cos_beta = (L1 ** 2 + d ** 2 - L2 ** 2) / (2 * L1 * d)
        cos_beta = max(-1.0, min(1.0, cos_beta))
        beta = math.acos(cos_beta)
        shoulder_deg = math.degrees(alpha + beta)

        # --- Wrist levelling ---
        # Keep the gripper horizontal: wrist_roll = 90 + shoulder - elbow
        # (compensates for the combined bend of the two links)
        wrist_deg = 90.0 + shoulder_deg - elbow_deg
        lo, hi = SERVO_LIMITS.get(SERVO_WRIST_ROLL, (0, 180))
        wrist_deg = max(lo, min(hi, wrist_deg))

        log.info(
            "IK → base=%.0f° shoulder=%.0f° elbow=%.0f° wrist=%.0f°",
            base_servo_target, shoulder_deg, elbow_deg, wrist_deg,
        )

        # Move in a safe order: base → shoulder → elbow → wrist
        self._move_joints_smooth({
            SERVO_BASE_ROTATION: base_servo_target,
        })
        time.sleep(0.2)
        self._move_joints_smooth({
            SERVO_SHOULDER: shoulder_deg,
            SERVO_ELBOW: elbow_deg,
            SERVO_WRIST_ROLL: wrist_deg,
        })

    def move_to_user_hand(self) -> None:
        """Move arm to delivery position using IK so the user can take the object."""
        log.info("Moving to delivery position")

        from object_detection import ObjectPosition
        delivery = ObjectPosition(
            x=DELIVERY_X_MM,
            y=DELIVERY_Y_MM,
            z=DELIVERY_Z_MM,
            confidence=1.0,
            class_name="delivery",
        )
        self.move_to(delivery)

    # ------------------------------------------------------------------
    # Gripper
    # ------------------------------------------------------------------

    def close_gripper(self, object_width_mm: Optional[float] = None) -> None:
        """Close the ORCA hand.

        If object_width_mm is provided, close only as much as needed so the
        gripper matches the object size rather than fully fisting.
        """
        if object_width_mm is not None:
            # Estimate gripper angle from object width
            # Gripper span: 0° = 200mm open, 90° = 32mm closed (from engineering calcs)
            max_span = 200.0
            min_span = 32.0
            clamped_w = max(min_span, min(max_span, object_width_mm))
            angle = 90.0 * (1.0 - (clamped_w - min_span) / (max_span - min_span))
            log.info("Gripper: closing to %.0f° for %.0fmm object", angle, object_width_mm)
        else:
            angle = 90.0    # Full fist close

        self.set_angle_smooth(SERVO_GRIPPER, angle, step=5.0)
        time.sleep(GRIPPER_CLOSE_TIME_S)

    def open_gripper(self) -> None:
        """Open the gripper fully."""
        log.info("Gripper: opening")
        self.set_angle_smooth(SERVO_GRIPPER, 0.0, step=5.0)
        time.sleep(0.5)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _move_joints_smooth(self, targets: Dict[int, float]) -> None:
        """Move multiple joints simultaneously using interleaved steps.

        Each joint advances one STEP_DEG per iteration so they all arrive
        at roughly the same time.
        """
        # Build per-channel (current, target, direction, remaining) table
        motion = {}
        for ch, target in targets.items():
            start = self._current.get(ch, target)
            delta = target - start
            if abs(delta) > 0.1:
                motion[ch] = {
                    "target": target,
                    "sign": 1 if delta > 0 else -1,
                }

        if not motion:
            return

        while motion:
            done = []
            for ch, m in motion.items():
                current = self._current.get(ch, m["target"])
                remaining = abs(m["target"] - current)
                if remaining <= STEP_DEG:
                    self.set_angle(ch, m["target"])
                    done.append(ch)
                else:
                    self.set_angle(ch, current + m["sign"] * STEP_DEG)
            for ch in done:
                del motion[ch]
            if motion:
                time.sleep(STEP_DELAY_S)
