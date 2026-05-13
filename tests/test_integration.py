"""
Integration test — full pipeline in simulation.

Tests the complete voice → detect → move → grip → log sequence
without any hardware. Every module is real (not mocked); only
hardware I/O (servos, camera, GPIO, audio) is stubbed at the
boundary.

Run with: python -m pytest tests/test_integration.py -v
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from main import parse_target_object
from arm_control import ArmController
from object_detection import ObjectDetector, ObjectPosition
from safety import SafetyMonitor
from session_logger import SessionLogger
from tts import Speaker
import session_logger as sl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sim_arm():
    return ArmController(simulate=True)


@pytest.fixture
def stub_detector():
    with patch("object_detection.CV_AVAILABLE", False):
        d = ObjectDetector()
    return d


@pytest.fixture
def safety(sim_arm):
    with patch("safety.GPIO_AVAILABLE", False):
        m = SafetyMonitor(sim_arm, poll_interval_s=0.01)
    yield m
    if m._thread.is_alive():
        m.stop()


@pytest.fixture
def session(tmp_path):
    old = sl.LOG_DIR
    sl.LOG_DIR = tmp_path
    s = SessionLogger()
    yield s, tmp_path
    sl.LOG_DIR = old


@pytest.fixture
def speaker():
    with patch("tts.PYTTSX3_AVAILABLE", False):
        yield Speaker()


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_happy_path_voice_to_log(self, sim_arm, stub_detector,
                                      safety, session, speaker):
        """Complete: parse command → detect → move → grip → log."""
        logger, tmp_path = session

        # 1. Parse voice command
        command = "reachbot pick up my remote"
        target = parse_target_object(command)
        assert target == "remote"

        # 2. Detect
        speaker.confirm(target)
        position = stub_detector.find_object(target)
        assert position is not None

        # 3. Safety check
        assert safety.check_position(position.x, position.y, position.z)

        # 4. Log attempt
        attempt = logger.start_attempt(command, target)
        logger.log_detection(attempt, detected=True,
                              confidence=position.confidence,
                              x=position.x, y=position.y, z=position.z)

        # 5. Move arm (real IK + smooth motion — fast_sleep makes this instant)
        sim_arm.move_to(position)
        sim_arm.close_gripper(object_width_mm=position.estimated_width_mm)
        sim_arm.open_gripper()
        sim_arm.home()

        # 6. Finish log
        logger.finish_attempt(attempt, success=True, duration_s=1.2)
        speaker.done()

        # 7. Verify session log
        logs = list(tmp_path.glob("session_*.jsonl"))
        assert len(logs) == 1
        with open(logs[0]) as f:
            record = json.loads(f.readline())
        assert record["target_object"] == "remote"
        assert record["grasp_success"] is True
        assert record["object_detected"] is True

    def test_not_found_path(self, sim_arm, safety, session, speaker):
        """Pipeline when object isn't detected."""
        logger, tmp_path = session

        command = "grab my glasses"
        target = parse_target_object(command)
        assert target == "glasses"

        speaker.confirm(target)
        attempt = logger.start_attempt(command, target)

        # Simulate failed detection
        position = None
        logger.log_detection(attempt, detected=False)
        logger.finish_attempt(attempt, success=False,
                               failure_reason="not_found", duration_s=3.1)
        speaker.not_found(target)

        with open(list(tmp_path.glob("session_*.jsonl"))[0]) as f:
            record = json.loads(f.readline())
        assert record["grasp_success"] is False
        assert record["failure_reason"] == "not_found"
        assert record["object_detected"] is False

    def test_out_of_reach_path(self, sim_arm, safety, session, speaker):
        """Pipeline when position exceeds arm reach."""
        from config import MAX_REACH_MM
        logger, tmp_path = session

        attempt = logger.start_attempt("grab cup", "cup")

        # Position beyond reach
        ok = safety.check_position(MAX_REACH_MM + 200, 0, 0)
        assert ok is False

        logger.finish_attempt(attempt, success=False,
                               failure_reason="out_of_reach", duration_s=0.5)
        speaker.out_of_reach()

        with open(list(tmp_path.glob("session_*.jsonl"))[0]) as f:
            record = json.loads(f.readline())
        assert record["failure_reason"] == "out_of_reach"

    def test_multiple_attempts_summary(self, sim_arm, stub_detector,
                                        safety, session, speaker):
        """Three attempts: 2 success, 1 failure → correct summary stats."""
        logger, tmp_path = session

        objects = ["remote", "phone", "glasses"]
        successes = [True, True, False]

        for obj, success in zip(objects, successes):
            pos = stub_detector.find_object(obj)
            attempt = logger.start_attempt(f"grab {obj}", obj)
            logger.log_detection(attempt, detected=True,
                                  confidence=0.9, x=200, y=0, z=-80)
            if success:
                sim_arm.move_to(pos)
                sim_arm.close_gripper()
                sim_arm.home()
            logger.finish_attempt(attempt, success=success,
                                   failure_reason=None if success else "slip",
                                   duration_s=2.0)

        summary = logger.summary()
        assert summary["total"] == 3
        assert summary["successes"] == 2
        assert abs(summary["success_rate"] - 2/3) < 0.001


# ---------------------------------------------------------------------------
# Parse + detect pairings
# ---------------------------------------------------------------------------

class TestCommandToDetection:
    @pytest.mark.parametrize("command,expected_alias", [
        ("pick up the remote",     "remote"),
        ("grab my glasses",        "glasses"),
        ("get the phone",          "phone"),
        ("fetch my keys",          "keys"),
        ("pick up a bottle",       "bottle"),
        ("grab the cup",           "cup"),
    ])
    def test_command_maps_to_detectable_object(self, command, expected_alias,
                                                stub_detector):
        target = parse_target_object(command)
        assert target == expected_alias
        # Detector should handle this alias
        pos = stub_detector.find_object(target)
        assert pos is not None
        assert isinstance(pos, ObjectPosition)


# ---------------------------------------------------------------------------
# TTS wired into pipeline
# ---------------------------------------------------------------------------

class TestTTSInPipeline:
    def test_speaker_called_at_each_stage(self, stub_detector, speaker, capsys):
        """Verify TTS fires at the right points."""
        speaker.confirm("remote")
        time.sleep(0.05)
        out = capsys.readouterr().out
        assert "remote" in out

        speaker.found()
        time.sleep(0.05)
        out = capsys.readouterr().out
        assert len(out.strip()) > 0

        speaker.done()
        time.sleep(0.05)
        out = capsys.readouterr().out
        assert len(out.strip()) > 0

    def test_estop_fires_tts_before_home(self, sim_arm, safety, speaker, capsys):
        speaker.estop()  # blocking
        out = capsys.readouterr().out
        assert len(out.strip()) > 0
        # Arm should still respond after estop TTS
        sim_arm.home()
