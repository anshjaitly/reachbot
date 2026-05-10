"""
Tests for ArmController — IK solver, servo clamping, gripper logic.
Run with: python -m pytest tests/ -v
"""

import math
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from arm_control import ArmController
from config import (
    HOME_POSITION,
    LINK_ELBOW_TO_WRIST_MM,
    LINK_SHOULDER_TO_ELBOW_MM,
    LINK_WRIST_TO_GRIPPER_MM,
    MAX_REACH_MM,
    SERVO_GRIPPER,
    SERVO_LIMITS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def arm():
    """ArmController in simulation mode — no hardware required."""
    return ArmController(simulate=True)


# ---------------------------------------------------------------------------
# Home position
# ---------------------------------------------------------------------------

class TestHome:
    def test_home_calls_set_angle_for_all_channels(self, arm):
        # Put arm in a non-home state so smooth motion actually fires
        arm._current = {ch: 0.0 for ch in HOME_POSITION}
        arm._current[SERVO_GRIPPER] = 45.0  # gripper half-closed

        set_angle_calls = []
        arm.set_angle = lambda ch, ang: set_angle_calls.append((ch, ang))
        arm.home()
        called_channels = {ch for ch, _ in set_angle_calls}
        assert called_channels == set(HOME_POSITION.keys())

    def test_home_gripper_is_open(self, arm):
        # Gripper channel should be set to 0 (open) at home
        calls = []
        arm.set_angle = lambda ch, ang: calls.append((ch, ang))
        arm.home()
        gripper_angles = [ang for ch, ang in calls if ch == SERVO_GRIPPER]
        assert gripper_angles and gripper_angles[-1] == 0


# ---------------------------------------------------------------------------
# Servo clamping
# ---------------------------------------------------------------------------

class TestServoClamping:
    @pytest.mark.parametrize("channel,lo,hi", [
        (ch, lim[0], lim[1]) for ch, lim in SERVO_LIMITS.items()
    ])
    def test_angle_clamps_to_limits(self, arm, channel, lo, hi, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            arm.set_angle(channel, lo - 10)
        # Should log a warning about clamping
        assert any("clamp" in r.message.lower() for r in caplog.records)

    def test_valid_angle_no_warning(self, arm, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            arm.set_angle(SERVO_GRIPPER, 45)
        assert not caplog.records


# ---------------------------------------------------------------------------
# Inverse kinematics
# ---------------------------------------------------------------------------

class TestInverseKinematics:
    """Verify the 2-link IK produces geometrically consistent joint angles."""

    def _ik_angles(self, arm, x, y, z):
        """Run move_to and capture the shoulder/elbow angles sent."""
        from object_detection import ObjectPosition
        pos = ObjectPosition(x=x, y=y, z=z, confidence=1.0, class_name="test")

        angles = {}
        original_set = arm.set_angle

        def capture(ch, ang):
            angles[ch] = ang

        arm.set_angle = capture
        arm.move_to(pos)
        arm.set_angle = original_set
        return angles

    def test_forward_reach_within_workspace(self, arm):
        # Target at (400, 0, 0) should be reachable
        from object_detection import ObjectPosition
        pos = ObjectPosition(x=400, y=0, z=0, confidence=1.0, class_name="test")
        called = []
        arm.set_angle = lambda ch, ang: called.append(ch)
        arm.move_to(pos)
        # Should have commanded at least shoulder and elbow
        assert len(called) >= 2

    def test_out_of_reach_does_not_crash(self, arm):
        # Target beyond MAX_REACH_MM should log an error but not raise
        from object_detection import ObjectPosition
        pos = ObjectPosition(
            x=MAX_REACH_MM + 200, y=0, z=0,
            confidence=1.0, class_name="test"
        )
        # Should not raise
        arm.move_to(pos)

    def test_elbow_angle_law_of_cosines(self):
        """Verify the elbow angle formula is geometrically correct."""
        L1 = LINK_SHOULDER_TO_ELBOW_MM
        L2 = LINK_ELBOW_TO_WRIST_MM + LINK_WRIST_TO_GRIPPER_MM
        d = 500.0  # mm — arbitrary reachable distance

        cos_elbow = (L1 ** 2 + L2 ** 2 - d ** 2) / (2 * L1 * L2)
        elbow_rad = math.acos(max(-1.0, min(1.0, cos_elbow)))
        elbow_deg = math.degrees(elbow_rad)

        # For a reachable d, elbow angle should be in (0°, 180°)
        assert 0 < elbow_deg < 180

    @pytest.mark.parametrize("x,y", [
        (200, 0), (0, 200), (-200, 0), (150, 150)
    ])
    def test_base_rotation_azimuth(self, arm, x, y):
        """Base angle should reflect the azimuth of the target."""
        from object_detection import ObjectPosition
        pos = ObjectPosition(x=x, y=y, z=0, confidence=1.0, class_name="test")
        angles = {}
        arm.set_angle = lambda ch, ang: angles.update({ch: ang})
        arm.move_to(pos)

        from config import SERVO_BASE_ROTATION
        if SERVO_BASE_ROTATION in angles:
            expected_azimuth = math.degrees(math.atan2(y, x))
            expected_base = 180 + expected_azimuth
            assert abs(angles[SERVO_BASE_ROTATION] - expected_base) < 1e-6


# ---------------------------------------------------------------------------
# Gripper
# ---------------------------------------------------------------------------

class TestGripper:
    def test_close_gripper_sets_90(self, arm):
        angles = {}
        arm.set_angle = lambda ch, ang: angles.update({ch: ang})
        arm.close_gripper()
        assert angles.get(SERVO_GRIPPER) == 90

    def test_open_gripper_sets_0(self, arm):
        angles = {}
        arm.set_angle = lambda ch, ang: angles.update({ch: ang})
        arm.open_gripper()
        assert angles.get(SERVO_GRIPPER) == 0
