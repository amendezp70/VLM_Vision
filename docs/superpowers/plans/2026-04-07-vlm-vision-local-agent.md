# VLM Vision — Local PC Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the on-site Python application that captures camera frames from both Modula VLM bays, detects parts using YOLOv8 ONNX, verifies picks, and serves a WebSocket feed to the display overlay.

**Architecture:** A multi-threaded Python application with one camera thread per bay feeding a shared detection pipeline. A FastAPI WebSocket server broadcasts per-bay detection state to browser overlay clients. An SQLite offline queue buffers confirmed pick events when the cloud is unreachable.

**Tech Stack:** Python 3.11, OpenCV 4.x, Ultralytics YOLOv8 / ONNX Runtime, FastAPI, uvicorn, SQLite (stdlib), httpx (Modula WMS client), pytest, Docker Compose

---

## File Structure

```
vlm_vision/
├── local_agent/
│   ├── __init__.py
│   ├── config.py           # Typed config dataclass; loaded from env vars
│   ├── models.py           # Shared dataclasses: Detection, PickOrder, PickEvent, BayStatus
│   ├── detector.py         # YOLOv8 ONNX inference wrapper; returns List[Detection]
│   ├── camera_agent.py     # OpenCV capture loop; puts frames onto a per-bay Queue
│   ├── pick_verifier.py    # Diffs before/after Detection lists; emits PickEvent
│   ├── offline_queue.py    # SQLite store for PickEvent; tracks sync status
│   ├── modula_client.py    # HTTP client for Modula WMS pick orders
│   ├── display_server.py   # FastAPI WebSocket server; pushes bay state to overlays
│   └── main.py             # Wires all components; runs event loop
├── tests/
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_detector.py
│   ├── test_pick_verifier.py
│   ├── test_offline_queue.py
│   └── test_modula_client.py
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Task 1: Project Setup, Requirements, and Shared Models

**Files:**
- Create: `vlm_vision/requirements.txt`
- Create: `vlm_vision/local_agent/__init__.py`
- Create: `vlm_vision/local_agent/models.py`
- Create: `vlm_vision/tests/conftest.py`
- Test: `vlm_vision/tests/test_models.py`

- [ ] **Step 1: Create the project directory structure**

```bash
mkdir -p vlm_vision/local_agent vlm_vision/tests
touch vlm_vision/local_agent/__init__.py vlm_vision/tests/__init__.py
```

- [ ] **Step 2: Write requirements.txt**

```
# vlm_vision/requirements.txt
opencv-python==4.9.0.80
ultralytics==8.2.0
onnxruntime==1.17.3
fastapi==0.111.0
uvicorn[standard]==0.29.0
httpx==0.27.0
pytest==8.2.0
pytest-asyncio==0.23.6
```

- [ ] **Step 3: Write the failing test for models**

```python
# vlm_vision/tests/test_models.py
from local_agent.models import Detection, PickOrder, PickEvent, BayStatus

def test_detection_fields():
    d = Detection(sku="STL-P-100-BK", color="black", confidence=0.97,
                  bbox=(10, 20, 100, 80))
    assert d.sku == "STL-P-100-BK"
    assert d.color == "black"
    assert d.confidence == 0.97
    assert d.bbox == (10, 20, 100, 80)

def test_pick_order_fields():
    o = PickOrder(order_id="PO-001", sku="STL-P-100-BK", qty=2, tray_id="T-042")
    assert o.order_id == "PO-001"
    assert o.qty == 2

def test_pick_event_result_values():
    e = PickEvent(order_id="PO-001", sku="STL-P-100-BK", qty_picked=1,
                  bay_id=1, worker_id="jmartinez", result="correct",
                  timestamp=1712500000.0)
    assert e.result in ("correct", "wrong", "short")

def test_bay_status_values():
    assert BayStatus.WAITING != BayStatus.ACTIVE
    assert BayStatus.ACTIVE != BayStatus.CONFIRMING
```

- [ ] **Step 4: Run test to confirm it fails**

```bash
cd vlm_vision && python -m pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'local_agent.models'`

- [ ] **Step 5: Implement models.py**

```python
# vlm_vision/local_agent/models.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple


class BayStatus(Enum):
    WAITING = "waiting"
    ACTIVE = "active"
    CONFIRMING = "confirming"


@dataclass
class Detection:
    sku: str
    color: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2


@dataclass
class PickOrder:
    order_id: str
    sku: str
    qty: int
    tray_id: str


@dataclass
class PickEvent:
    order_id: str
    sku: str
    qty_picked: int
    bay_id: int
    worker_id: str
    result: str  # "correct" | "wrong" | "short"
    timestamp: float
    synced: bool = False
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
cd vlm_vision && python -m pytest tests/test_models.py -v
```

Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add vlm_vision/
git commit -m "feat: vlm-agent project scaffold and shared models"
```

---

## Task 2: Configuration

**Files:**
- Create: `vlm_vision/local_agent/config.py`

- [ ] **Step 1: Write the failing test**

```python
# vlm_vision/tests/test_models.py  (append to existing file)
import os
from local_agent.config import Config

def test_config_defaults():
    os.environ.setdefault("MODEL_PATH", "models/metwall.onnx")
    os.environ.setdefault("CAMERA_BAY1", "0")
    os.environ.setdefault("CAMERA_BAY2", "1")
    os.environ.setdefault("MODULA_WMS_URL", "http://modula-wms.local:8080")
    os.environ.setdefault("CLOUD_SYNC_URL", "https://catalyst.zoho.com/baas/v1/project/123")
    c = Config.from_env()
    assert c.model_path == "models/metwall.onnx"
    assert c.camera_ids == [0, 1]
    assert c.modula_wms_url == "http://modula-wms.local:8080"
    assert c.detection_fps == 10
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd vlm_vision && python -m pytest tests/test_models.py::test_config_defaults -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement config.py**

```python
# vlm_vision/local_agent/config.py
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    model_path: str
    camera_ids: List[int]
    modula_wms_url: str
    cloud_sync_url: str
    detection_fps: int = 10
    websocket_port: int = 8765
    db_path: str = "picks.db"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            model_path=os.environ["MODEL_PATH"],
            camera_ids=[
                int(os.environ.get("CAMERA_BAY1", "0")),
                int(os.environ.get("CAMERA_BAY2", "1")),
            ],
            modula_wms_url=os.environ["MODULA_WMS_URL"],
            cloud_sync_url=os.environ["CLOUD_SYNC_URL"],
            detection_fps=int(os.environ.get("DETECTION_FPS", "10")),
            websocket_port=int(os.environ.get("WEBSOCKET_PORT", "8765")),
            db_path=os.environ.get("DB_PATH", "picks.db"),
        )
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd vlm_vision && python -m pytest tests/test_models.py::test_config_defaults -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/local_agent/config.py vlm_vision/tests/test_models.py
git commit -m "feat: vlm-agent typed config from env vars"
```

---

## Task 3: SQLite Offline Queue

**Files:**
- Create: `vlm_vision/local_agent/offline_queue.py`
- Test: `vlm_vision/tests/test_offline_queue.py`

- [ ] **Step 1: Write the failing tests**

```python
# vlm_vision/tests/test_offline_queue.py
import os
import pytest
from local_agent.offline_queue import OfflineQueue
from local_agent.models import PickEvent

@pytest.fixture
def queue(tmp_path):
    db = str(tmp_path / "test_picks.db")
    q = OfflineQueue(db_path=db)
    yield q
    q.close()

def make_event(order_id="PO-001", result="correct") -> PickEvent:
    return PickEvent(order_id=order_id, sku="STL-P-100-BK", qty_picked=1,
                     bay_id=1, worker_id="jmartinez", result=result,
                     timestamp=1712500000.0)

def test_enqueue_and_count(queue):
    queue.enqueue(make_event())
    assert queue.unsynced_count() == 1

def test_enqueue_multiple(queue):
    queue.enqueue(make_event("PO-001"))
    queue.enqueue(make_event("PO-002"))
    assert queue.unsynced_count() == 2

def test_fetch_unsynced(queue):
    queue.enqueue(make_event("PO-001"))
    events = queue.fetch_unsynced(limit=10)
    assert len(events) == 1
    assert events[0].order_id == "PO-001"

def test_mark_synced(queue):
    queue.enqueue(make_event("PO-001"))
    queue.enqueue(make_event("PO-002"))
    events = queue.fetch_unsynced(limit=10)
    queue.mark_synced([e.order_id for e in events])
    assert queue.unsynced_count() == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd vlm_vision && python -m pytest tests/test_offline_queue.py -v
```

Expected: `ImportError: cannot import name 'OfflineQueue'`

- [ ] **Step 3: Implement offline_queue.py**

```python
# vlm_vision/local_agent/offline_queue.py
import json
import sqlite3
from typing import List
from local_agent.models import PickEvent


class OfflineQueue:
    def __init__(self, db_path: str = "picks.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_table()

    def _create_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS pick_events (
                order_id TEXT NOT NULL,
                payload  TEXT NOT NULL,
                synced   INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.commit()

    def enqueue(self, event: PickEvent) -> None:
        payload = json.dumps({
            "order_id": event.order_id,
            "sku": event.sku,
            "qty_picked": event.qty_picked,
            "bay_id": event.bay_id,
            "worker_id": event.worker_id,
            "result": event.result,
            "timestamp": event.timestamp,
        })
        self._conn.execute(
            "INSERT INTO pick_events (order_id, payload, synced) VALUES (?, ?, 0)",
            (event.order_id, payload),
        )
        self._conn.commit()

    def fetch_unsynced(self, limit: int = 50) -> List[PickEvent]:
        rows = self._conn.execute(
            "SELECT payload FROM pick_events WHERE synced = 0 LIMIT ?", (limit,)
        ).fetchall()
        events = []
        for (payload,) in rows:
            data = json.loads(payload)
            events.append(PickEvent(**data))
        return events

    def mark_synced(self, order_ids: List[str]) -> None:
        self._conn.executemany(
            "UPDATE pick_events SET synced = 1 WHERE order_id = ?",
            [(oid,) for oid in order_ids],
        )
        self._conn.commit()

    def unsynced_count(self) -> int:
        (count,) = self._conn.execute(
            "SELECT COUNT(*) FROM pick_events WHERE synced = 0"
        ).fetchone()
        return count

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd vlm_vision && python -m pytest tests/test_offline_queue.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/local_agent/offline_queue.py vlm_vision/tests/test_offline_queue.py
git commit -m "feat: vlm-agent SQLite offline pick queue"
```

---

## Task 4: YOLO Detector Wrapper

**Files:**
- Create: `vlm_vision/local_agent/detector.py`
- Test: `vlm_vision/tests/test_detector.py`

- [ ] **Step 1: Write the failing tests**

```python
# vlm_vision/tests/test_detector.py
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
from local_agent.detector import Detector
from local_agent.models import Detection


def make_mock_result():
    """Simulate a YOLOv8 result with one detection."""
    box = MagicMock()
    box.xyxy = [[10.0, 20.0, 110.0, 80.0]]
    box.conf = [0.94]
    box.cls = [0]  # class index 0

    result = MagicMock()
    result.boxes = box
    result.names = {0: "STL-P-100-BK__black"}  # format: SKU__color
    return [result]


def test_detect_returns_list_of_detections():
    with patch("local_agent.detector.YOLO") as mock_yolo_cls:
        mock_model = MagicMock()
        mock_model.return_value = make_mock_result()
        mock_yolo_cls.return_value = mock_model

        detector = Detector(model_path="fake.onnx")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        results = detector.detect(frame)

    assert len(results) == 1
    assert isinstance(results[0], Detection)
    assert results[0].sku == "STL-P-100-BK"
    assert results[0].color == "black"
    assert results[0].confidence == pytest.approx(0.94, abs=0.01)
    assert results[0].bbox == (10, 20, 110, 80)


def test_detect_returns_empty_on_no_detections():
    with patch("local_agent.detector.YOLO") as mock_yolo_cls:
        mock_model = MagicMock()
        empty_result = MagicMock()
        empty_result.boxes.xyxy = []
        empty_result.boxes.conf = []
        empty_result.boxes.cls = []
        empty_result.names = {}
        mock_model.return_value = [empty_result]
        mock_yolo_cls.return_value = mock_model

        detector = Detector(model_path="fake.onnx")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        results = detector.detect(frame)

    assert results == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd vlm_vision && python -m pytest tests/test_detector.py -v
```

Expected: `ImportError: cannot import name 'Detector'`

- [ ] **Step 3: Implement detector.py**

```python
# vlm_vision/local_agent/detector.py
"""
Wraps YOLOv8 ONNX inference.

Class names in the model must follow the format  SKU__color
e.g. "STL-P-100-BK__black", "ALUM-P-60-SL__silver"
"""
import numpy as np
from typing import List
from ultralytics import YOLO
from local_agent.models import Detection


class Detector:
    def __init__(self, model_path: str):
        self._model = YOLO(model_path)

    def detect(self, frame: np.ndarray) -> List[Detection]:
        results = self._model(frame, verbose=False)
        detections: List[Detection] = []

        for result in results:
            boxes = result.boxes
            names = result.names
            for i, xyxy in enumerate(boxes.xyxy):
                if i >= len(boxes.conf):
                    break
                cls_idx = int(boxes.cls[i])
                raw_name = names.get(cls_idx, "__")
                parts = raw_name.split("__", 1)
                sku = parts[0]
                color = parts[1] if len(parts) > 1 else "unknown"

                x1, y1, x2, y2 = (int(v) for v in xyxy)
                detections.append(Detection(
                    sku=sku,
                    color=color,
                    confidence=float(boxes.conf[i]),
                    bbox=(x1, y1, x2, y2),
                ))

        return detections
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd vlm_vision && python -m pytest tests/test_detector.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/local_agent/detector.py vlm_vision/tests/test_detector.py
git commit -m "feat: vlm-agent YOLOv8 ONNX detector wrapper"
```

---

## Task 5: Pick Verifier

**Files:**
- Create: `vlm_vision/local_agent/pick_verifier.py`
- Test: `vlm_vision/tests/test_pick_verifier.py`

- [ ] **Step 1: Write the failing tests**

```python
# vlm_vision/tests/test_pick_verifier.py
import time
import pytest
from local_agent.pick_verifier import PickVerifier
from local_agent.models import Detection, PickOrder, PickEvent


def det(sku, color="black", count=1):
    return [Detection(sku=sku, color=color, confidence=0.95,
                      bbox=(0, 0, 10, 10)) for _ in range(count)]


def test_correct_pick_detected():
    order = PickOrder(order_id="PO-001", sku="STL-P-100-BK", qty=1, tray_id="T-01")
    verifier = PickVerifier(bay_id=1, worker_id="jmartinez")

    before = det("STL-P-100-BK", count=3) + det("SCREW-M5-12", count=5)
    after  = det("STL-P-100-BK", count=2) + det("SCREW-M5-12", count=5)

    event = verifier.verify(order=order, before=before, after=after)

    assert event is not None
    assert event.result == "correct"
    assert event.sku == "STL-P-100-BK"
    assert event.qty_picked == 1
    assert event.order_id == "PO-001"


def test_wrong_pick_detected():
    order = PickOrder(order_id="PO-002", sku="STL-P-100-BK", qty=1, tray_id="T-01")
    verifier = PickVerifier(bay_id=1, worker_id="jmartinez")

    before = det("STL-P-100-BK", count=3) + det("ALUM-P-100-BK", count=2)
    after  = det("STL-P-100-BK", count=3) + det("ALUM-P-100-BK", count=1)

    event = verifier.verify(order=order, before=before, after=after)

    assert event is not None
    assert event.result == "wrong"
    assert event.sku == "ALUM-P-100-BK"


def test_no_pick_returns_none():
    order = PickOrder(order_id="PO-003", sku="STL-P-100-BK", qty=1, tray_id="T-01")
    verifier = PickVerifier(bay_id=1, worker_id="jmartinez")

    before = det("STL-P-100-BK", count=3)
    after  = det("STL-P-100-BK", count=3)  # nothing changed

    event = verifier.verify(order=order, before=before, after=after)
    assert event is None


def test_short_pick_detected():
    order = PickOrder(order_id="PO-004", sku="STL-P-100-BK", qty=2, tray_id="T-01")
    verifier = PickVerifier(bay_id=1, worker_id="jmartinez")

    before = det("STL-P-100-BK", count=3)
    after  = det("STL-P-100-BK", count=2)  # picked 1 but needed 2

    event = verifier.verify(order=order, before=before, after=after)

    assert event is not None
    assert event.result == "short"
    assert event.qty_picked == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd vlm_vision && python -m pytest tests/test_pick_verifier.py -v
```

Expected: `ImportError: cannot import name 'PickVerifier'`

- [ ] **Step 3: Implement pick_verifier.py**

```python
# vlm_vision/local_agent/pick_verifier.py
import time
from typing import List, Optional, Dict
from local_agent.models import Detection, PickOrder, PickEvent


def _count_by_sku(detections: List[Detection]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for d in detections:
        counts[d.sku] = counts.get(d.sku, 0) + 1
    return counts


class PickVerifier:
    def __init__(self, bay_id: int, worker_id: str):
        self.bay_id = bay_id
        self.worker_id = worker_id

    def verify(
        self,
        order: PickOrder,
        before: List[Detection],
        after: List[Detection],
    ) -> Optional[PickEvent]:
        before_counts = _count_by_sku(before)
        after_counts = _count_by_sku(after)

        # Find which SKU decreased
        removed: Dict[str, int] = {}
        for sku, count in before_counts.items():
            after_count = after_counts.get(sku, 0)
            if after_count < count:
                removed[sku] = count - after_count

        if not removed:
            return None

        # Check if correct SKU was removed
        if order.sku in removed:
            qty_picked = removed[order.sku]
            if qty_picked >= order.qty:
                result = "correct"
            else:
                result = "short"
            picked_sku = order.sku
        else:
            # Wrong part picked — report the first removed SKU
            picked_sku = next(iter(removed))
            qty_picked = removed[picked_sku]
            result = "wrong"

        return PickEvent(
            order_id=order.order_id,
            sku=picked_sku,
            qty_picked=qty_picked,
            bay_id=self.bay_id,
            worker_id=self.worker_id,
            result=result,
            timestamp=time.time(),
        )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd vlm_vision && python -m pytest tests/test_pick_verifier.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/local_agent/pick_verifier.py vlm_vision/tests/test_pick_verifier.py
git commit -m "feat: vlm-agent pick verifier with correct/wrong/short detection"
```

---

## Task 6: Modula WMS Client

**Files:**
- Create: `vlm_vision/local_agent/modula_client.py`
- Test: `vlm_vision/tests/test_modula_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# vlm_vision/tests/test_modula_client.py
import pytest
import httpx
from unittest.mock import patch, MagicMock
from local_agent.modula_client import ModulaClient
from local_agent.models import PickOrder


BASE_URL = "http://modula-wms.local:8080"


def test_fetch_active_order_returns_pick_order():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "order_id": "PO-2847",
        "sku": "STL-P-100-BK",
        "qty": 2,
        "tray_id": "T-0042",
    }

    with patch("local_agent.modula_client.httpx.get", return_value=mock_response):
        client = ModulaClient(base_url=BASE_URL)
        order = client.fetch_active_order(bay_id=1)

    assert isinstance(order, PickOrder)
    assert order.order_id == "PO-2847"
    assert order.sku == "STL-P-100-BK"
    assert order.qty == 2
    assert order.tray_id == "T-0042"


def test_fetch_active_order_returns_none_when_no_order():
    mock_response = MagicMock()
    mock_response.status_code = 204

    with patch("local_agent.modula_client.httpx.get", return_value=mock_response):
        client = ModulaClient(base_url=BASE_URL)
        order = client.fetch_active_order(bay_id=1)

    assert order is None


def test_confirm_pick_calls_correct_endpoint():
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("local_agent.modula_client.httpx.post", return_value=mock_response) as mock_post:
        client = ModulaClient(base_url=BASE_URL)
        client.confirm_pick(order_id="PO-2847", result="correct")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "PO-2847" in str(call_kwargs)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd vlm_vision && python -m pytest tests/test_modula_client.py -v
```

Expected: `ImportError: cannot import name 'ModulaClient'`

- [ ] **Step 3: Implement modula_client.py**

```python
# vlm_vision/local_agent/modula_client.py
import httpx
from typing import Optional
from local_agent.models import PickOrder


class ModulaClient:
    def __init__(self, base_url: str, timeout: int = 5):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def fetch_active_order(self, bay_id: int) -> Optional[PickOrder]:
        url = f"{self._base_url}/api/v1/bays/{bay_id}/active-order"
        response = httpx.get(url, timeout=self._timeout)
        if response.status_code == 204:
            return None
        response.raise_for_status()
        data = response.json()
        return PickOrder(
            order_id=data["order_id"],
            sku=data["sku"],
            qty=int(data["qty"]),
            tray_id=data["tray_id"],
        )

    def confirm_pick(self, order_id: str, result: str) -> None:
        url = f"{self._base_url}/api/v1/orders/{order_id}/confirm"
        response = httpx.post(
            url,
            json={"result": result},
            timeout=self._timeout,
        )
        response.raise_for_status()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd vlm_vision && python -m pytest tests/test_modula_client.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/local_agent/modula_client.py vlm_vision/tests/test_modula_client.py
git commit -m "feat: vlm-agent Modula WMS HTTP client"
```

---

## Task 7: Camera Agent

**Files:**
- Create: `vlm_vision/local_agent/camera_agent.py`

No unit test for camera capture (requires physical hardware). Integration tested manually in Task 9.

- [ ] **Step 1: Implement camera_agent.py**

```python
# vlm_vision/local_agent/camera_agent.py
"""
Captures frames from a single camera and puts them onto a Queue.
One CameraAgent instance per bay. Runs in its own thread.
"""
import threading
import time
import cv2
import numpy as np
from queue import Queue, Full
from typing import Optional


class CameraAgent(threading.Thread):
    def __init__(self, camera_id: int, frame_queue: Queue, fps: int = 10):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self._queue = frame_queue
        self._interval = 1.0 / fps
        self._stop_event = threading.Event()
        self._cap: Optional[cv2.VideoCapture] = None

    def run(self) -> None:
        self._cap = cv2.VideoCapture(self.camera_id)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)

        while not self._stop_event.is_set():
            start = time.monotonic()
            ok, frame = self._cap.read()
            if ok:
                try:
                    self._queue.put_nowait(frame)
                except Full:
                    # Drop oldest frame to keep queue fresh
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(frame)
                    except Exception:
                        pass
            elapsed = time.monotonic() - start
            sleep_for = self._interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def stop(self) -> None:
        self._stop_event.set()
        if self._cap:
            self._cap.release()
```

- [ ] **Step 2: Commit**

```bash
git add vlm_vision/local_agent/camera_agent.py
git commit -m "feat: vlm-agent threaded camera capture agent"
```

---

## Task 8: WebSocket Display Server

**Files:**
- Create: `vlm_vision/local_agent/display_server.py`

- [ ] **Step 1: Implement display_server.py**

```python
# vlm_vision/local_agent/display_server.py
"""
FastAPI WebSocket server. Each bay has its own endpoint.
The main loop calls broadcast() to push detection state to connected overlay clients.
"""
import json
import asyncio
from typing import Dict, List, Set
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
    active_order: PickOrder | None,
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
```

- [ ] **Step 2: Commit**

```bash
git add vlm_vision/local_agent/display_server.py
git commit -m "feat: vlm-agent FastAPI WebSocket display server"
```

---

## Task 9: Main Orchestrator

**Files:**
- Create: `vlm_vision/local_agent/main.py`

- [ ] **Step 1: Implement main.py**

```python
# vlm_vision/local_agent/main.py
"""
Entry point. Wires all components and runs the pick loop for each bay.
"""
import asyncio
import threading
import time
from queue import Queue

import uvicorn

from local_agent.camera_agent import CameraAgent
from local_agent.config import Config
from local_agent.detector import Detector
from local_agent.display_server import app, broadcast
from local_agent.models import BayStatus, PickOrder
from local_agent.modula_client import ModulaClient
from local_agent.offline_queue import OfflineQueue
from local_agent.pick_verifier import PickVerifier

FRAME_QUEUE_SIZE = 3
PICK_SETTLE_SECONDS = 1.5  # wait after motion stops before comparing before/after


def run_bay(
    bay_id: int,
    camera_id: int,
    config: Config,
    detector: Detector,
    modula: ModulaClient,
    queue: OfflineQueue,
    loop: asyncio.AbstractEventLoop,
):
    frame_queue: Queue = Queue(maxsize=FRAME_QUEUE_SIZE)
    camera = CameraAgent(camera_id=camera_id, frame_queue=frame_queue, fps=config.detection_fps)
    camera.start()
    verifier = PickVerifier(bay_id=bay_id, worker_id="operator")

    active_order: PickOrder | None = None

    while True:
        # Poll for active pick order
        try:
            active_order = modula.fetch_active_order(bay_id=bay_id)
        except Exception:
            pass  # network error — keep last known order

        if frame_queue.empty():
            time.sleep(0.05)
            continue

        frame = frame_queue.get()
        detections = detector.detect(frame)

        status = BayStatus.ACTIVE if active_order else BayStatus.WAITING
        asyncio.run_coroutine_threadsafe(
            broadcast(bay_id, status, detections, active_order), loop
        )

        if active_order is None:
            continue

        # Capture before snapshot, wait for pick, capture after snapshot
        before = detections
        time.sleep(PICK_SETTLE_SECONDS)

        if not frame_queue.empty():
            after_frame = frame_queue.get()
            after = detector.detect(after_frame)
            event = verifier.verify(order=active_order, before=before, after=after)

            if event:
                queue.enqueue(event)
                try:
                    modula.confirm_pick(order_id=event.order_id, result=event.result)
                except Exception:
                    pass  # queued locally; cloud sync handles retry
                asyncio.run_coroutine_threadsafe(
                    broadcast(bay_id, BayStatus.CONFIRMING, after, None), loop
                )
                active_order = None


def main():
    config = Config.from_env()
    detector = Detector(model_path=config.model_path)
    modula = ModulaClient(base_url=config.modula_wms_url)
    queue = OfflineQueue(db_path=config.db_path)

    loop = asyncio.new_event_loop()

    for i, camera_id in enumerate(config.camera_ids):
        bay_id = i + 1
        t = threading.Thread(
            target=run_bay,
            args=(bay_id, camera_id, config, detector, modula, queue, loop),
            daemon=True,
        )
        t.start()

    # Run FastAPI WebSocket server on the main thread's event loop
    asyncio.set_event_loop(loop)
    config_uvicorn = uvicorn.Config(
        app, host="0.0.0.0", port=config.websocket_port, loop="asyncio"
    )
    server = uvicorn.Server(config_uvicorn)
    loop.run_until_complete(server.serve())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run all tests to confirm nothing is broken**

```bash
cd vlm_vision && python -m pytest tests/ -v
```

Expected: all previous tests still pass

- [ ] **Step 3: Commit**

```bash
git add vlm_vision/local_agent/main.py
git commit -m "feat: vlm-agent main orchestrator wiring all components"
```

---

## Task 10: Docker Packaging

**Files:**
- Create: `vlm_vision/Dockerfile`
- Create: `vlm_vision/docker-compose.yml`
- Create: `vlm_vision/.env.example`

- [ ] **Step 1: Write Dockerfile**

```dockerfile
# vlm_vision/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY local_agent/ ./local_agent/

CMD ["python", "-m", "local_agent.main"]
```

- [ ] **Step 2: Write docker-compose.yml**

```yaml
# vlm_vision/docker-compose.yml
version: "3.9"

services:
  vlm-agent:
    build: .
    restart: unless-stopped
    devices:
      - /dev/video0:/dev/video0   # Bay 1 camera
      - /dev/video1:/dev/video1   # Bay 2 camera
    volumes:
      - ./models:/app/models      # ONNX model files
      - ./data:/app/data          # SQLite offline queue
    ports:
      - "8765:8765"               # WebSocket for display overlay
    env_file:
      - .env
```

- [ ] **Step 3: Write .env.example**

```bash
# vlm_vision/.env.example
MODEL_PATH=models/metwall.onnx
CAMERA_BAY1=0
CAMERA_BAY2=1
MODULA_WMS_URL=http://modula-wms.local:8080
CLOUD_SYNC_URL=https://catalyst.zoho.com/baas/v1/project/YOUR_PROJECT_ID
DETECTION_FPS=10
WEBSOCKET_PORT=8765
DB_PATH=data/picks.db
```

- [ ] **Step 4: Verify Docker build succeeds**

```bash
cd vlm_vision && docker build -t vlm-agent .
```

Expected: `Successfully built <image_id>`

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/Dockerfile vlm_vision/docker-compose.yml vlm_vision/.env.example
git commit -m "feat: vlm-agent Docker packaging and compose config"
```

---

## Task 11: Full Test Suite Run

- [ ] **Step 1: Install dependencies**

```bash
cd vlm_vision && pip install -r requirements.txt
```

- [ ] **Step 2: Run all tests**

```bash
cd vlm_vision && python -m pytest tests/ -v --tb=short
```

Expected output:
```
tests/test_models.py::test_detection_fields PASSED
tests/test_models.py::test_pick_order_fields PASSED
tests/test_models.py::test_pick_event_result_values PASSED
tests/test_models.py::test_bay_status_values PASSED
tests/test_models.py::test_config_defaults PASSED
tests/test_detector.py::test_detect_returns_list_of_detections PASSED
tests/test_detector.py::test_detect_returns_empty_on_no_detections PASSED
tests/test_pick_verifier.py::test_correct_pick_detected PASSED
tests/test_pick_verifier.py::test_wrong_pick_detected PASSED
tests/test_pick_verifier.py::test_no_pick_returns_none PASSED
tests/test_pick_verifier.py::test_short_pick_detected PASSED
tests/test_offline_queue.py::test_enqueue_and_count PASSED
tests/test_offline_queue.py::test_enqueue_multiple PASSED
tests/test_offline_queue.py::test_fetch_unsynced PASSED
tests/test_offline_queue.py::test_mark_synced PASSED
tests/test_modula_client.py::test_fetch_active_order_returns_pick_order PASSED
tests/test_modula_client.py::test_fetch_active_order_returns_none_when_no_order PASSED
tests/test_modula_client.py::test_confirm_pick_calls_correct_endpoint PASSED

18 passed
```

- [ ] **Step 3: Final commit**

```bash
git commit --allow-empty -m "chore: vlm-agent plan 1 complete — all 18 tests passing"
```
