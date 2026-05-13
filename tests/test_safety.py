"""
Tests for SafetyMonitor — watchdog, servo clamping, position checks, e-stop.
Run with: python -m pytest tests/ -v
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from safety import SafetyMonitor, SafetyEvent, WATCHDOG_TIMEOUT_S
from config import SERVO_LIMITS, MAX_REACH_MM


@pytest.fixture
def arm():
    mock = MagicMock()
    mock.home = MagicMock()
    mock.shutdown = MagicMock()
    return mock


@pytest.fixture
def monitor(arm):
    with patch("safety.GPIO_AVAILABLE", False):
        m = SafetyMonitor(arm, poll_interval_s=0.01)
    yield m
    if m._thread.is_alive():
        m.stop()


# ---------------------------------------------------------------------------
# Servo angle clamping
# ---------------------------------------------------------------------------

class TestServoAngleClamping:
    def test_angle_within_limits_passes_through(self, monitor):
        # Channel 0 limits are [0, 180] per default config
        ch = list(SERVO_LIMITS.keys())[0]
        lo, hi = SERVO_LIMITS[ch]
        mid = (lo + hi) / 2
        result = monitor.check_servo_angle(ch, mid)
        assert result == mid

    def test_angle_below_min_is_clamped(self, monitor):
        ch = list(SERVO_LIMITS.keys())[0]
        lo, hi = SERVO_LIMITS[ch]
        result = monitor.check_servo_angle(ch, lo - 20)
        assert result == lo

    def test_angle_above_max_is_clamped(self, monitor):
        ch = list(SERVO_LIMITS.keys())[0]
        lo, hi = SERVO_LIMITS[ch]
        result = monitor.check_servo_angle(ch, hi + 20)
        assert result == hi

    def test_clamping_logs_warning(self, monitor, caplog):
        import logging
        ch = list(SERVO_LIMITS.keys())[0]
        lo, hi = SERVO_LIMITS[ch]
        with caplog.at_level(logging.WARNING):
            monitor.check_servo_angle(ch, hi + 50)
        assert any("clamp" in r.message.lower() for r in caplog.records)

    def test_valid_angle_no_event_recorded(self, monitor):
        ch = list(SERVO_LIMITS.keys())[0]
        lo, hi = SERVO_LIMITS[ch]
        before = len(monitor.recent_events())
        monitor.check_servo_angle(ch, (lo + hi) // 2)
        assert len(monitor.recent_events()) == before


# ---------------------------------------------------------------------------
# Position checks
# ---------------------------------------------------------------------------

class TestPositionChecks:
    def test_position_within_reach_passes(self, monitor, arm):
        ok = monitor.check_position(200, 0, 0)
        assert ok is True
        arm.shutdown.assert_not_called()

    def test_position_at_exact_max_passes(self, monitor, arm):
        # On the boundary is still ok
        ok = monitor.check_position(MAX_REACH_MM, 0, 0)
        assert ok is True

    def test_position_beyond_max_triggers_estop(self, monitor, arm):
        ok = monitor.check_position(MAX_REACH_MM + 100, 0, 0)
        assert ok is False
        arm.shutdown.assert_called_once()

    def test_diagonal_beyond_reach_triggers_estop(self, monitor, arm):
        import math
        # x=y such that sqrt(x²+y²) > MAX_REACH_MM
        side = (MAX_REACH_MM / math.sqrt(2)) + 50
        ok = monitor.check_position(side, side, 0)
        assert ok is False


# ---------------------------------------------------------------------------
# E-stop
# ---------------------------------------------------------------------------

class TestEstop:
    def test_request_estop_calls_arm_shutdown(self, monitor, arm):
        monitor.request_estop("test reason")
        arm.shutdown.assert_called_once()

    def test_is_stopped_after_estop(self, monitor, arm):
        assert not monitor.is_stopped
        monitor.request_estop("test")
        assert monitor.is_stopped

    def test_duplicate_estop_only_shuts_down_once(self, monitor, arm):
        monitor.request_estop("first")
        monitor.request_estop("second")
        arm.shutdown.assert_called_once()

    def test_estop_records_event(self, monitor, arm):
        monitor.request_estop("something bad")
        events = monitor.recent_events()
        assert any(e.kind == "estop" for e in events)


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------

class TestWatchdog:
    def test_ping_resets_watchdog_timer(self, monitor):
        # After ping, last_command_time should be recent
        monitor.ping()
        assert time.time() - monitor._last_command_time < 0.5

    def test_watchdog_fires_after_timeout(self, monitor, arm):
        # Wind the clock back past the timeout
        monitor._last_command_time = time.time() - (WATCHDOG_TIMEOUT_S + 1)
        monitor._check_watchdog()
        arm.home.assert_called_once()

    def test_watchdog_resets_timer_after_firing(self, monitor, arm):
        monitor._last_command_time = time.time() - (WATCHDOG_TIMEOUT_S + 1)
        monitor._check_watchdog()
        # Timer should be reset to now
        assert time.time() - monitor._last_command_time < 1.0

    def test_watchdog_does_not_fire_when_recent(self, monitor, arm):
        monitor.ping()
        monitor._check_watchdog()
        arm.home.assert_not_called()


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

class TestEventLog:
    def test_recent_events_empty_at_start(self, monitor):
        assert monitor.recent_events() == []

    def test_recent_events_capped_at_n(self, monitor, arm):
        for i in range(5):
            monitor.request_estop(f"event {i}")
        events = monitor.recent_events(n=3)
        assert len(events) <= 3

    def test_safety_event_str_contains_kind(self):
        e = SafetyEvent(kind="watchdog", message="idle too long")
        assert "WATCHDOG" in str(e)
        assert "idle too long" in str(e)
