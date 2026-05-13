"""
Tests for calibration — CalibrationResult, solve_calibration, save/load.
OpenCV-dependent paths are skipped when cv2 is unavailable.
Run with: python -m pytest tests/ -v
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from calibration import CalibrationResult, save_calibration, load_calibration, MIN_POINTS


# ---------------------------------------------------------------------------
# CalibrationResult
# ---------------------------------------------------------------------------

class TestCalibrationResult:
    def _make(self, sx=1.5, sy=-1.5, ox=10.0, oy=20.0, z=80.0, err=2.5):
        return CalibrationResult(sx=sx, sy=sy, ox=ox, oy=oy,
                                  z_offset=z, error_mm=err)

    def test_pixel_to_arm_x(self):
        cal = self._make(sx=2.0, ox=50.0)
        ax, ay, az = cal.pixel_to_arm(100.0, 0.0)
        assert ax == pytest.approx(250.0)  # 2.0*100 + 50

    def test_pixel_to_arm_y(self):
        cal = self._make(sy=3.0, oy=-10.0)
        ax, ay, az = cal.pixel_to_arm(0.0, 50.0)
        assert ay == pytest.approx(140.0)  # 3.0*50 + (-10)

    def test_pixel_to_arm_z_is_negative_offset(self):
        cal = self._make(z=80.0)
        ax, ay, az = cal.pixel_to_arm(0.0, 0.0)
        assert az == pytest.approx(-80.0)

    def test_to_dict_roundtrip(self):
        cal = self._make()
        d = cal.to_dict()
        cal2 = CalibrationResult.from_dict(d)
        assert cal2.sx == cal.sx
        assert cal2.sy == cal.sy
        assert cal2.ox == cal.ox
        assert cal2.oy == cal.oy
        assert cal2.z_offset == cal.z_offset
        assert cal2.error_mm == cal.error_mm

    def test_str_contains_scale_and_offset(self):
        cal = self._make(sx=1.5, oy=20.0)
        s = str(cal)
        assert "1.5" in s
        assert "20" in s

    def test_from_dict_missing_rms_defaults_to_zero(self):
        d = {"sx": 1.0, "sy": 1.0, "ox": 0.0, "oy": 0.0, "z_offset_mm": 80.0}
        cal = CalibrationResult.from_dict(d)
        assert cal.error_mm == 0.0


# ---------------------------------------------------------------------------
# solve_calibration (requires numpy + cv2 — skipped otherwise)
# ---------------------------------------------------------------------------

cv2_available = False
try:
    import cv2, numpy
    cv2_available = True
except ImportError:
    pass


@pytest.mark.skipif(not cv2_available, reason="OpenCV / numpy not installed")
class TestSolveCalibration:
    from calibration import solve_calibration

    def test_perfect_scale_no_offset(self):
        from calibration import solve_calibration
        # arm_x = 2 * px, arm_y = 3 * py
        pixels = [(0, 0), (100, 0), (200, 0), (0, 100), (0, 200)]
        arms = [(0, 0), (200, 0), (400, 0), (0, 300), (0, 600)]
        result = solve_calibration(pixels, arms, z_offset_mm=80.0)
        assert result.sx == pytest.approx(2.0, abs=0.01)
        assert result.sy == pytest.approx(3.0, abs=0.01)
        assert result.error_mm == pytest.approx(0.0, abs=0.5)

    def test_with_offset(self):
        from calibration import solve_calibration
        # arm_x = 1.5*px + 50, arm_y = -1.5*py + 100
        pixels = [(10, 20), (50, 80), (100, 150), (200, 50), (150, 100)]
        arms = [(1.5*p + 50, -1.5*q + 100) for p, q in pixels]
        result = solve_calibration(pixels, arms, z_offset_mm=100.0)
        assert result.sx == pytest.approx(1.5, abs=0.01)
        assert result.ox == pytest.approx(50.0, abs=0.5)
        assert result.z_offset == pytest.approx(100.0)

    def test_insufficient_points_raises(self):
        from calibration import solve_calibration
        with pytest.raises(ValueError, match="at least"):
            solve_calibration([(0, 0)], [(0, 0)], z_offset_mm=80.0)

    def test_minimum_points_accepted(self):
        from calibration import solve_calibration
        pixels = [(i * 50, 0) for i in range(MIN_POINTS)]
        arms = [(i * 100.0, 0.0) for i in range(MIN_POINTS)]
        result = solve_calibration(pixels, arms, z_offset_mm=80.0)
        assert result is not None

    def test_rms_error_is_nonnegative(self):
        from calibration import solve_calibration
        pixels = [(0, 0), (100, 0), (200, 0), (0, 100), (0, 200)]
        arms = [(0, 0), (200, 1), (400, -1), (1, 300), (-1, 600)]
        result = solve_calibration(pixels, arms, z_offset_mm=80.0)
        assert result.error_mm >= 0.0


# ---------------------------------------------------------------------------
# save / load (mocked filesystem)
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_roundtrip_via_json(self, tmp_path):
        import calibration as cal_module
        original_path = cal_module.CALIBRATION_FILE
        cal_module.CALIBRATION_FILE = tmp_path / "calibration.json"

        try:
            cal = CalibrationResult(sx=1.23, sy=-0.98, ox=15.0, oy=-5.0,
                                     z_offset=80.0, error_mm=3.1)
            save_calibration(cal)
            loaded = load_calibration()
            assert loaded is not None
            assert loaded.sx == pytest.approx(1.23)
            assert loaded.sy == pytest.approx(-0.98)
            assert loaded.error_mm == pytest.approx(3.1)
        finally:
            cal_module.CALIBRATION_FILE = original_path

    def test_load_returns_none_when_missing(self, tmp_path):
        import calibration as cal_module
        original_path = cal_module.CALIBRATION_FILE
        cal_module.CALIBRATION_FILE = tmp_path / "does_not_exist.json"
        try:
            assert load_calibration() is None
        finally:
            cal_module.CALIBRATION_FILE = original_path

    def test_saved_file_is_valid_json(self, tmp_path):
        import calibration as cal_module
        original_path = cal_module.CALIBRATION_FILE
        cal_module.CALIBRATION_FILE = tmp_path / "calibration.json"
        try:
            cal = CalibrationResult(sx=1.0, sy=1.0, ox=0.0, oy=0.0,
                                     z_offset=80.0, error_mm=0.0)
            save_calibration(cal)
            with open(tmp_path / "calibration.json") as f:
                data = json.load(f)
            assert "sx" in data and "sy" in data
        finally:
            cal_module.CALIBRATION_FILE = original_path
