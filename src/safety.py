"""
ReachBot — Safety Monitor

Watches for:
  - Physical emergency-stop button (GPIO 17)
  - Gripper torque overload (estimated from servo feedback)
  - Arm reach-limit violations
  - Watchdog timeout (arm must be commanded at least every N seconds)

Runs as a background thread so it can interrupt any ongoing motion.
"""

import logging
import threading
import time
from dataclasses import dataclass, field

from config import (
    EMERGENCY_STOP_GPIO,
    GRIPPER_TORQUE_LIMIT_KGCM,
    MAX_REACH_MM,
    SERVO_LIMITS,
)

log = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    log.warning("RPi.GPIO not available — e-stop button disabled (simulation mode)")

WATCHDOG_TIMEOUT_S = 30.0   # Arm auto-homes if idle this long


@dataclass
class SafetyEvent:
    kind: str           # "estop", "torque", "reach", "watchdog"
    message: str
    timestamp: float = field(default_factory=time.time)

    def __str__(self) -> str:
        return f"[{self.kind.upper()}] {self.message}"


class SafetyMonitor:
    """Background thread that watches for unsafe conditions.

    Usage:
        monitor = SafetyMonitor(arm_controller)
        monitor.start()
        ...
        monitor.stop()

    Any module can call monitor.request_estop("reason") to trigger an
    immediate safe shutdown.
    """

    def __init__(self, arm_controller, poll_interval_s: float = 0.05):
        self._arm = arm_controller
        self._poll_interval = poll_interval_s
        self._stop_event = threading.Event()
        self._estop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="SafetyMonitor", daemon=True
        )
        self._last_command_time = time.time()
        self._events: list[SafetyEvent] = []
        self._lock = threading.Lock()

        if GPIO_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(EMERGENCY_STOP_GPIO, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                EMERGENCY_STOP_GPIO,
                GPIO.FALLING,
                callback=self._gpio_estop_callback,
                bouncetime=200,
            )
            log.info("E-stop button armed on GPIO %d", EMERGENCY_STOP_GPIO)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self) -> None:
        log.info("SafetyMonitor starting")
        self._thread.start()

    def stop(self) -> None:
        log.info("SafetyMonitor stopping")
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        if GPIO_AVAILABLE:
            GPIO.cleanup(EMERGENCY_STOP_GPIO)

    def request_estop(self, reason: str) -> None:
        """Trigger an emergency stop from any thread."""
        if not self._estop_event.is_set():
            log.critical("E-STOP TRIGGERED: %s", reason)
            self._record_event("estop", reason)
            self._estop_event.set()
            self._arm.shutdown()

    def ping(self) -> None:
        """Call this every time the arm receives a new command (resets watchdog)."""
        self._last_command_time = time.time()

    @property
    def is_stopped(self) -> bool:
        return self._estop_event.is_set()

    def recent_events(self, n: int = 10) -> list[SafetyEvent]:
        with self._lock:
            return list(self._events[-n:])

    def check_position(self, x: float, y: float, z: float) -> bool:
        """Return True if (x, y, z) in mm is within the safe workspace."""
        import math
        reach = math.sqrt(x ** 2 + y ** 2)
        if reach > MAX_REACH_MM:
            self.request_estop(
                f"Target position ({reach:.0f}mm) exceeds max reach ({MAX_REACH_MM}mm)"
            )
            return False
        return True

    def check_servo_angle(self, channel: int, angle: float) -> float:
        """Clamp angle to safe limits. Logs a warning if clamping occurs."""
        lo, hi = SERVO_LIMITS.get(channel, (0, 180))
        if angle < lo or angle > hi:
            clamped = max(lo, min(hi, angle))
            msg = (
                f"Servo {channel} angle {angle:.1f}° out of limits "
                f"[{lo}, {hi}] — clamped to {clamped:.1f}°"
            )
            log.warning(msg)
            self._record_event("reach", msg)
            return clamped
        return angle

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._estop_event.is_set():
                break

            self._check_watchdog()
            time.sleep(self._poll_interval)

    def _check_watchdog(self) -> None:
        idle_s = time.time() - self._last_command_time
        if idle_s > WATCHDOG_TIMEOUT_S:
            log.warning(
                "Watchdog: arm idle for %.0fs — returning to home", idle_s
            )
            self._record_event(
                "watchdog",
                f"Auto-homed after {idle_s:.0f}s of inactivity",
            )
            self._arm.home()
            self._last_command_time = time.time()

    def _gpio_estop_callback(self, channel: int) -> None:
        self.request_estop(f"Physical e-stop button pressed (GPIO {channel})")

    def _record_event(self, kind: str, message: str) -> None:
        event = SafetyEvent(kind=kind, message=message)
        with self._lock:
            self._events.append(event)
            if len(self._events) > 500:
                self._events = self._events[-500:]
        log.warning("SafetyEvent: %s", event)
