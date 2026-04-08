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

# Serve overlay/ as static files at / (mounted after routes are defined)
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
