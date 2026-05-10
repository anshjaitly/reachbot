"""
ReachBot — Object Detection

Detects objects using YOLOv8. For position accuracy, loads the saved
camera-to-arm calibration (calibration.json) when available; falls back
to a linear approximation if not yet calibrated.

Detection is averaged over FRAME_AVERAGE frames to reduce noise from
a single bad frame.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, List

from config import (
    CAMERA_INDEX, CAMERA_WIDTH, CAMERA_HEIGHT,
    CAM_TO_ARM_X_OFFSET_MM,
    CAM_TO_ARM_Y_OFFSET_MM,
    CAM_TO_ARM_Z_OFFSET_MM,
    OBJECT_CLASSES,
)

log = logging.getLogger(__name__)

FRAME_AVERAGE = 3           # Frames to average for stable position
DETECTION_TIMEOUT_S = 3.0   # Max time to wait for a confident detection

try:
    import cv2
    from ultralytics import YOLO
    CV_AVAILABLE = True
except ImportError:
    CV_AVAILABLE = False
    log.warning("OpenCV / Ultralytics not installed — running in stub mode")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


@dataclass
class ObjectPosition:
    """3D position of a detected object in arm-frame coordinates (mm)."""

    x: float
    y: float
    z: float
    confidence: float
    class_name: str
    width_px: float = 0.0   # Bounding box width in pixels (used for grasp width)
    height_px: float = 0.0

    @property
    def estimated_width_mm(self) -> float:
        """Rough object width in mm from bounding box size.

        Uses the calibration x-scale if available; else falls back to the
        uncalibrated workspace approximation.
        """
        if self.width_px <= 0:
            return 50.0  # Default guess
        try:
            from calibration import load_calibration
            cal = load_calibration()
            if cal:
                return abs(cal.sx) * self.width_px
        except Exception:
            pass
        # Fallback: approximate scale from default workspace width
        return (self.width_px / CAMERA_WIDTH) * 600.0

    def __str__(self) -> str:
        return (
            f"<{self.class_name} ({self.confidence:.2f}) at "
            f"({self.x:.0f}, {self.y:.0f}, {self.z:.0f})mm "
            f"~{self.estimated_width_mm:.0f}mm wide>"
        )


class ObjectDetector:
    """YOLOv8-based object detector with calibrated coordinate mapping."""

    def __init__(self, model: str = "yolov8n.pt", confidence: float = 0.5):
        self.confidence = confidence
        self.model = None
        self.cap = None
        self._calibration = None

        # Load saved calibration if it exists
        self._load_calibration()

        if not CV_AVAILABLE:
            return

        log.info("Loading YOLO model: %s", model)
        self.model = YOLO(model)
        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimise latency

        if not self.cap.isOpened():
            log.error("Failed to open camera index %d", CAMERA_INDEX)
            self.cap = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_object(self, target_alias: str) -> Optional[ObjectPosition]:
        """Find the best detection of `target_alias` averaged over several frames.

        Returns the ObjectPosition with the highest mean confidence, or None
        if no detection reaches self.confidence within DETECTION_TIMEOUT_S.
        """
        target_class = OBJECT_CLASSES.get(target_alias.lower())
        if target_class is None:
            log.warning("Unknown object alias: %r", target_alias)
            return None

        if not CV_AVAILABLE or self.cap is None:
            return self._stub_find(target_alias, target_class)

        candidates: List[ObjectPosition] = []
        deadline = time.time() + DETECTION_TIMEOUT_S

        while len(candidates) < FRAME_AVERAGE and time.time() < deadline:
            pos = self._detect_once(target_class)
            if pos is not None:
                candidates.append(pos)

        if not candidates:
            log.warning("No detection of %r within %.1fs", target_class, DETECTION_TIMEOUT_S)
            return None

        return self._average_positions(candidates)

    def close(self) -> None:
        """Release the camera."""
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    # ------------------------------------------------------------------
    # Internal detection
    # ------------------------------------------------------------------

    def _detect_once(self, target_class: str) -> Optional[ObjectPosition]:
        """Run YOLO on a single fresh frame, return best matching box."""
        # Flush stale frames from the buffer
        for _ in range(2):
            self.cap.grab()

        ret, frame = self.cap.read()
        if not ret:
            log.warning("Camera read failed")
            return None

        results = self.model(frame, conf=self.confidence, verbose=False)
        best: Optional[ObjectPosition] = None
        best_conf = 0.0

        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls.item())
                cls_name = self.model.names[cls_id]
                if cls_name != target_class:
                    continue

                conf = float(box.conf.item())
                if conf <= best_conf:
                    continue

                x1, y1, x2, y2 = box.xyxy[0].tolist()
                px = (x1 + x2) / 2
                py = (y1 + y2) / 2
                w_px = x2 - x1
                h_px = y2 - y1

                arm_x, arm_y, arm_z = self._pixel_to_arm_mm(px, py)
                best_conf = conf
                best = ObjectPosition(
                    x=arm_x, y=arm_y, z=arm_z,
                    confidence=conf, class_name=cls_name,
                    width_px=w_px, height_px=h_px,
                )

        return best

    def _average_positions(self, positions: List[ObjectPosition]) -> ObjectPosition:
        """Return the element-wise mean of a list of ObjectPositions."""
        if len(positions) == 1:
            return positions[0]

        if NUMPY_AVAILABLE:
            import numpy as np
            xs = np.array([p.x for p in positions])
            ys = np.array([p.y for p in positions])
            zs = np.array([p.z for p in positions])
            confs = np.array([p.confidence for p in positions])
            widths = np.array([p.width_px for p in positions])

            # Weighted mean by confidence
            w = confs / confs.sum()
            return ObjectPosition(
                x=float(np.dot(w, xs)),
                y=float(np.dot(w, ys)),
                z=float(np.dot(w, zs)),
                confidence=float(confs.mean()),
                class_name=positions[0].class_name,
                width_px=float(np.dot(w, widths)),
            )

        # Fallback: simple mean
        n = len(positions)
        return ObjectPosition(
            x=sum(p.x for p in positions) / n,
            y=sum(p.y for p in positions) / n,
            z=sum(p.z for p in positions) / n,
            confidence=sum(p.confidence for p in positions) / n,
            class_name=positions[0].class_name,
            width_px=sum(p.width_px for p in positions) / n,
        )

    # ------------------------------------------------------------------
    # Coordinate transform
    # ------------------------------------------------------------------

    def _pixel_to_arm_mm(self, px: float, py: float) -> Tuple[float, float, float]:
        """Convert pixel centroid to arm-frame mm using calibration if available."""
        if self._calibration is not None:
            return self._calibration.pixel_to_arm(px, py)

        # Uncalibrated fallback — linear approximation
        workspace_w_mm = 600.0
        workspace_h_mm = 450.0
        norm_x = (px / CAMERA_WIDTH) - 0.5
        norm_y = (py / CAMERA_HEIGHT) - 0.5
        arm_x = norm_x * workspace_w_mm + CAM_TO_ARM_X_OFFSET_MM
        arm_y = norm_y * workspace_h_mm + CAM_TO_ARM_Y_OFFSET_MM
        arm_z = -CAM_TO_ARM_Z_OFFSET_MM
        return arm_x, arm_y, arm_z

    def _load_calibration(self) -> None:
        """Load calibration.json from the project root if it exists."""
        try:
            from calibration import load_calibration
            cal = load_calibration()
            if cal:
                self._calibration = cal
                log.info("Loaded camera calibration (rms=%.2fmm)", cal.error_mm)
            else:
                log.warning(
                    "No calibration file found — using uncalibrated approximation. "
                    "Run: python src/calibration.py"
                )
        except Exception as exc:
            log.warning("Could not load calibration: %s", exc)

    # ------------------------------------------------------------------
    # Stub
    # ------------------------------------------------------------------

    def _stub_find(self, alias: str, cls: str) -> ObjectPosition:
        log.info("[stub] Pretending to detect %s at (200, 0, -80)mm", cls)
        return ObjectPosition(
            x=200.0, y=0.0, z=-80.0,
            confidence=0.99, class_name=cls,
            width_px=80.0,
        )

    def __del__(self):
        self.close()
