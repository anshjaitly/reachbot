"""
Pytest configuration — shared fixtures and global patches.

Patches time.sleep to a no-op for all tests so smooth-motion loops
(which sleep ~12ms per step) don't make the suite take minutes.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src/ is on the path for all test files
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(autouse=True)
def fast_sleep():
    """Replace time.sleep with a no-op for the duration of every test."""
    with patch("time.sleep"):
        yield
