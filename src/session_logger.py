"""
ReachBot — Session Logger

Records every grasp attempt to a JSON-lines log file.
Useful for:
  - Debugging (what objects are being requested vs. found?)
  - User research (how often does it succeed? what objects are most common?)
  - Regeneron / competition data (empirical success rate)

Each log entry is one JSON object per line (JSONL format), so you can
open the file in a text editor or load it with pandas for analysis.

Log location: ~/reachbot_logs/session_YYYY-MM-DD_HH-MM-SS.jsonl
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

LOG_DIR = Path.home() / "reachbot_logs"


@dataclass
class GraspAttempt:
    """One complete grasp cycle."""

    timestamp: float = field(default_factory=time.time)
    command_text: str = ""
    target_object: str = ""
    object_detected: bool = False
    detection_confidence: float = 0.0
    position_x_mm: float = 0.0
    position_y_mm: float = 0.0
    position_z_mm: float = 0.0
    grasp_success: bool = False
    failure_reason: str = ""        # "not_found", "out_of_reach", "drop", "estop"
    duration_s: float = 0.0

    def iso_time(self) -> str:
        return datetime.fromtimestamp(self.timestamp).isoformat()


class SessionLogger:
    """Append-only JSONL logger for grasp attempts.

    Usage:
        logger = SessionLogger()
        attempt = logger.start_attempt("pick up glasses", "glasses")
        # ... grasp happens ...
        logger.finish_attempt(attempt, success=True)
    """

    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._path = LOG_DIR / f"session_{ts}.jsonl"
        self._count = 0
        log.info("Session log: %s", self._path)

    def start_attempt(self, command: str, target: str) -> GraspAttempt:
        attempt = GraspAttempt(command_text=command, target_object=target)
        log.debug("Attempt started: %s", target)
        return attempt

    def finish_attempt(
        self,
        attempt: GraspAttempt,
        success: bool,
        failure_reason: str = "",
        duration_s: float = 0.0,
    ) -> None:
        attempt.grasp_success = success
        attempt.failure_reason = failure_reason
        attempt.duration_s = duration_s
        self._write(attempt)
        self._count += 1

    def log_detection(
        self,
        attempt: GraspAttempt,
        detected: bool,
        confidence: float = 0.0,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
    ) -> None:
        attempt.object_detected = detected
        attempt.detection_confidence = confidence
        attempt.position_x_mm = x
        attempt.position_y_mm = y
        attempt.position_z_mm = z

    def summary(self) -> dict:
        """Return session stats parsed from the log file."""
        attempts = self._read_all()
        if not attempts:
            return {"total": 0, "success_rate": 0.0, "top_objects": []}

        total = len(attempts)
        successes = sum(1 for a in attempts if a.get("grasp_success"))
        objects: dict[str, int] = {}
        for a in attempts:
            obj = a.get("target_object", "unknown")
            objects[obj] = objects.get(obj, 0) + 1

        top_objects = sorted(objects.items(), key=lambda x: x[1], reverse=True)[:5]
        return {
            "total": total,
            "successes": successes,
            "success_rate": round(successes / total, 3),
            "top_objects": [{"object": k, "count": v} for k, v in top_objects],
            "log_file": str(self._path),
        }

    def print_summary(self) -> None:
        s = self.summary()
        print(f"\n{'='*40}")
        print(f"  ReachBot Session Summary")
        print(f"{'='*40}")
        print(f"  Total attempts : {s['total']}")
        print(f"  Successes      : {s.get('successes', 0)}")
        print(f"  Success rate   : {s['success_rate']:.1%}")
        if s["top_objects"]:
            print("  Top objects    :")
            for item in s["top_objects"]:
                print(f"    {item['object']}: {item['count']}x")
        print(f"  Log saved to   : {s.get('log_file', 'n/a')}")
        print(f"{'='*40}\n")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _write(self, attempt: GraspAttempt) -> None:
        record = asdict(attempt)
        record["iso_time"] = attempt.iso_time()
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as exc:
            log.error("Failed to write session log: %s", exc)

    def _read_all(self) -> list[dict]:
        records = []
        if not self._path.exists():
            return records
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records
