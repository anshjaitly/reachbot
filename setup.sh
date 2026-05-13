#!/bin/bash
# =============================================================================
# ReachBot — Raspberry Pi Setup Script
# =============================================================================
# Run once on a fresh Raspberry Pi OS (Bookworm 64-bit recommended).
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# What this does:
#   1. Enables I2C for PCA9685 servo driver
#   2. Installs system packages (Python 3, git, ffmpeg, portaudio)
#   3. Installs Python dependencies from requirements.txt
#   4. Downloads YOLOv8n model
#   5. Optionally installs ReachBot as a systemd service (auto-start on boot)
# =============================================================================

set -e  # Exit immediately on any error

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[⚠]${NC} $1"; }
info() { echo -e "${BLUE}[→]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   ReachBot Pi Setup — github.com/    ║"
echo "║   anshjaitly/reachbot                ║"
echo "╚══════════════════════════════════════╝"
echo ""

# =============================================================================
# 1. Check we're on a Raspberry Pi
# =============================================================================
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    warn "Not detected as Raspberry Pi — continuing anyway (development mode)."
fi

# =============================================================================
# 2. System update
# =============================================================================
info "Updating package lists..."
sudo apt-get update -q

info "Installing system packages..."
sudo apt-get install -y -q \
    python3-pip \
    python3-venv \
    git \
    ffmpeg \
    portaudio19-dev \
    python3-dev \
    libasound2-dev \
    libatlas-base-dev \
    i2c-tools \
    libcamera-apps \
    2>/dev/null || warn "Some packages may not be available on this OS version."

log "System packages installed."

# =============================================================================
# 3. Enable I2C for PCA9685 servo driver
# =============================================================================
info "Enabling I2C interface..."
if command -v raspi-config &>/dev/null; then
    sudo raspi-config nonint do_i2c 0
    log "I2C enabled via raspi-config."
else
    # Manual method — add to /boot/config.txt
    if ! grep -q "^dtparam=i2c_arm=on" /boot/config.txt 2>/dev/null && \
       ! grep -q "^dtparam=i2c_arm=on" /boot/firmware/config.txt 2>/dev/null; then
        warn "raspi-config not found. Add 'dtparam=i2c_arm=on' to /boot/firmware/config.txt manually."
    else
        log "I2C already enabled in config.txt."
    fi
fi

# Verify I2C kernel modules
if lsmod | grep -q i2c_dev; then
    log "I2C kernel module loaded."
else
    warn "I2C module not loaded yet — reboot required after setup."
fi

# =============================================================================
# 4. Python virtual environment
# =============================================================================
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    info "Creating Python virtual environment at .venv..."
    python3 -m venv "$VENV_DIR"
    log "Virtual environment created."
else
    log "Virtual environment already exists."
fi

source "$VENV_DIR/bin/activate"
info "Upgrading pip..."
pip install --upgrade pip -q

# =============================================================================
# 5. Python dependencies
# =============================================================================
info "Installing Python dependencies from requirements.txt..."
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    pip install -r "$SCRIPT_DIR/requirements.txt" -q
    log "Python dependencies installed."
else
    err "requirements.txt not found at $SCRIPT_DIR"
fi

# =============================================================================
# 6. Raspberry Pi hardware libraries
# =============================================================================
info "Installing Raspberry Pi hardware libraries..."
pip install -q \
    adafruit-circuitpython-servokit \
    adafruit-circuitpython-pca9685 \
    RPi.GPIO \
    2>/dev/null || warn "Hardware libraries failed — may need reboot with I2C enabled."

log "Hardware libraries installed."

# =============================================================================
# 7. Download YOLOv8n model (if not already cached)
# =============================================================================
YOLO_CACHE="$HOME/.cache/ultralytics/yolov8n.pt"
if [ -f "$YOLO_CACHE" ]; then
    log "YOLOv8n model already cached at $YOLO_CACHE"
else
    info "Downloading YOLOv8n model (~6MB)..."
    python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" 2>/dev/null \
        && log "YOLOv8n downloaded." \
        || warn "YOLOv8n download failed — will retry on first run."
fi

# =============================================================================
# 8. Check for OpenAI API key
# =============================================================================
if [ -z "$OPENAI_API_KEY" ]; then
    warn "OPENAI_API_KEY not set."
    echo ""
    echo "  To use Whisper voice recognition, add to ~/.bashrc:"
    echo "  export OPENAI_API_KEY='sk-...'"
    echo ""
    echo "  Or set it before running ReachBot:"
    echo "  OPENAI_API_KEY='sk-...' python main.py"
    echo ""
else
    log "OPENAI_API_KEY is set."
fi

# =============================================================================
# 9. Verify wiring reminder
# =============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  PCA9685 Wiring (I2C):"
echo "  PCA9685 SDA  → Pi GPIO 2  (Pin 3)"
echo "  PCA9685 SCL  → Pi GPIO 3  (Pin 5)"
echo "  PCA9685 VCC  → Pi 3.3V    (Pin 1)"
echo "  PCA9685 GND  → Pi GND     (Pin 6)"
echo "  PCA9685 V+   → 6V PSU     (NOT Pi 5V — servos need external power)"
echo ""
echo "  E-stop button:"
echo "  One leg → GPIO 17 (Pin 11)"
echo "  Other   → GND     (Pin 9)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# =============================================================================
# 10. Optional: systemd service for auto-start
# =============================================================================
read -r -p "Install ReachBot as a systemd service (auto-start on boot)? [y/N]: " INSTALL_SERVICE
if [[ "$INSTALL_SERVICE" =~ ^[Yy]$ ]]; then
    SERVICE_FILE="/etc/systemd/system/reachbot.service"
    sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=ReachBot — Voice-Controlled Assistive Arm
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=$VENV_DIR/bin/python $SCRIPT_DIR/main.py --web
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable reachbot.service
    log "ReachBot service installed and enabled."
    echo "  Start now:     sudo systemctl start reachbot"
    echo "  View logs:     sudo journalctl -u reachbot -f"
    echo "  Disable:       sudo systemctl disable reachbot"
fi

# =============================================================================
# Done
# =============================================================================
echo ""
log "Setup complete!"
echo ""
echo "  Run ReachBot:"
echo "    source .venv/bin/activate"
echo "    python main.py              # Hardware mode"
echo "    python main.py --web        # + Web dashboard at :8000"
echo ""
echo "  Test ORCA Hand only:"
echo "    python gripper_test.py --sweep"
echo ""
echo "  Run camera calibration:"
echo "    python src/calibration.py"
echo ""
if ! lsmod | grep -q i2c_dev; then
    warn "Reboot required to activate I2C:"
    echo "    sudo reboot"
fi
