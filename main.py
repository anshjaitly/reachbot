"""
ReachBot — Main Orchestrator

Coordinates voice input, object detection, arm control, safety monitoring,
session logging, and the optional web dashboard.

Usage:
    python main.py                     # Run with hardware
    python main.py --simulate          # Run without hardware (logs actions only)
    python main.py --simulate --web    # Also start web dashboard on port 8000

Project: https://reachbot-arm.netlify.app/
License: MIT
"""

import argparse
import logging
import sys
import time
import threading
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent / "src"))

from voice_command import VoiceCommandListener
from object_detection import ObjectDetector
from arm_control import ArmController
from safety import SafetyMonitor
from session_logger import SessionLogger
from config import OBJECT_CLASSES, WAKE_WORD


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("reachbot")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(simulate: bool = False, web: bool = False) -> None:
    log.info("ReachBot starting (simulate=%s, web=%s)", simulate, web)

    arm = ArmController(simulate=simulate)
    safety = SafetyMonitor(arm)
    session = SessionLogger()
    voice = VoiceCommandListener(wake_word=WAKE_WORD)
    detector = ObjectDetector(model="yolov8n.pt", confidence=0.5)

    safety.start()
    arm.home()
    safety.ping()

    if web:
        _start_web_server(arm, session, safety)

    log.info("Ready. Say '%s, pick up my [object]' to begin.", WAKE_WORD)

    try:
        while True:
            if safety.is_stopped:
                log.critical("E-stop active — waiting for manual reset")
                time.sleep(5)
                continue

            # 1. Listen
            command = voice.listen()
            if command is None:
                continue

            log.info("Command: %s", command)
            safety.ping()

            # 2. Parse target
            target = parse_target_object(command)
            if target is None:
                log.warning("Could not parse target from: %r", command)
                continue

            if target not in OBJECT_CLASSES:
                log.warning("Object %r not in supported classes", target)
                continue

            attempt = session.start_attempt(command, target)
            t_start = time.time()

            # 3. Detect
            log.info("Searching for: %s", target)
            position = detector.find_object(target)

            if position is None:
                log.warning("Object %r not found in view", target)
                session.log_detection(attempt, detected=False)
                session.finish_attempt(
                    attempt, success=False,
                    failure_reason="not_found",
                    duration_s=time.time() - t_start,
                )
                continue

            log.info("Found: %s", position)
            session.log_detection(
                attempt, detected=True,
                confidence=position.confidence,
                x=position.x, y=position.y, z=position.z,
            )

            # 4. Safety check before moving
            if not safety.check_position(position.x, position.y, position.z):
                session.finish_attempt(
                    attempt, success=False,
                    failure_reason="out_of_reach",
                    duration_s=time.time() - t_start,
                )
                continue

            # 5. Grasp
            arm.move_to(position)
            safety.ping()
            arm.close_gripper(object_width_mm=position.estimated_width_mm)
            time.sleep(0.5)

            # 6. Return to user
            arm.move_to_user_hand()
            arm.open_gripper()
            arm.home()
            safety.ping()

            session.finish_attempt(
                attempt, success=True,
                duration_s=time.time() - t_start,
            )

    except KeyboardInterrupt:
        log.info("Shutting down (Ctrl+C)")
    finally:
        safety.stop()
        arm.shutdown()
        session.print_summary()


def parse_target_object(command: str) -> Optional[str]:
    """Extract target object from a voice command string.

    Supports phrases like:
        - "pick up my glasses"
        - "grab the remote"
        - "get me the phone"
    """
    command = command.lower().strip()
    triggers = ["pick up", "grab", "get", "fetch"]

    for trigger in triggers:
        if trigger in command:
            tail = command.split(trigger, 1)[1].strip()
            # Strip chained fillers ("me the", "me my", etc.)
            fillers = ("my ", "the ", "a ", "me ")
            changed = True
            while changed:
                changed = False
                for filler in fillers:
                    if tail.startswith(filler):
                        tail = tail[len(filler):].strip()
                        changed = True
            for filler in (" my ", " the ", " a ", " me "):
                tail = tail.replace(filler, " ")
            return tail.split()[0] if tail else None
    return None


def _start_web_server(arm, session, safety) -> None:
    try:
        import uvicorn
        from web_interface import app, inject_dependencies, FASTAPI_AVAILABLE
        if not FASTAPI_AVAILABLE:
            log.warning("FastAPI not installed — web dashboard disabled")
            return
        inject_dependencies(arm, session, safety)

        def _run():
            uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

        t = threading.Thread(target=_run, name="WebDashboard", daemon=True)
        t.start()
        log.info("Web dashboard running at http://0.0.0.0:8000")
    except ImportError:
        log.warning("uvicorn not installed — web dashboard disabled")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReachBot main controller")
    parser.add_argument(
        "--simulate", action="store_true",
        help="Run without hardware (logs actions only)"
    )
    parser.add_argument(
        "--web", action="store_true",
        help="Start web dashboard on port 8000"
    )
    args = parser.parse_args()
    main(simulate=args.simulate, web=args.web)
