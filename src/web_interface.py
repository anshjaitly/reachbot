"""
ReachBot — Web Dashboard (FastAPI)

A lightweight web interface so caregivers or researchers can:
  - See live arm status (joint angles, last command, session stats)
  - Control the arm manually from a phone/tablet (home, open/close gripper)
  - Stream the camera feed
  - Download session logs

Run from project root:
    uvicorn src.web_interface:app --host 0.0.0.0 --port 8000

Then visit: http://<raspberry-pi-ip>:8000
"""

import base64
import io
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
    from pydantic import BaseModel
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    log.warning("FastAPI not installed — web interface unavailable")

try:
    import cv2
    CV_AVAILABLE = True
except ImportError:
    CV_AVAILABLE = False

# These are set by inject_dependencies() after the arm/logger are created
_arm = None
_logger = None
_safety = None


def inject_dependencies(arm_controller, session_logger, safety_monitor=None):
    """Call this from main.py before starting uvicorn."""
    global _arm, _logger, _safety
    _arm = arm_controller
    _logger = session_logger
    _safety = safety_monitor


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

if FASTAPI_AVAILABLE:
    app = FastAPI(title="ReachBot Dashboard", version="1.0")
else:
    app = None   # Import guard — main.py checks FASTAPI_AVAILABLE


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

if FASTAPI_AVAILABLE:
    class ServoCommand(BaseModel):
        channel: int
        angle: float

    class MoveCommand(BaseModel):
        x_mm: float
        y_mm: float
        z_mm: float


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

if FASTAPI_AVAILABLE:

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        """Serve the control dashboard HTML."""
        return _build_dashboard_html()


    @app.get("/status")
    async def status():
        """Return current arm state and session statistics."""
        stats = _logger.summary() if _logger else {}
        estop = _safety.is_stopped if _safety else False
        return JSONResponse({
            "estop_active": estop,
            "session_stats": stats,
            "timestamp": time.time(),
        })


    @app.post("/arm/home")
    async def arm_home():
        """Send arm to home position."""
        if _safety and _safety.is_stopped:
            raise HTTPException(status_code=503, detail="E-stop active")
        if _arm is None:
            raise HTTPException(status_code=503, detail="Arm not initialized")
        _arm.home()
        if _safety:
            _safety.ping()
        return {"ok": True, "action": "home"}


    @app.post("/arm/gripper/open")
    async def gripper_open():
        if _safety and _safety.is_stopped:
            raise HTTPException(status_code=503, detail="E-stop active")
        if _arm is None:
            raise HTTPException(status_code=503, detail="Arm not initialized")
        _arm.open_gripper()
        if _safety:
            _safety.ping()
        return {"ok": True, "action": "gripper_open"}


    @app.post("/arm/gripper/close")
    async def gripper_close():
        if _safety and _safety.is_stopped:
            raise HTTPException(status_code=503, detail="E-stop active")
        if _arm is None:
            raise HTTPException(status_code=503, detail="Arm not initialized")
        _arm.close_gripper()
        if _safety:
            _safety.ping()
        return {"ok": True, "action": "gripper_close"}


    @app.post("/arm/servo")
    async def set_servo(cmd: ServoCommand):
        """Directly command a single servo (for debugging)."""
        if _safety and _safety.is_stopped:
            raise HTTPException(status_code=503, detail="E-stop active")
        if _arm is None:
            raise HTTPException(status_code=503, detail="Arm not initialized")
        angle = _safety.check_servo_angle(cmd.channel, cmd.angle) if _safety else cmd.angle
        _arm.set_angle(cmd.channel, angle)
        return {"ok": True, "channel": cmd.channel, "angle": angle}


    @app.post("/arm/estop")
    async def emergency_stop():
        """Trigger software e-stop."""
        if _safety:
            _safety.request_estop("Web dashboard e-stop button")
        elif _arm:
            _arm.shutdown()
        return {"ok": True, "action": "estop"}


    @app.get("/camera/snapshot")
    async def camera_snapshot():
        """Return a single JPEG frame from the webcam as base64."""
        if not CV_AVAILABLE:
            raise HTTPException(status_code=503, detail="OpenCV not available")
        cap = cv2.VideoCapture(0)
        try:
            for _ in range(3):
                cap.read()
            ret, frame = cap.read()
            if not ret:
                raise HTTPException(status_code=503, detail="Camera read failed")
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            b64 = base64.b64encode(buf.tobytes()).decode()
            return {"image_base64": b64, "format": "jpeg"}
        finally:
            cap.release()


    @app.get("/camera/stream")
    async def camera_stream():
        """MJPEG stream for live camera view."""
        if not CV_AVAILABLE:
            raise HTTPException(status_code=503, detail="OpenCV not available")

        def generate():
            cap = cv2.VideoCapture(0)
            try:
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    _, buf = cv2.imencode(".jpg", frame,
                                         [cv2.IMWRITE_JPEG_QUALITY, 60])
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + buf.tobytes()
                        + b"\r\n"
                    )
                    time.sleep(0.1)  # ~10 fps
            finally:
                cap.release()

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )


    @app.get("/logs")
    async def list_logs():
        """List available session log files."""
        log_dir = Path.home() / "reachbot_logs"
        if not log_dir.exists():
            return {"logs": []}
        files = sorted(log_dir.glob("session_*.jsonl"), reverse=True)
        return {
            "logs": [
                {"name": f.name, "size_bytes": f.stat().st_size}
                for f in files[:20]
            ]
        }


    @app.get("/logs/{filename}")
    async def download_log(filename: str):
        """Download a specific session log."""
        log_dir = Path.home() / "reachbot_logs"
        path = log_dir / filename
        if not path.exists() or not path.suffix == ".jsonl":
            raise HTTPException(status_code=404, detail="Log not found")
        return StreamingResponse(
            open(path, "rb"),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------

def _build_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ReachBot Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #0f1117; color: #e2e8f0; min-height: 100vh; padding: 1rem; }
    h1 { font-size: 1.5rem; font-weight: 700; color: #38bdf8; margin-bottom: 1rem; }
    h2 { font-size: 1rem; font-weight: 600; color: #94a3b8; margin-bottom: 0.5rem; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1rem; }
    .card { background: #1e2532; border-radius: 12px; padding: 1.25rem;
            border: 1px solid #2d3748; }
    .btn { display: block; width: 100%; padding: 0.75rem;
           border: none; border-radius: 8px; font-size: 1rem; font-weight: 600;
           cursor: pointer; margin-bottom: 0.5rem; transition: opacity 0.15s; }
    .btn:hover { opacity: 0.85; }
    .btn-blue  { background: #3b82f6; color: white; }
    .btn-green { background: #22c55e; color: white; }
    .btn-amber { background: #f59e0b; color: white; }
    .btn-red   { background: #ef4444; color: white; font-size: 1.1rem; }
    .status-box { background: #0f1117; border-radius: 8px; padding: 0.75rem;
                  font-family: monospace; font-size: 0.85rem; white-space: pre-wrap;
                  min-height: 80px; }
    img#feed { width: 100%; border-radius: 8px; background: #0f1117; }
    .badge { display: inline-block; padding: 0.2rem 0.6rem;
             border-radius: 999px; font-size: 0.75rem; font-weight: 700; }
    .badge-ok  { background: #14532d; color: #4ade80; }
    .badge-err { background: #450a0a; color: #f87171; }
  </style>
</head>
<body>
  <h1>ReachBot Dashboard</h1>
  <div class="grid">

    <!-- Controls -->
    <div class="card">
      <h2>Arm Controls</h2>
      <button class="btn btn-blue"  onclick="post('/arm/home')">Home Position</button>
      <button class="btn btn-green" onclick="post('/arm/gripper/open')">Open Gripper</button>
      <button class="btn btn-amber" onclick="post('/arm/gripper/close')">Close Gripper</button>
      <button class="btn btn-red"   onclick="estop()">&#9888; EMERGENCY STOP</button>
    </div>

    <!-- Status -->
    <div class="card">
      <h2>System Status <span id="estop-badge" class="badge badge-ok">OK</span></h2>
      <div id="status-box" class="status-box">Loading...</div>
    </div>

    <!-- Camera -->
    <div class="card">
      <h2>Camera</h2>
      <img id="feed" src="/camera/stream" alt="Live camera feed"
           onerror="this.alt='Camera unavailable'">
    </div>

  </div>

  <script>
    async function post(url) {
      try {
        const r = await fetch(url, { method: 'POST' });
        const d = await r.json();
        console.log(url, d);
      } catch(e) { alert('Error: ' + e); }
    }

    async function estop() {
      if (!confirm('Trigger emergency stop? Arm will shut down.')) return;
      await post('/arm/estop');
      document.getElementById('estop-badge').className = 'badge badge-err';
      document.getElementById('estop-badge').textContent = 'E-STOP';
    }

    async function refreshStatus() {
      try {
        const r = await fetch('/status');
        const d = await r.json();
        const s = d.session_stats;
        const box = document.getElementById('status-box');
        box.textContent = [
          'E-Stop: ' + (d.estop_active ? 'ACTIVE' : 'clear'),
          '',
          '-- Session --',
          'Attempts  : ' + (s.total ?? 0),
          'Successes : ' + (s.successes ?? 0),
          'Rate      : ' + ((s.success_rate ?? 0) * 100).toFixed(1) + '%',
        ].join('\\n');
        const badge = document.getElementById('estop-badge');
        if (d.estop_active) {
          badge.className = 'badge badge-err';
          badge.textContent = 'E-STOP';
        } else {
          badge.className = 'badge badge-ok';
          badge.textContent = 'OK';
        }
      } catch(e) { /* offline */ }
    }

    setInterval(refreshStatus, 2000);
    refreshStatus();
  </script>
</body>
</html>"""
