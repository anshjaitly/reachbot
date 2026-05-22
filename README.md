# ReachBot

> A voice-controlled, wheelchair-mounted robotic arm that helps seniors with limited mobility retrieve dropped objects — hands-free, no caregiver required.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/anshjaitly/reachbot/actions/workflows/ci.yml/badge.svg)](https://github.com/anshjaitly/reachbot/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-128%20passing-brightgreen.svg)]()
[![Status](https://img.shields.io/badge/status-ORCA%20Hand%20assembled-green.svg)]()

**Live site:** [reachbot-arm.netlify.app](https://reachbot-arm.netlify.app/)  
**Research submission:** Regeneron STS 2025

---

## The Problem

According to the CDC, over 14 million adults 65+ fall each year — and one of the leading triggers is reaching for objects they've dropped. For wheelchair users or seniors with limited arm mobility, a phone that slides off a lap or glasses that fall to the floor can mean waiting 20+ minutes for a caregiver to return.

Commercial assistive robotic arms (Kinova JACO, Exact Dynamics iARM) solve this — but cost $10,000–$50,000, require institutional procurement, and take months to receive. Most seniors never get one.

**ReachBot's goal:** replicate 80% of that functionality for under $300, using open-source hardware and a Raspberry Pi.

---

## Demo

**[→ reachbot-arm.netlify.app](https://reachbot-arm.netlify.app/)** — design log, gripper iteration photos, and architecture overview.

---

## What It Does

Say **"ReachBot, pick up my glasses"** — and the arm:

1. Wakes on the wake word using VAD (no constant cloud streaming)
2. Transcribes the command via OpenAI Whisper
3. Parses the target object from natural speech ("pick up / grab / get / fetch my…")
4. Runs YOLOv8n to locate the object in the camera frame
5. Maps pixel coordinates → real-world mm using a calibrated affine transform
6. Solves inverse kinematics and smoothly moves the arm to grasp position
7. Closes the ORCA Hand gripper with adaptive grip force based on object width
8. Returns the object to the user's hand, re-homes, and speaks "Here you go."

At every stage the system gives spoken feedback so users don't need to watch a screen — critical for the target population.

---

## Hardware

### Phase 1 — Gripper (current)

| Part | Detail |
|------|--------|
| Hand | Modified [ORCA Hand v1](https://srl.ethz.ch/orcahand.html) (ETH Zurich, CC BY 4.0) — 17-DOF tendon-driven anthropomorphic hand |
| Servo | 1× MG996R (modified for single-servo actuation across all fingers) |
| Tendons | ~5m Power Pro 30 lb braided spectra line |
| Bearings | 4×8×3mm MR84ZZ ball bearings at tendon routing points |
| Pins | 2mm steel dowel pins |
| Frame | Custom servo hub block (Onshape, PLA) |

### Phase 2 — Arm (ordered)

| Part | Detail |
|------|--------|
| Base rotation | NEMA 17 stepper + DRV8825 driver |
| Shoulder / elbow | 2× DS3225 25kg digital servo |
| Wrist roll | 1× MG996R |
| Forearm | 760mm aluminum square tube |
| Bearing | 4" lazy susan for base |
| Reach | ~760mm horizontal |

### Phase 3 — Compute & Sensors

| Part | Detail |
|------|--------|
| SBC | Raspberry Pi 4 Model B (4GB) |
| PWM driver | Adafruit PCA9685 16-channel |
| Camera | Logitech C270 (720p, fixed-focus) |
| Mic | USB lavalier |
| Mount | Wheelchair armrest clamp (3D-printed) |

**Total BOM target: < $300**

---

## Gripper Design — 4 Iterations

Getting the gripper right took four full redesigns over ~8 weeks. The short version:

| # | Design | Problem | Decision |
|---|--------|---------|----------|
| 1 | Dual paddle (servo-actuated) | No conformability — hard objects slipped on contact | Rejected |
| 2 | Octopus tentacles (3+3 opposing curling fingers) | Curl radius too large, missed small objects | Rejected |
| 3 | 6-finger tendon array (custom) | Too many independent DOF to control with 1 servo reliably | Rejected |
| 4 | **ORCA Hand v1** (ETH Zurich, modified) | — | **Current** |

The ORCA Hand gave anthropomorphic conformability out of the box. The key modification was routing all five finger tendons to a single servo hub so one MG996R drives a full fist-close motion, with adaptive angle:

```
angle_deg = 90 × (1 − (width_mm − 32) / 168)
```

where `width_mm` is the estimated object width from the YOLO bounding box.

---

## Software Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         main.py                             │
│              (orchestrator + safety watchdog)               │
└───────────┬─────────────────────────────────────────────────┘
            │
   ┌────────▼────────┐     ┌──────────────┐
   │ voice_command   │────▶│  Whisper API │  (OpenAI STT)
   │ (VAD + parser)  │     └──────────────┘
   └────────┬────────┘
            │ "remote", "glasses", …
   ┌────────▼────────┐     ┌──────────────┐
   │ object_detection│────▶│  YOLOv8n     │  (Ultralytics)
   │ (pixel→mm cal.) │     └──────────────┘
   └────────┬────────┘
            │ ObjectPosition(x, y, z, confidence)
   ┌────────▼────────┐
   │  safety.py      │  (reach limits, watchdog, e-stop GPIO)
   └────────┬────────┘
            │
   ┌────────▼────────┐     ┌──────────────┐
   │  arm_control    │────▶│  PCA9685     │  (I2C servo driver)
   │  (IK + motion)  │     └──────────────┘
   └────────┬────────┘
            │
   ┌────────▼────────┐     ┌──────────────┐
   │  tts.py         │────▶│  pyttsx3     │  (offline, Pi-native)
   │  (voice feedback│     └──────────────┘
   └────────┬────────┘
            │
   ┌────────▼────────┐
   │ session_logger  │  (JSONL grasp logs → tools/log_analyzer.py)
   └─────────────────┘
```

### Key design decisions

- **Offline TTS** (pyttsx3) rather than cloud — works without internet, no latency spike mid-grasp
- **VAD pre-filter** before Whisper — avoids billing for ambient noise; wakes only on speech
- **Simulation mode** (`--simulate`) — full pipeline runs on any laptop without hardware; used for all CI tests
- **Stub fallbacks everywhere** — every hardware module (camera, servos, GPIO, audio) degrades gracefully so the software stack is always testable
- **JSONL session logging** — every grasp attempt is logged with target, confidence, position, success/fail, duration, and failure reason; feeds directly into `tools/log_analyzer.py` for Regeneron STS research data

---

## Repository Structure

```
reachbot/
├── main.py                    # Entry point — orchestrator loop
├── gripper_test.py            # Standalone ORCA Hand tester (sweep, interactive)
├── setup.sh                   # Raspberry Pi one-shot setup (venv, deps, YOLOv8n)
├── requirements.txt
├── src/
│   ├── config.py              # Hardware pinouts, reach limits, object classes
│   ├── voice_command.py       # Whisper + VAD, wake-word detection
│   ├── object_detection.py    # YOLOv8n, calibrated pixel→mm transform
│   ├── arm_control.py         # Servo IK, smooth motion, wrist auto-level
│   ├── safety.py              # Watchdog thread, e-stop GPIO, reach envelope
│   ├── session_logger.py      # JSONL attempt logging for research data
│   ├── calibration.py         # Affine calibration wizard (checkerboard)
│   ├── tts.py                 # pyttsx3 TTS + print-stub fallback
│   └── web_interface.py       # FastAPI dashboard + MJPEG camera stream
├── tests/                     # 128 tests — all pass in simulation
│   ├── conftest.py            # Shared fixtures (fast_sleep patches time.sleep)
│   ├── test_arm_control.py
│   ├── test_calibration.py
│   ├── test_integration.py    # Full voice→detect→grasp→log pipeline
│   ├── test_object_detection.py
│   ├── test_safety.py
│   ├── test_session_logger.py
│   ├── test_tts.py
│   └── test_voice_command.py
├── tools/
│   └── log_analyzer.py        # Research stats from JSONL logs (per-object rates, CSV)
└── .github/
    └── workflows/ci.yml       # GitHub Actions: pytest on Python 3.11 + 3.12
```

---

## Quick Start

### Simulation mode (no hardware needed)

```bash
git clone https://github.com/anshjaitly/reachbot.git
cd reachbot
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."   # Whisper transcription

python main.py --simulate
# Say (or type when prompted): "pick up my remote"
```

### With web dashboard

```bash
python main.py --simulate --web
# Open http://localhost:8000 for live arm status + camera feed
```

### Run the test suite

```bash
python -m pytest tests/ -v
# 128 tests, ~8 seconds, no hardware required
```

### Analyze session logs (after real runs)

```bash
python tools/log_analyzer.py              # Full report with per-object bar chart
python tools/log_analyzer.py --summary   # One-liner: n=X success=Y% μ=Zs
python tools/log_analyzer.py --csv out.csv
```

### Raspberry Pi setup (one command)

```bash
bash setup.sh          # Enables I2C, creates venv, installs deps, downloads YOLOv8n
bash setup.sh --service  # Also installs systemd service for auto-start on boot
```

---

## Research Context

ReachBot is being developed as a Regeneron STS research project. The focus is on measuring real-world grasp success rates across object classes common in senior-care settings (phones, glasses, remotes, pill bottles, keys).

Session logs capture: target object, YOLOv8 detection confidence, real-world XYZ position, grasp success/fail, failure mode, and total attempt duration. After user testing at senior facilities, `tools/log_analyzer.py` produces the stats table and the STS citation line (`n=X, success=Y%, μ=Zs/attempt, σ_conf=Z`).

---

## Wrist Auto-Leveling

One non-obvious piece of the IK: the wrist needs to stay level with the ground regardless of shoulder and elbow angle so the gripper approaches objects flat. The formula is:

```
wrist_deg = 90 + shoulder_deg − elbow_deg
```

This is computed automatically in `arm_control.py` on every `move_to()` call.

---

## Acknowledgments

- **ETH Zurich Soft Robotics Lab** — for open-sourcing the ORCA Hand v1 under CC BY 4.0  
  *Christoph C.C., Eberlein M., Katsimalis F., Roberti A., Sympetheros A., Vogt M.R., Liconti D., Yang C., Cangan B.G., Hinchet R.J., Katzschmann R.K.*
- **Ultralytics** — YOLOv8 object detection
- **OpenAI** — Whisper speech recognition

---

## License

MIT — see [LICENSE](LICENSE).

---

## Contact

**Ansh Jaitly** · Dougherty Valley High School  
Project site: [reachbot-arm.netlify.app](https://reachbot-arm.netlify.app/)
