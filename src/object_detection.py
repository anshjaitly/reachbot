"""
ReachBot — Object Detection

Detects objects in the camera view using YOLOv8, returns the 3D
position of the closest match for the requested target class.
"""

import logging
from dataclasses import dataclass

from config import (
    CAMERA_INDEX, CAMERA_WIDTH, CAMERA_HEIGHT,
    CAM_TO_ARM_X_OFFSET_MM,
    CAM_TO_ARM_Y_OFFSET_MM,
    CAM_TO_ARM_Z_OFFSET_MM,
    OBJECT_CLASSES,
)

log = logging.getLogger(__name__)

try:
    import cv2
    from ultralytics import YOLO
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False
    log.warning(
        "OpenCV / Ultralytics not installed — running in stub mode"
    )


@dataclass
class ObjectPosition:
    """3D position of a detected object in arm-frame coordinates (mm)."""

    x: float
    y: float
    z: float
    confidence: float
    class_name: str

    def __str__(self) -> str:
        return (
            f"<{self.class_name} ({self.confidence:.2f}) at "
            f"({self.x:.0f}, {self.y:.0f}, {self.z:.0f})mm>"
        )


class ObjectDetector:
    """YOLOv8-based object detector with camera-to-arm coordinate mapping."""

    def __init__(self, model: str = "yolov8n.pt", confidence: float = 0.5):
        self.confidence = confidence
        self.model = None
        self.cap = None

        if HARDWARE_AVAILABLE:
            log.info("Loading YOLO model: %s", model)
            self.model = YOLO(model)
            self.cap = cv2.VideoCapture(CAMERA_INDEX)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)

    def find_object(self, target_alias: str) -> ObjectPosition | None:
        """Find the highest-confidence instance of `target_alias` in view."""
        target_class = OBJECT_CLASSES.get(target_alias.lower())
        if target_class is None:
            log.warning("Unknown target alias: %s", target_alias)
            return None

        if not HARDWARE_AVAILABLE or self.cap is None:
            return self._stub_find(target_alias, target_class)

        ret, frame = self.cap.read()
        if not ret:
            log.error("Camera frame grab failed")
            return None

        results = self.model(frame, conf=self.confidence, verbose=False)
        best = None
        best_conf = 0.0

        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls.item())
                cls_name = self.model.names[cls_id]
                conf = float(box.conf.item())
                if cls_name != target_class:
                    continue
                if conf <= best_conf:
                    continue

                # Centroid of bounding box in pixel space
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                px = (x1 + x2) / 2
                py = (y1 + y2) / 2

                # Convert pixel -> arm-frame mm
                arm_x, arm_y, arm_z = self._pixel_to_arm_mm(px, py)
                best_conf = conf
                best = ObjectPosition(
                    x=arm_x, y=arm_y, z=arm_z,
                    confidence=conf, class_name=cls_name,
                )

        return best

    def _pixel_to_arm_mm(self, px: float, py: float) -> tuple[float, float, float]:
        """Convert pixel coordinates to arm-frame (mm).

        Assumes a downward-facing camera over a flat reachable workspace.
        Real implementation requires per-camera calibration; this is a
        first-order approximation for development.
        """
        # Workspace is 600mm x 450mm centered under the camera
        workspace_w_mm = 600.0
        workspace_h_mm = 450.0

        norm_x = (px / CAMERA_WIDTH) - 0.5     # -0.5 .. 0.5
        norm_y = (py / CAMERA_HEIGHT) - 0.5

        arm_x = norm_x * workspace_w_mm + CAM_TO_ARM_X_OFFSET_MM
        arm_y = norm_y * workspace_h_mm + CAM_TO_ARM_Y_OFFSET_MM
        arm_z = -CAM_TO_ARM_Z_OFFSET_MM        # Object on floor

        return arm_x, arm_y, arm_z

    def _stub_find(self, alias: str, cls: str) -> ObjectPosition:
        """Stub mode: return a fixed position for development."""
        log.info("[stub] Pretending to find %s at (200, 0, -80)mm", cls)
        return ObjectPosition(
            x=200.0, y=0.0, z=-80.0,
            confidence=0.99, class_name=cls,
        )

    def __del__(self):
        if self.cap is not None:
            self.cap.release()
