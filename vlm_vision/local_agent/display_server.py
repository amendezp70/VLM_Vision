# vlm_vision/local_agent/display_server.py
"""
FastAPI WebSocket server. Each bay has its own endpoint.
The main loop calls broadcast() to push detection state to connected overlay clients.
"""
import json
from typing import Dict, List, Set, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from local_agent.models import Detection, PickOrder, BayStatus


app = FastAPI()

# bay_id -> set of connected WebSocket clients
_connections: Dict[int, Set[WebSocket]] = {}


@app.websocket("/bay/{bay_id}")
async def bay_websocket(websocket: WebSocket, bay_id: int):
    await websocket.accept()
    _connections.setdefault(bay_id, set()).add(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep connection alive; client sends heartbeats
    except WebSocketDisconnect:
        _connections.get(bay_id, set()).discard(websocket)


async def broadcast(
    bay_id: int,
    status: BayStatus,
    detections: List[Detection],
    active_order: Optional[PickOrder],
) -> None:
    clients = _connections.get(bay_id, set())
    if not clients:
        return

    payload = json.dumps({
        "bay_id": bay_id,
        "status": status.value,
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
