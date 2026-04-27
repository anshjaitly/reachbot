"""
ReachBot configuration — hardware pinouts and runtime constants.
"""

# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------
WAKE_WORD = "reachbot"
WHISPER_MODEL = "whisper-1"  # OpenAI API model
COMMAND_TIMEOUT_S = 5.0      # Max length of one voice command


# ---------------------------------------------------------------------------
# Object detection
# ---------------------------------------------------------------------------
# YOLOv8 / COCO class names that map to common dropped objects in
# senior-living contexts.
OBJECT_CLASSES = {
    "glasses": "glasses",
    "phone": "cell phone",
    "remote": "remote",
    "remote_control": "remote",
    "book": "book",
    "cup": "cup",
    "bottle": "bottle",
    "pill": "bottle",          # Pill bottles fall under COCO 'bottle'
    "pillbottle": "bottle",
    "keys": "key",
    "wallet": "handbag",       # Closest COCO match
    "tv_remote": "remote",
}

CAMERA_INDEX = 0               # /dev/video0 on Raspberry Pi
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

# Camera-to-arm coordinate transform (calibration values)
# Will be measured during physical setup
CAM_TO_ARM_X_OFFSET_MM = 0.0
CAM_TO_ARM_Y_OFFSET_MM = 0.0
CAM_TO_ARM_Z_OFFSET_MM = 80.0  # Camera mounted 80mm above arm base


# ---------------------------------------------------------------------------
# Servo channels (PCA9685 PWM driver)
# ---------------------------------------------------------------------------
SERVO_BASE_ROTATION = 0     # NEMA 17 driver enable (Phase 2)
SERVO_SHOULDER = 1          # DS3225 (Phase 2)
SERVO_ELBOW = 2             # DS3225 (Phase 2)
SERVO_WRIST_ROLL = 3        # MG996R (Phase 2)
SERVO_GRIPPER = 4           # MG996R — Phase 1 active

# Servo angle limits (degrees)
SERVO_LIMITS = {
    SERVO_BASE_ROTATION: (0, 360),
    SERVO_SHOULDER: (0, 180),
    SERVO_ELBOW: (0, 150),
    SERVO_WRIST_ROLL: (0, 180),
    SERVO_GRIPPER: (0, 90),  # 0 = open, 90 = closed (fist)
}

# Home position (all servos)
HOME_POSITION = {
    SERVO_BASE_ROTATION: 180,
    SERVO_SHOULDER: 90,
    SERVO_ELBOW: 90,
    SERVO_WRIST_ROLL: 90,
    SERVO_GRIPPER: 0,   # Open
}


# ---------------------------------------------------------------------------
# Arm geometry (mm)
# ---------------------------------------------------------------------------
LINK_BASE_TO_SHOULDER_MM = 80
LINK_SHOULDER_TO_ELBOW_MM = 380
LINK_ELBOW_TO_WRIST_MM = 380
LINK_WRIST_TO_GRIPPER_MM = 100
MAX_REACH_MM = (
    LINK_SHOULDER_TO_ELBOW_MM
    + LINK_ELBOW_TO_WRIST_MM
    + LINK_WRIST_TO_GRIPPER_MM
)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------
GRIPPER_CLOSE_TIME_S = 1.0      # Time to fully close
GRIPPER_TORQUE_LIMIT_KGCM = 9.0  # MG996R rated 11 kg-cm; limit below max
EMERGENCY_STOP_GPIO = 17         # Physical e-stop button on Pi
