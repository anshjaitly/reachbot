"""
Tests for SessionLogger — data integrity, summary stats, JSONL format.
Run with: python -m pytest tests/ -v
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestSessionLogger:
    def _make_logger(self, tmp_path):
        """Create a SessionLogger that writes to a temp directory."""
        from session_logger import SessionLogger, LOG_DIR
        import session_logger as sl_module

        # Redirect log dir to temp
        original = sl_module.LOG_DIR
        sl_module.LOG_DIR = tmp_path
        logger = SessionLogger()
        sl_module.LOG_DIR = original
        return logger

    def test_successful_grasp_written_to_jsonl(self, tmp_path):
        from session_logger import SessionLogger
        import session_logger as sl

        old_dir = sl.LOG_DIR
        sl.LOG_DIR = tmp_path
        try:
            logger = SessionLogger()
            attempt = logger.start_attempt("pick up glasses", "glasses")
            logger.log_detection(attempt, detected=True, confidence=0.95,
                                  x=200, y=0, z=-80)
            logger.finish_attempt(attempt, success=True, duration_s=2.5)

            # Verify JSONL file
            logs = list(tmp_path.glob("session_*.jsonl"))
            assert len(logs) == 1
            with open(logs[0]) as f:
                record = json.loads(f.readline())
            assert record["target_object"] == "glasses"
            assert record["grasp_success"] is True
            assert record["detection_confidence"] == 0.95
            assert record["duration_s"] == 2.5
        finally:
            sl.LOG_DIR = old_dir

    def test_failed_grasp_records_reason(self, tmp_path):
        from session_logger import SessionLogger
        import session_logger as sl

        old_dir = sl.LOG_DIR
        sl.LOG_DIR = tmp_path
        try:
            logger = SessionLogger()
            attempt = logger.start_attempt("grab remote", "remote")
            logger.finish_attempt(attempt, success=False, failure_reason="not_found")

            logs = list(tmp_path.glob("session_*.jsonl"))
            with open(logs[0]) as f:
                record = json.loads(f.readline())
            assert record["grasp_success"] is False
            assert record["failure_reason"] == "not_found"
        finally:
            sl.LOG_DIR = old_dir

    def test_summary_success_rate(self, tmp_path):
        from session_logger import SessionLogger
        import session_logger as sl

        old_dir = sl.LOG_DIR
        sl.LOG_DIR = tmp_path
        try:
            logger = SessionLogger()
            for i in range(3):
                a = logger.start_attempt("grab cup", "cup")
                logger.finish_attempt(a, success=True)
            for i in range(1):
                a = logger.start_attempt("grab phone", "phone")
                logger.finish_attempt(a, success=False, failure_reason="not_found")

            summary = logger.summary()
            assert summary["total"] == 4
            assert summary["successes"] == 3
            assert abs(summary["success_rate"] - 0.75) < 0.001
        finally:
            sl.LOG_DIR = old_dir

    def test_summary_empty_session(self, tmp_path):
        from session_logger import SessionLogger
        import session_logger as sl

        old_dir = sl.LOG_DIR
        sl.LOG_DIR = tmp_path
        try:
            logger = SessionLogger()
            summary = logger.summary()
            assert summary["total"] == 0
            assert summary["success_rate"] == 0.0
        finally:
            sl.LOG_DIR = old_dir

    def test_multiple_attempts_all_written(self, tmp_path):
        from session_logger import SessionLogger
        import session_logger as sl

        old_dir = sl.LOG_DIR
        sl.LOG_DIR = tmp_path
        try:
            logger = SessionLogger()
            for obj in ["glasses", "keys", "remote", "cup", "phone"]:
                a = logger.start_attempt(f"grab {obj}", obj)
                logger.finish_attempt(a, success=True)

            logs = list(tmp_path.glob("session_*.jsonl"))
            with open(logs[0]) as f:
                lines = [l for l in f if l.strip()]
            assert len(lines) == 5
        finally:
            sl.LOG_DIR = old_dir
