"""
ReachBot — Main Orchestrator

Coordinates voice input, object detection, and arm control.

Usage:
    python main.py              # Run with hardware
    python main.py --simulate   # Run without hardware (logs actions only)

Project: https://reachbot-arm.netlify.app/
License: MIT
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from voice_command import VoiceCommandListener
from object_detection import ObjectDetector
from arm_control import ArmController
from config import OBJECT_CLASSES, WAKE_WORD


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("reachbot")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main(simulate: bool = False) -> None:
    """Main event loop. Listen → detect → grasp → return."""
    log.info("ReachBot starting (simulate=%s)", simulate)

    voice = VoiceCommandListener(wake_word=WAKE_WORD)
    detector = ObjectDetector(model="yolov8n.pt", confidence=0.5)
    arm = ArmController(simulate=simulate)

    arm.home()
    log.info("Ready. Say '%s, pick up my [object]' to begin.", WAKE_WORD)

    try:
        while True:
            # 1. Listen for voice command
            command = voice.listen()
            if command is None:
                continue

            log.info("Command received: %s", command)

            # 2. Parse target object
            target = parse_target_object(command)
            if target is None:
                log.warning("Could not parse target object from: %s", command)
                continue

            if target not in OBJECT_CLASSES:
                log.warning("Object '%s' not in supported classes", target)
                continue

            # 3. Detect object position
            log.info("Searching for: %s", target)
            position = detector.find_object(target)
            if position is None:
                log.warning("Object '%s' not found in view", target)
                continue

            log.info("Object found at: %s", position)

            # 4. Move arm + grasp
            arm.move_to(position)
            arm.close_gripper()
            time.sleep(0.5)

            # 5. Return to user
            arm.move_to_user_hand()
            arm.open_gripper()
            arm.home()

    except KeyboardInterrupt:
        log.info("Shutting down (Ctrl+C)")
        arm.shutdown()


def parse_target_object(command: str) -> str | None:
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
            for filler in ("my ", "the ", "a ", "me "):
                if tail.startswith(filler):
                    tail = tail[len(filler):].strip()
            for filler in (" my ", " the ", " a ", " me "):
                tail = tail.replace(filler, " ")
            return tail.split()[0] if tail else None
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReachBot main controller")
    parser.add_argument(
        "--simulate", action="store_true",
        help="Run without hardware (logs actions only)"
    )
    args = parser.parse_args()
    main(simulate=args.simulate)
