"""
ReachBot — Arm Controller

Servo control + 2-link planar inverse kinematics for the 4-axis arm.
Uses Adafruit PCA9685 over I2C for PWM generation.
"""

import logging
import math
import time

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
)

log = logging.getLogger(__name__)

try:
    from adafruit_servokit import ServoKit
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False
    log.warning(
        "adafruit_servokit not available — arm running in simulation mode"
    )


class ArmController:
    """High-level controller for ReachBot's 4-axis arm + gripper."""

    def __init__(self, simulate: bool = False):
        self.simulate = simulate or not HARDWARE_AVAILABLE
        if self.simulate:
            log.info("ArmController: SIMULATION MODE (no hardware)")
            self.kit = None
        else:
            log.info("ArmController: hardware mode (PCA9685)")
            self.kit = ServoKit(channels=16)

    # ------------------------------------------------------------------
    # Low-level servo commands
    # ------------------------------------------------------------------
    def set_angle(self, channel: int, angle: float) -> None:
        """Set a servo to a specific angle, clamped to its limits."""
        lo, hi = SERVO_LIMITS.get(channel, (0, 180))
        clamped = max(lo, min(hi, angle))
        if clamped != angle:
            log.warning(
                "Servo %d angle %.1f clamped to %.1f", channel, angle, clamped
            )
        if self.simulate:
            log.info("[sim] Servo %d -> %.1f deg", channel, clamped)
        else:
            self.kit.servo[channel].angle = clamped

    def home(self) -> None:
        """Move all servos to their home positions."""
        log.info("Moving to home position")
        for channel, angle in HOME_POSITION.items():
            self.set_angle(channel, angle)
        time.sleep(1.0)

    def shutdown(self) -> None:
        """Safely de-energize the arm (release all torque)."""
        log.info("Shutting down arm")
        if not self.simulate and self.kit is not None:
            for channel in SERVO_LIMITS.keys():
                self.kit.servo[channel].angle = None  # Disable

    # ------------------------------------------------------------------
    # Kinematics
    # ------------------------------------------------------------------
    def move_to(self, position) -> None:
        """Move the arm so the gripper reaches the target ObjectPosition.

        Two-link planar IK in the (radius, height) plane, plus base
        rotation for azimuth.
        """
        target_x, target_y, target_z = position.x, position.y, position.z

        # Azimuth (base rotation)
        azimuth_deg = math.degrees(math.atan2(target_y, target_x))
        base_angle = 180 + azimuth_deg  # Servo zeros at 180 (forward)
        log.debug("Azimuth: %.1f deg, base angle: %.1f", azimuth_deg, base_angle)

        # Radius from base
        radius_mm = math.sqrt(target_x ** 2 + target_y ** 2)
        height_mm = target_z + LINK_BASE_TO_SHOULDER_MM

        if radius_mm > MAX_REACH_MM:
            log.error(
                "Target out of reach: %.0fmm > max %.0fmm",
                radius_mm, MAX_REACH_MM,
            )
            return

        # Solve 2-link IK (shoulder, elbow) — ignore wrist + gripper offset
        # for first pass; refine in v2
        L1 = LINK_SHOULDER_TO_ELBOW_MM
        L2 = LINK_ELBOW_TO_WRIST_MM + LINK_WRIST_TO_GRIPPER_MM
        d_sq = radius_mm ** 2 + height_mm ** 2
        d = math.sqrt(d_sq)

        if d > L1 + L2:
            log.error("Target unreachable by IK: distance %.0f > %.0f", d, L1 + L2)
            return

        # Elbow angle (law of cosines)
        cos_elbow = (L1 ** 2 + L2 ** 2 - d_sq) / (2 * L1 * L2)
        cos_elbow = max(-1.0, min(1.0, cos_elbow))
        elbow_rad = math.acos(cos_elbow)
        elbow_deg = math.degrees(elbow_rad)

        # Shoulder angle
        alpha = math.atan2(height_mm, radius_mm)
        cos_beta = (L1 ** 2 + d_sq - L2 ** 2) / (2 * L1 * d)
        cos_beta = max(-1.0, min(1.0, cos_beta))
        beta = math.acos(cos_beta)
        shoulder_deg = math.degrees(alpha + beta)

        log.info(
            "IK: base=%.0f, shoulder=%.0f, elbow=%.0f",
            base_angle, shoulder_deg, elbow_deg,
        )

        # Move servos in order
        self.set_angle(SERVO_BASE_ROTATION, base_angle)
        time.sleep(0.5)
        self.set_angle(SERVO_SHOULDER, shoulder_deg)
        self.set_angle(SERVO_ELBOW, elbow_deg)
        self.set_angle(SERVO_WRIST_ROLL, 90)  # Neutral
        time.sleep(1.0)

    def move_to_user_hand(self) -> None:
        """Move arm so user can take the held object."""
        log.info("Returning to user")
        self.set_angle(SERVO_BASE_ROTATION, 180)  # Forward
        self.set_angle(SERVO_SHOULDER, 45)        # Up
        self.set_angle(SERVO_ELBOW, 90)
        self.set_angle(SERVO_WRIST_ROLL, 90)
        time.sleep(1.0)

    # ------------------------------------------------------------------
    # Gripper
    # ------------------------------------------------------------------
    def close_gripper(self) -> None:
        """Close the ORCA-modified hand into a fist."""
        log.info("Closing gripper")
        self.set_angle(SERVO_GRIPPER, 90)
        time.sleep(1.0)

    def open_gripper(self) -> None:
        """Open the gripper."""
        log.info("Opening gripper")
        self.set_angle(SERVO_GRIPPER, 0)
        time.sleep(1.0)
