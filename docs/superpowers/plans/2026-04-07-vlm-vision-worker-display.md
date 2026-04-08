# VLM Vision — Worker Display Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full-screen browser overlay that workers see on the Modula bay screen — live camera feed with bounding boxes, pick guidance, and pick state feedback.

**Architecture:** A `FrameStore` module buffers the latest camera frame per bay. `display_server.py` gains an MJPEG endpoint (`/bay/{bay_id}/video`) and serves static overlay files. The browser loads a single HTML page that displays the MJPEG stream in an `<img>` tag with a `<canvas>` overlay, driven by WebSocket detection data for bounding boxes and state transitions.

**Tech Stack:** Python 3.11, FastAPI (StreamingResponse, StaticFiles), OpenCV (JPEG encode), vanilla HTML5/CSS3/JavaScript (no build step), WebSocket API (browser-native)

---

## File Structure

```
vlm_vision/
├── local_agent/
│   ├── frame_store.py        # NEW: thread-safe per-bay latest-frame buffer
│   ├── display_server.py     # MODIFY: add MJPEG endpoint, static files, update_frame()
│   └── main.py               # MODIFY: call update_frame() after each detection
├── overlay/
│   ├── bay.html              # Full-screen worker pick display
│   ├── bay.css               # Dark theme, state animations, bounding-box colours
│   └── bay.js                # WebSocket client + canvas renderer + state machine
└── tests/
    ├── test_frame_store.py   # Unit tests for FrameStore
    └── test_display_server.py # Integration tests for MJPEG and WebSocket endpoints
```

**Dependency on Plan 1:** `display_server.py`, `main.py`, and all models must already exist.

---

## Task 1: FrameStore

**Files:**
- Create: `vlm_vision/local_agent/frame_store.py`
- Create: `vlm_vision/tests/test_frame_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# vlm_vision/tests/test_frame_store.py
import numpy as np
import threading
import pytest
from local_agent.frame_store import FrameStore


def make_frame(value: int = 128) -> np.ndarray:
    return np.full((480, 640, 3), value, dtype=np.uint8)


def test_get_returns_none_before_any_update():
    store = FrameStore()
    assert store.get(bay_id=1) is None


def test_update_and_get_returns_frame():
    store = FrameStore()
    frame = make_frame(100)
    store.update(bay_id=1, frame=frame)
    result = store.get(bay_id=1)
    assert result is not None
    assert result.shape == (480, 640, 3)
    assert result[0, 0, 0] == 100


def test_update_stores_copy_not_reference():
    store = FrameStore()
    frame = make_frame(50)
    store.update(bay_id=1, frame=frame)
    frame[0, 0, 0] = 255  # mutate original
    result = store.get(bay_id=1)
    assert result[0, 0, 0] == 50  # store is unaffected


def test_separate_bays_are_independent():
    store = FrameStore()
    store.update(bay_id=1, frame=make_frame(10))
    store.update(bay_id=2, frame=make_frame(20))
    assert store.get(bay_id=1)[0, 0, 0] == 10
    assert store.get(bay_id=2)[0, 0, 0] == 20
    assert store.get(bay_id=3) is None


def test_concurrent_updates_are_safe():
    store = FrameStore()
    errors = []

    def writer(bay_id, value):
        try:
            for _ in range(100):
                store.update(bay_id=bay_id, frame=make_frame(value))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i, i * 10)) for i in range(1, 4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    for i in range(1, 4):
        assert store.get(bay_id=i) is not None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd vlm_vision && python3 -m pytest tests/test_frame_store.py -v
```

Expected: `ImportError: cannot import name 'FrameStore'`

- [ ] **Step 3: Implement frame_store.py**

```python
# vlm_vision/local_agent/frame_store.py
"""
Thread-safe per-bay frame buffer.
Holds the latest captured frame for each bay so the MJPEG endpoint
can serve it without touching the detection queue.
"""
import threading
import numpy as np
from typing import Dict, Optional


class FrameStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frames: Dict[int, np.ndarray] = {}

    def update(self, bay_id: int, frame: np.ndarray) -> None:
        with self._lock:
            self._frames[bay_id] = frame.copy()

    def get(self, bay_id: int) -> Optional[np.ndarray]:
        with self._lock:
            return self._frames.get(bay_id)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd vlm_vision && python3 -m pytest tests/test_frame_store.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant add vlm_vision/local_agent/frame_store.py vlm_vision/tests/test_frame_store.py
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant commit -m "feat: vlm-overlay FrameStore thread-safe frame buffer"
```

---

## Task 2: Extend display_server.py (MJPEG + Static Files)

**Files:**
- Modify: `vlm_vision/local_agent/display_server.py`
- Create: `vlm_vision/tests/test_display_server.py`

The existing `display_server.py` has a FastAPI `app`, a WebSocket endpoint, and a `broadcast()` coroutine. This task adds:
1. A module-level `frame_store` instance
2. `update_frame(bay_id, frame)` — called by `main.py` to store latest frame
3. `GET /bay/{bay_id}/video` — MJPEG streaming endpoint
4. Static file serving for `overlay/` at `/`

- [ ] **Step 1: Write the failing tests**

```python
# vlm_vision/tests/test_display_server.py
import numpy as np
import pytest
from fastapi.testclient import TestClient


def make_frame(value: int = 128) -> np.ndarray:
    return np.full((480, 640, 3), value, dtype=np.uint8)


def test_update_frame_stores_frame():
    from local_agent.display_server import update_frame, frame_store
    update_frame(bay_id=1, frame=make_frame(99))
    result = frame_store.get(bay_id=1)
    assert result is not None
    assert result.shape == (480, 640, 3)


def test_mjpeg_endpoint_returns_503_without_frame(monkeypatch):
    import local_agent.display_server as ds
    from local_agent.display_server import app, frame_store
    from local_agent.frame_store import FrameStore
    # Replace frame_store with empty one
    monkeypatch.setattr(ds, "frame_store", FrameStore())

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/bay/99/video")
    assert response.status_code == 503
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd vlm_vision && python3 -m pytest tests/test_display_server.py -v
```

Expected: `ImportError` — `update_frame` and `frame_store` not yet in display_server

- [ ] **Step 3: Rewrite display_server.py with MJPEG and static files**

Replace the full contents of `vlm_vision/local_agent/display_server.py`:

```python
# vlm_vision/local_agent/display_server.py
"""
FastAPI server with three responsibilities:
  1. WebSocket /bay/{bay_id}           — push detection state to overlay clients
  2. GET /bay/{bay_id}/video           — MJPEG stream from latest camera frame
  3. Static files at /                 — serves the overlay/ HTML/CSS/JS
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

import cv2
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from local_agent.frame_store import FrameStore
from local_agent.models import BayStatus, Detection, PickOrder

app = FastAPI()

# Module-level singletons shared with main.py
frame_store = FrameStore()
_connections: Dict[int, Set[WebSocket]] = {}

# Serve overlay/ as static files at /ui (mounted after routes are defined)
_OVERLAY_DIR = Path(__file__).parent.parent / "overlay"


def _mount_static() -> None:
    if _OVERLAY_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_OVERLAY_DIR), html=True), name="overlay")


# ── Frame store helper ──────────────────────────────────────────────────────

def update_frame(bay_id: int, frame) -> None:
    """Called by main.py after each detection to keep MJPEG feed fresh."""
    frame_store.update(bay_id=bay_id, frame=frame)


# ── WebSocket endpoint ──────────────────────────────────────────────────────

@app.websocket("/bay/{bay_id}")
async def bay_websocket(websocket: WebSocket, bay_id: int):
    await websocket.accept()
    _connections.setdefault(bay_id, set()).add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _connections.get(bay_id, set()).discard(websocket)


async def broadcast(
    bay_id: int,
    status: BayStatus,
    detections: List[Detection],
    active_order: Optional[PickOrder],
    result: Optional[str] = None,
) -> None:
    clients = _connections.get(bay_id, set())
    if not clients:
        return

    payload = json.dumps({
        "bay_id": bay_id,
        "status": status.value,
        "result": result,
        "detections": [
            {
                "sku": d.sku,
                "color": d.color,
                "confidence": round(d.confidence, 3),
                "bbox": list(d.bbox),
            }
            for d in detections
        ],
        "active_order": {
            "order_id": active_order.order_id,
            "sku": active_order.sku,
            "qty": active_order.qty,
        } if active_order else None,
    })

    dead: Set[WebSocket] = set()
    for ws in list(clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    clients -= dead


# ── MJPEG streaming endpoint ────────────────────────────────────────────────

@app.get("/bay/{bay_id}/video")
async def mjpeg_stream(bay_id: int):
    frame = frame_store.get(bay_id)
    if frame is None:
        raise HTTPException(status_code=503, detail="No frame available for bay")

    async def generate():
        while True:
            current = frame_store.get(bay_id)
            if current is not None:
                _, buf = cv2.imencode(
                    ".jpg", current, [cv2.IMWRITE_JPEG_QUALITY, 70]
                )
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + buf.tobytes()
                    + b"\r\n"
                )
            await asyncio.sleep(0.05)  # ~20 fps max

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# Mount static files last so API routes take priority
_mount_static()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd vlm_vision && python3 -m pytest tests/test_display_server.py -v
```

Expected: 3 passed

- [ ] **Step 5: Run all existing tests to confirm no regression**

```bash
cd vlm_vision && python3 -m pytest tests/ -v --tb=short
```

Expected: all 23 tests pass (18 from Plan 1 + 5 from frame_store)

- [ ] **Step 6: Commit**

```bash
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant add vlm_vision/local_agent/display_server.py vlm_vision/tests/test_display_server.py
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant commit -m "feat: vlm-overlay MJPEG stream and static file serving"
```

---

## Task 3: Wire main.py to FrameStore

**Files:**
- Modify: `vlm_vision/local_agent/main.py` (add one import + one call)

- [ ] **Step 1: Read current main.py to find the right insertion points**

```bash
grep -n "detector.detect\|from local_agent" vlm_vision/local_agent/main.py
```

- [ ] **Step 2: Add update_frame import to main.py**

In `vlm_vision/local_agent/main.py`, add `update_frame` to the display_server import line:

```python
# Change this line:
from local_agent.display_server import app, broadcast
# To:
from local_agent.display_server import app, broadcast, update_frame
```

- [ ] **Step 3: Call update_frame after each detection in run_bay()**

In `run_bay()`, immediately after `detections = detector.detect(frame)`, add:

```python
        detections = detector.detect(frame)
        update_frame(bay_id, frame)   # keep MJPEG feed current
```

- [ ] **Step 3b: Pass pick result to CONFIRMING broadcast in run_bay()**

Find this line in `run_bay()`:
```python
                asyncio.run_coroutine_threadsafe(
                    broadcast(bay_id, BayStatus.CONFIRMING, after, None), loop
                )
```
Replace with:
```python
                asyncio.run_coroutine_threadsafe(
                    broadcast(bay_id, BayStatus.CONFIRMING, after, None, result=event.result), loop
                )
```

- [ ] **Step 4: Run all tests to confirm no regression**

```bash
cd vlm_vision && python3 -m pytest tests/ -v --tb=short
```

Expected: all 26 tests pass (18 plan-1 + 5 frame_store + 3 display_server)

- [ ] **Step 5: Commit**

```bash
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant add vlm_vision/local_agent/main.py
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant commit -m "feat: vlm-overlay feed frames into display server for MJPEG"
```

---

## Task 4: Overlay HTML and CSS

**Files:**
- Create: `vlm_vision/overlay/bay.html`
- Create: `vlm_vision/overlay/bay.css`

No automated tests — verify manually by opening `http://localhost:8765/bay.html?bay=1` after the server is running.

- [ ] **Step 1: Create overlay/ directory**

```bash
mkdir -p /Users/alfonsomendez/Documents/Dhar/email_ai_assistant/vlm_vision/overlay
```

- [ ] **Step 2: Write bay.html**

```html
<!-- vlm_vision/overlay/bay.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VLM Pick Bay</title>
  <link rel="stylesheet" href="bay.css">
</head>
<body>
  <div id="app" class="state-waiting">

    <!-- Top bar -->
    <div id="top-bar">
      <span id="bay-label">BAY —</span>
      <span id="worker-label">Operator</span>
      <span id="live-dot" class="dot-offline">● CONNECTING</span>
    </div>

    <!-- Camera + canvas overlay -->
    <div id="camera-wrap">
      <img id="video-feed" alt="camera feed">
      <canvas id="overlay-canvas"></canvas>

      <!-- Waiting spinner -->
      <div id="waiting-msg">
        <div class="spinner"></div>
        <p>Waiting for tray…</p>
      </div>

      <!-- State flash overlays -->
      <div id="correct-flash">
        <span class="flash-icon">✓</span>
        <span class="flash-text">Correct Part!</span>
      </div>
      <div id="wrong-flash">
        <span class="flash-icon">✗</span>
        <span class="flash-text">Wrong Part!</span>
        <span class="flash-sub" id="wrong-detail"></span>
      </div>
    </div>

    <!-- Pick order bar -->
    <div id="order-bar">
      <div id="order-left">
        <div id="order-id-label">—</div>
        <div id="sku-display">—</div>
        <div id="sku-desc">Waiting for order</div>
      </div>
      <div id="order-right">
        <div class="bar-label">QTY NEEDED</div>
        <div id="qty-display">—</div>
      </div>
    </div>

    <!-- Status bar -->
    <div id="status-bar">
      <span id="pick-timer">00:00</span>
      <span class="sep">|</span>
      <span id="last-result">—</span>
      <span class="sep">|</span>
      <span id="ws-status">Connecting…</span>
    </div>

  </div>
  <script src="bay.js"></script>
</body>
</html>
```

- [ ] **Step 3: Write bay.css**

```css
/* vlm_vision/overlay/bay.css */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  height: 100%;
  background: #0a0a0a;
  color: #e0e0e0;
  font-family: 'Segoe UI', system-ui, sans-serif;
  overflow: hidden;
}

#app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

/* ── Top bar ─────────────────────────────────────────────────── */
#top-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 16px;
  background: #1a1a2e;
  border-bottom: 1px solid #333;
  font-size: 13px;
  flex-shrink: 0;
}
#bay-label   { font-weight: bold; color: #7bd4ff; letter-spacing: 1px; }
#worker-label{ color: #aaa; }
#live-dot    { margin-left: auto; font-size: 12px; }
.dot-live    { color: #7bff7b; }
.dot-offline { color: #ff7b7b; }

/* ── Camera area ─────────────────────────────────────────────── */
#camera-wrap {
  position: relative;
  flex: 1;
  overflow: hidden;
  background: #111;
  display: flex;
  align-items: center;
  justify-content: center;
}
#video-feed {
  max-width: 100%;
  max-height: 100%;
  display: block;
}
#overlay-canvas {
  position: absolute;
  top: 0; left: 0;
  pointer-events: none;
}

/* ── Waiting state ───────────────────────────────────────────── */
#waiting-msg {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: #888;
}
.spinner {
  width: 48px; height: 48px;
  border: 4px solid #333;
  border-top-color: #7bd4ff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.state-active   #waiting-msg,
.state-correct  #waiting-msg,
.state-wrong    #waiting-msg { display: none; }
.state-waiting  #waiting-msg { display: flex; }

/* ── Flash overlays ──────────────────────────────────────────── */
#correct-flash, #wrong-flash {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
}
#correct-flash { background: rgba(0, 180, 0, 0.55); }
#wrong-flash   { background: rgba(200, 0, 0, 0.55); }

.flash-icon { font-size: 72px; }
.flash-text { font-size: 32px; font-weight: bold; }
.flash-sub  { font-size: 16px; color: rgba(255,255,255,0.8); }

.state-correct #correct-flash { opacity: 1; }
.state-wrong   #wrong-flash   { opacity: 1; }

/* ── Order bar ───────────────────────────────────────────────── */
#order-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #161b27;
  border-top: 1px solid #333;
  flex-shrink: 0;
}
#order-id-label { font-size: 11px; color: #666; margin-bottom: 2px; }
#sku-display    { font-size: 20px; font-weight: bold; color: #fff; }
#sku-desc       { font-size: 12px; color: #aaa; }
#order-right    { text-align: right; }
.bar-label      { font-size: 10px; color: #666; margin-bottom: 4px; }
#qty-display    { font-size: 28px; font-weight: bold; color: #ffd700; }

/* ── Status bar ──────────────────────────────────────────────── */
#status-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 5px 16px;
  background: #0d1117;
  border-top: 1px solid #222;
  font-size: 11px;
  color: #666;
  flex-shrink: 0;
}
.sep { color: #333; }
#last-result.result-correct { color: #7bff7b; }
#last-result.result-wrong   { color: #ff7b7b; }
```

- [ ] **Step 4: Commit**

```bash
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant add vlm_vision/overlay/
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant commit -m "feat: vlm-overlay bay.html and bay.css full-screen layout"
```

---

## Task 5: Overlay JavaScript

**Files:**
- Create: `vlm_vision/overlay/bay.js`

- [ ] **Step 1: Write bay.js**

```javascript
// vlm_vision/overlay/bay.js
/**
 * Connects to the WebSocket at ws://localhost:{port}/bay/{bayId}
 * and renders detection bounding boxes on the canvas overlay.
 *
 * URL params: ?bay=1  (defaults to 1)
 * State machine: waiting → active → correct|wrong → waiting
 */

// ── Configuration ────────────────────────────────────────────────────────────
const params   = new URLSearchParams(window.location.search);
const BAY_ID   = parseInt(params.get('bay') || '1', 10);
const WS_PORT  = parseInt(params.get('port') || location.port || '8765', 10);
const WS_URL   = `ws://${location.hostname}:${WS_PORT}/bay/${BAY_ID}`;
// Source resolution the model was trained on (must match camera capture res)
const SRC_W    = 3840;
const SRC_H    = 2160;
// Colours
const COL_TARGET = '#ffd700';  // gold
const COL_OTHER  = '#4a9eff';  // blue
// Flash durations (ms)
const CORRECT_FLASH_MS = 1500;
const WRONG_FLASH_MS   = 3000;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const app         = document.getElementById('app');
const bayLabel    = document.getElementById('bay-label');
const liveDot     = document.getElementById('live-dot');
const videoFeed   = document.getElementById('video-feed');
const canvas      = document.getElementById('overlay-canvas');
const ctx         = canvas.getContext('2d');
const orderIdEl   = document.getElementById('order-id-label');
const skuEl       = document.getElementById('sku-display');
const skuDescEl   = document.getElementById('sku-desc');
const qtyEl       = document.getElementById('qty-display');
const timerEl     = document.getElementById('pick-timer');
const lastResultEl= document.getElementById('last-result');
const wrongDetail = document.getElementById('wrong-detail');
const wsStatusEl  = document.getElementById('ws-status');

// ── State ─────────────────────────────────────────────────────────────────────
let currentState   = 'waiting';
let pickStartTime  = null;
let flashTimeout   = null;
let timerInterval  = null;

// ── Initialise ────────────────────────────────────────────────────────────────
bayLabel.textContent = `BAY ${BAY_ID}`;
videoFeed.src = `/bay/${BAY_ID}/video`;

// Resize canvas to match displayed image size whenever window resizes
function resizeCanvas() {
  const rect = videoFeed.getBoundingClientRect();
  canvas.width  = rect.width  || videoFeed.offsetWidth;
  canvas.height = rect.height || videoFeed.offsetHeight;
  canvas.style.left = rect.left - videoFeed.parentElement.getBoundingClientRect().left + 'px';
  canvas.style.top  = rect.top  - videoFeed.parentElement.getBoundingClientRect().top  + 'px';
}
window.addEventListener('resize', resizeCanvas);
videoFeed.addEventListener('load', resizeCanvas);

// ── State machine ─────────────────────────────────────────────────────────────
function setState(state, extra) {
  if (flashTimeout && state !== 'correct' && state !== 'wrong') {
    clearTimeout(flashTimeout);
    flashTimeout = null;
  }
  currentState = state;
  app.className = `state-${state}`;

  if (state === 'active') {
    if (!pickStartTime) {
      pickStartTime = Date.now();
      timerInterval = setInterval(updateTimer, 500);
    }
  }

  if (state === 'correct') {
    playBeep(880, 0.15);
    stopTimer();
    lastResultEl.textContent = '✓ Correct pick';
    lastResultEl.className = 'result-correct';
    flashTimeout = setTimeout(() => setState('waiting'), CORRECT_FLASH_MS);
  }

  if (state === 'wrong') {
    playBeep(220, 0.4);
    stopTimer();
    wrongDetail.textContent = extra ? `Got: ${extra}` : '';
    lastResultEl.textContent = '✗ Wrong pick';
    lastResultEl.className = 'result-wrong';
    flashTimeout = setTimeout(() => setState('waiting'), WRONG_FLASH_MS);
  }

  if (state === 'waiting') {
    stopTimer();
    pickStartTime = null;
    clearCanvas();
  }
}

function stopTimer() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
}

function updateTimer() {
  if (!pickStartTime) return;
  const elapsed = Math.floor((Date.now() - pickStartTime) / 1000);
  const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  timerEl.textContent = `${m}:${s}`;
}

// ── Audio feedback ────────────────────────────────────────────────────────────
let _audioCtx = null;
function playBeep(freq, gain) {
  try {
    if (!_audioCtx) _audioCtx = new AudioContext();
    const osc = _audioCtx.createOscillator();
    const vol = _audioCtx.createGain();
    osc.connect(vol);
    vol.connect(_audioCtx.destination);
    osc.frequency.value = freq;
    vol.gain.setValueAtTime(gain, _audioCtx.currentTime);
    vol.gain.exponentialRampToValueAtTime(0.001, _audioCtx.currentTime + 0.4);
    osc.start();
    osc.stop(_audioCtx.currentTime + 0.4);
  } catch (_) { /* audio blocked by browser policy — silently ignore */ }
}

// ── Canvas rendering ──────────────────────────────────────────────────────────
function clearCanvas() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function drawDetections(detections, activeOrder) {
  resizeCanvas();
  clearCanvas();

  const scaleX = canvas.width  / SRC_W;
  const scaleY = canvas.height / SRC_H;

  for (const det of detections) {
    const [x1, y1, x2, y2] = det.bbox;
    const sx = x1 * scaleX;
    const sy = y1 * scaleY;
    const sw = (x2 - x1) * scaleX;
    const sh = (y2 - y1) * scaleY;

    const isTarget = activeOrder && det.sku === activeOrder.sku;
    const colour   = isTarget ? COL_TARGET : COL_OTHER;
    const lineW    = isTarget ? 3 : 1.5;

    // Bounding box
    ctx.strokeStyle = colour;
    ctx.lineWidth   = lineW;
    if (isTarget) {
      // Pulsing glow
      ctx.shadowColor = COL_TARGET;
      ctx.shadowBlur  = 12;
    } else {
      ctx.shadowBlur = 0;
    }
    ctx.strokeRect(sx, sy, sw, sh);
    ctx.shadowBlur = 0;

    // Label background
    const label    = isTarget ? `▶ PICK THIS  ${det.sku}` : det.sku;
    const fontSize = isTarget ? 14 : 11;
    ctx.font       = `bold ${fontSize}px monospace`;
    const tw       = ctx.measureText(label).width + 8;
    const th       = fontSize + 6;
    ctx.fillStyle  = isTarget ? 'rgba(255,215,0,0.85)' : 'rgba(74,158,255,0.75)';
    ctx.fillRect(sx, sy - th, tw, th);

    // Label text
    ctx.fillStyle = isTarget ? '#000' : '#fff';
    ctx.fillText(label, sx + 4, sy - 4);

    // Arrow pointer for target
    if (isTarget) {
      ctx.fillStyle  = COL_TARGET;
      ctx.font       = 'bold 20px sans-serif';
      ctx.fillText('→', sx - 28, sy + sh / 2 + 8);
    }
  }
}

// ── Order bar update ──────────────────────────────────────────────────────────
function updateOrderBar(order) {
  if (!order) {
    orderIdEl.textContent = '—';
    skuEl.textContent     = '—';
    skuDescEl.textContent = 'Waiting for order';
    qtyEl.textContent     = '—';
    return;
  }
  orderIdEl.textContent = `ORDER ${order.order_id}`;
  skuEl.textContent     = order.sku;
  skuDescEl.textContent = order.sku.replace(/-/g, ' ').toLowerCase();
  qtyEl.textContent     = `× ${order.qty}`;
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connect() {
  wsStatusEl.textContent = 'Connecting…';
  liveDot.className = 'dot-offline';
  liveDot.textContent = '● CONNECTING';

  const ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    wsStatusEl.textContent = 'Connected';
    liveDot.className = 'dot-live';
    liveDot.textContent = '● LIVE';
    // Send heartbeats every 5s to keep connection alive
    const hb = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
      else clearInterval(hb);
    }, 5000);
  };

  ws.onmessage = (evt) => {
    let msg;
    try { msg = JSON.parse(evt.data); } catch (_) { return; }

    const { status, detections = [], active_order } = msg;

    updateOrderBar(active_order);

    if (status === 'waiting') {
      if (currentState !== 'correct' && currentState !== 'wrong') {
        setState('waiting');
      }
      clearCanvas();
    } else if (status === 'active') {
      if (currentState === 'waiting') setState('active');
      drawDetections(detections, active_order);
    } else if (status === 'confirming') {
      // result is "correct" | "wrong" | "short" — sent by the server after PickVerifier runs
      if (msg.result === 'wrong' || msg.result === 'short') {
        setState('wrong');
      } else {
        setState('correct');
      }
      clearCanvas();
    }
  };

  ws.onclose = () => {
    wsStatusEl.textContent = 'Disconnected — retrying…';
    liveDot.className = 'dot-offline';
    liveDot.textContent = '● OFFLINE';
    setState('waiting');
    setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();
}

connect();
```

- [ ] **Step 2: Commit**

```bash
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant add vlm_vision/overlay/bay.js
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant commit -m "feat: vlm-overlay WebSocket + canvas bounding box renderer"
```

---

## Task 6: Verify End-to-End (Manual)

No automated test — verify manually with the server running.

- [ ] **Step 1: Start the server with test env vars**

```bash
cd vlm_vision && \
MODEL_PATH=models/metwall.onnx \
CAMERA_BAY1=0 \
CAMERA_BAY2=1 \
MODULA_WMS_URL=http://localhost:9999 \
CLOUD_SYNC_URL=http://localhost:9999 \
DB_PATH=/tmp/picks.db \
python3 -m local_agent.main
```

Expected: uvicorn starts on port 8765

- [ ] **Step 2: Open the overlay in a browser**

Open: `http://localhost:8765/bay.html?bay=1`

Expected:
- Top bar shows "BAY 1" in blue, "● CONNECTING" → "● LIVE" once WebSocket connects
- Camera area shows spinner with "Waiting for tray…"
- Status bar shows "Connecting…" → "Connected"

- [ ] **Step 3: Run all automated tests one final time**

```bash
cd vlm_vision && python3 -m pytest tests/ -v --tb=short
```

Expected: 26 passed (18 plan-1 + 5 frame-store + 3 display-server)

- [ ] **Step 4: Final commit**

```bash
git -C /Users/alfonsomendez/Documents/Dhar/email_ai_assistant commit --allow-empty -m "chore: vlm-overlay plan 2 complete — 26 tests passing"
```
