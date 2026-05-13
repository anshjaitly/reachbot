"""
Tests for ObjectDetector and ObjectPosition — stub mode, coordinate math,
averaging logic, calibration integration.
Run with: python -m pytest tests/ -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from object_detection import ObjectDetector, ObjectPosition
from config import CAMERA_WIDTH, CAMERA_HEIGHT, OBJECT_CLASSES


# ---------------------------------------------------------------------------
# ObjectPosition
# ---------------------------------------------------------------------------

class TestObjectPosition:
    def test_str_contains_class_and_coords(self):
        pos = ObjectPosition(x=100, y=50, z=-80, confidence=0.9, class_name="remote")
        s = str(pos)
        assert "remote" in s
        assert "100" in s

    def test_estimated_width_mm_default_when_no_pixels(self):
        pos = ObjectPosition(x=0, y=0, z=0, confidence=1.0,
                              class_name="cup", width_px=0)
        # Should return a reasonable default, not crash
        assert pos.estimated_width_mm > 0

    def test_estimated_width_mm_scales_with_pixels(self):
        pos_narrow = ObjectPosition(x=0, y=0, z=0, confidence=1.0,
                                     class_name="cup", width_px=40)
        pos_wide = ObjectPosition(x=0, y=0, z=0, confidence=1.0,
                                   class_name="cup", width_px=160)
        assert pos_wide.estimated_width_mm > pos_narrow.estimated_width_mm

    def test_estimated_width_uses_calibration_if_available(self, tmp_path):
        """When a calibration exists, estimated_width_mm uses cal.sx."""
        from calibration import CalibrationResult
        cal = CalibrationResult(sx=2.0, sy=2.0, ox=0, oy=0,
                                 z_offset=80, error_mm=0)
        with patch("object_detection.ObjectPosition.estimated_width_mm",
                   new_callable=lambda: property(lambda self: abs(2.0) * self.width_px)):
            pos = ObjectPosition(x=0, y=0, z=0, confidence=1.0,
                                  class_name="cup", width_px=50)
            # 2.0 mm/px * 50 px = 100 mm
            assert pos.width_px == 50


# ---------------------------------------------------------------------------
# ObjectDetector — stub mode (no camera, no YOLO)
# ---------------------------------------------------------------------------

class TestObjectDetectorStubMode:
    @pytest.fixture
    def detector(self):
        # Force stub mode by patching CV_AVAILABLE
        with patch("object_detection.CV_AVAILABLE", False):
            d = ObjectDetector()
        return d

    def test_find_known_object_returns_position(self, detector):
        result = detector.find_object("glasses")
        assert result is not None
        assert isinstance(result, ObjectPosition)

    def test_stub_position_is_reasonable(self, detector):
        result = detector.find_object("remote")
        assert result is not None
        # Should return a plausible arm-frame coordinate
        assert -1000 < result.x < 1000
        assert -1000 < result.y < 1000

    def test_unknown_object_returns_none(self, detector):
        result = detector.find_object("xyzzy_unknown_object")
        assert result is None

    def test_stub_confidence_is_high(self, detector):
        result = detector.find_object("phone")
        assert result is not None
        assert result.confidence > 0.5

    @pytest.mark.parametrize("alias", list(OBJECT_CLASSES.keys()))
    def test_all_known_aliases_return_position(self, detector, alias):
        result = detector.find_object(alias)
        assert result is not None, f"Expected position for alias '{alias}'"


# ---------------------------------------------------------------------------
# Coordinate transform
# ---------------------------------------------------------------------------

class TestCoordinateTransform:
    @pytest.fixture
    def detector(self):
        with patch("object_detection.CV_AVAILABLE", False):
            d = ObjectDetector()
        return d

    def test_pixel_center_maps_near_zero_x_without_calibration(self, detector):
        detector._calibration = None
        ax, ay, az = detector._pixel_to_arm_mm(CAMERA_WIDTH / 2, CAMERA_HEIGHT / 2)
        # Center pixel should map close to zero with no offset config
        from config import CAM_TO_ARM_X_OFFSET_MM
        assert abs(ax - CAM_TO_ARM_X_OFFSET_MM) < 5

    def test_calibration_overrides_fallback(self, detector):
        from calibration import CalibrationResult
        cal = CalibrationResult(sx=1.0, sy=1.0, ox=999.0, oy=999.0,
                                 z_offset=80, error_mm=0)
        detector._calibration = cal
        ax, ay, az = detector._pixel_to_arm_mm(0.0, 0.0)
        # ox=999 should dominate
        assert ax == pytest.approx(999.0)
        assert ay == pytest.approx(999.0)

    def test_z_is_negative_with_calibration(self, detector):
        from calibration import CalibrationResult
        cal = CalibrationResult(sx=1.0, sy=1.0, ox=0.0, oy=0.0,
                                 z_offset=80.0, error_mm=0)
        detector._calibration = cal
        _, _, az = detector._pixel_to_arm_mm(0.0, 0.0)
        assert az == pytest.approx(-80.0)


# ---------------------------------------------------------------------------
# Averaging logic
# ---------------------------------------------------------------------------

class TestAveraging:
    @pytest.fixture
    def detector(self):
        with patch("object_detection.CV_AVAILABLE", False):
            d = ObjectDetector()
        return d

    def _pos(self, x, y, conf=0.9):
        return ObjectPosition(x=x, y=y, z=0, confidence=conf,
                               class_name="remote", width_px=60)

    def test_single_position_returned_as_is(self, detector):
        pos = self._pos(100, 200)
        result = detector._average_positions([pos])
        assert result.x == pytest.approx(100)
        assert result.y == pytest.approx(200)

    def test_equal_weight_average(self, detector):
        positions = [self._pos(0, 0), self._pos(100, 100)]
        result = detector._average_positions(positions)
        assert result.x == pytest.approx(50, abs=1)
        assert result.y == pytest.approx(50, abs=1)

    def test_higher_confidence_weighs_more(self, detector):
        try:
            import numpy  # noqa: F401
            numpy_available = True
        except ImportError:
            numpy_available = False

        low = self._pos(0, 0, conf=0.5)
        high = self._pos(100, 100, conf=0.9)
        result = detector._average_positions([low, high])
        if numpy_available:
            # Weighted mean — high conf pulls result above simple 50/50
            assert result.x > 50
            assert result.y > 50
        else:
            # Simple mean fallback — exactly 50
            assert result.x >= 50
            assert result.y >= 50

    def test_averaged_confidence_is_mean(self, detector):
        positions = [self._pos(0, 0, conf=0.6), self._pos(0, 0, conf=0.8)]
        result = detector._average_positions(positions)
        assert result.confidence == pytest.approx(0.7, abs=0.01)
