# ReachBot

> A voice-controlled, wheelchair-mounted robotic arm that helps seniors retrieve dropped objects independently.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/anshjaitly/reachbot/actions/workflows/ci.yml/badge.svg)](https://github.com/anshjaitly/reachbot/actions/workflows/ci.yml)
[![Status](https://img.shields.io/badge/status-ORCA%20Hand%20assembled-green.svg)]()

**Project website:** [reachbot-arm.netlify.app](https://reachbot-arm.netlify.app/)

---

## Why ReachBot?

According to the CDC, more than 14 million adults over 65 fall each year, and reaching for dropped objects is among the leading causes ([CDC Falls Data, 2024](https://www.cdc.gov/falls/data-research/index.html)). Existing assistive robotic arms cost between $10,000 and $50,000, putting them out of reach for most users.

**ReachBot's goal:** a complete voice-controlled assistive arm built for under $300, leveraging open-source hardware designs and consumer electronics.

## Key Features (Planned)

- **Voice control** via OpenAI Whisper API — say "ReachBot, pick up my glasses"
- **Object detection** with OpenCV + YOLOv8 — identifies common dropped items (phones, glasses, pill bottles, remotes)
- **Anthropomorphic gripper** based on ETH Zurich's open-source [ORCA Hand v1](https://srl.ethz.ch/orcahand.html), modified for single-servo actuation
- **4-axis arm** with 760mm reach
- **Wheelchair-mountable** — no installation required
- **Sub-$300 BOM** — accessible to individuals, not just institutions

## Project Status

| Phase | Component | Status |
|-------|-----------|--------|
| Phase 1 | ORCA Hand v1 (ETH Zurich) | 🟢 Printed · tendon assembly in progress |
| Phase 1 | Software stack (7 modules) | 🟢 Fully implemented — simulation + hardware |
| Phase 2 | 4-axis arm | 🟡 Designed, hardware ordered |
| Phase 3 | AI / voice / vision | 🟢 Code complete — pending hardware integration |

## Hardware

**Phase 1 (current):**
- Modified ORCA Hand v1 (3D-printed PLA)
- 1× MG996R servo
- ~5m of 30 lb braided fishing line (tendon)
- Custom-designed servo hub block

**Phase 2 (planned):**
- 760mm aluminum forearm tube
- NEMA 17 stepper for 360° base rotation
- 2× DS3225 servos for shoulder + elbow
- 1× MG996R for wrist roll

**Phase 3 (planned):**
- Raspberry Pi 4 Model B (4GB)
- PCA9685 16-channel PWM driver
- Logitech C270 webcam
- USB lavalier microphone

## Software Architecture

```
[Mic]──>[Whisper STT]──>[Parser]──>[Action Queue]
                                        │
                              ┌─────────┼─────────┐
                              ▼         ▼         ▼
                       [OpenCV/YOLO] [IK Solver] [Servo Driver]
                              │         │         │
                              └─────────┴─────────┘
                                        │
                                  [Robotic Arm]
```

## Repository Structure

```
reachbot/
├── main.py                   # Entry point — orchestrator loop
├── gripper_test.py           # Standalone ORCA Hand test (no full stack needed)
├── setup.sh                  # Raspberry Pi one-shot setup script
├── src/
│   ├── voice_command.py      # Whisper API + VAD + local fallback
│   ├── object_detection.py   # YOLOv8n detector + calibrated coordinate mapping
│   ├── arm_control.py        # Servo IK, smooth motion, wrist auto-level
│   ├── safety.py             # Watchdog, e-stop, reach limits
│   ├── session_logger.py     # JSONL grasp attempt logging
│   ├── calibration.py        # Pixel→mm affine calibration wizard
│   ├── web_interface.py      # FastAPI dashboard + MJPEG stream
│   └── config.py             # Hardware pinouts and constants
├── tests/
│   ├── conftest.py           # Shared fixtures (fast_sleep)
│   ├── test_arm_control.py
│   ├── test_calibration.py
│   ├── test_object_detection.py
│   ├── test_safety.py
│   ├── test_session_logger.py
│   └── test_voice_command.py
├── .github/workflows/ci.yml  # GitHub Actions — tests on every push
├── requirements.txt
├── LICENSE
└── README.md
```

## Quick Start (Development Mode)

```bash
# Clone and install
git clone https://github.com/anshjaitly/reachbot.git
cd reachbot
pip install -r requirements.txt

# Set OpenAI API key for Whisper
export OPENAI_API_KEY="sk-..."

# Run in simulation mode (no hardware required)
python main.py --simulate
```

## Hardware Setup

**On a Raspberry Pi 4:**

```bash
# Enable I2C for PCA9685
sudo raspi-config  # Interface Options > I2C > Enable

# Install hardware libraries
pip install adafruit-circuitpython-pca9685 adafruit-circuitpython-servokit

# Wire the PCA9685 to the Pi (SDA=GPIO 2, SCL=GPIO 3, VCC=3.3V, GND=GND)
# Connect 6V external power to PCA9685 V+ (DO NOT power servos from Pi)

# Run with hardware
python main.py
```

## Acknowledgments

- **ETH Zurich Soft Robotics Lab** — for open-sourcing the ORCA Hand v1 design under CC BY 4.0
- **Original ORCA authors:** Clemens C. Christoph, Maximilian Eberlein, Filippos Katsimalis, Arturo Roberti, Aristotelis Sympetheros, Michel R. Vogt, Davide Liconti, Chenyu Yang, Barnabas Gavin Cangan, Ronan J. Hinchet, and Robert K. Katzschmann
- **OpenAI** — Whisper speech recognition
- **Ultralytics** — YOLOv8 object detection

## License

MIT License — see [LICENSE](LICENSE) for details.

## Contributing

This is currently a solo high school project, but contributions are welcome. Please open an issue first to discuss substantial changes.

## Contact

Project lead: Ansh Jaitly  
Project website: [reachbot-arm.netlify.app](https://reachbot-arm.netlify.app/)
