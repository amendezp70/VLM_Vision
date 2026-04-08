# VLM Vision — Cloud Sync Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local PC's cloud sync subsystem — a background worker that pushes confirmed picks from the SQLite offline queue to Zoho Catalyst, and polls the Catalyst File Store for updated ONNX models.

**Architecture:** Three new modules. `CloudSyncClient` is a thin HTTP wrapper for Catalyst REST endpoints. `ModelRegistry` checks for new model versions and downloads them. `SyncWorker` ties both together in a daemon thread with configurable intervals. All three are pure-Python with no Catalyst SDK dependency — plain `requests` calls against documented REST endpoints.

**Tech Stack:** Python 3.11, requests, threading, pathlib, existing `OfflineQueue` and `Config`

---

## File Structure

```
vlm_vision/
├── local_agent/
│   ├── cloud_sync_client.py   # NEW: HTTP client for Catalyst pick sync + model download
│   ├── model_registry.py      # NEW: polls for model updates, downloads, hot-swaps detector
│   ├── sync_worker.py         # NEW: daemon thread driving periodic sync + model check
│   ├── config.py              # MODIFY: add model_dir, sync_interval_sec, model_poll_interval_sec
│   └── main.py                # MODIFY: start SyncWorker thread
└── tests/
    ├── test_cloud_sync_client.py  # Unit tests for CloudSyncClient
    ├── test_model_registry.py     # Unit tests for ModelRegistry
    └── test_sync_worker.py        # Unit tests for SyncWorker
```

**Dependency on Plans 1–2:** `Config`, `OfflineQueue`, `PickEvent`, and `Detector` must already exist.

---

## Task 1: Extend Config with sync settings

**Files:**
- Modify: `vlm_vision/local_agent/config.py`
- Modify: `vlm_vision/tests/test_models.py` (the existing `test_config_defaults` test)

- [ ] **Step 1: Write the failing test**

Add to the bottom of `vlm_vision/tests/test_models.py`:

```python
def test_config_sync_defaults():
    import os
    env = {
        "MODEL_PATH": "m.onnx",
        "MODULA_WMS_URL": "http://m",
        "CLOUD_SYNC_URL": "http://c",
    }
    for k, v in env.items():
        os.environ[k] = v
    cfg = Config.from_env()
    assert cfg.model_dir == "models"
    assert cfg.sync_interval_sec == 30
    assert cfg.model_poll_interval_sec == 3600
    for k in env:
        os.environ.pop(k, None)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd vlm_vision && python3 -m pytest tests/test_models.py::test_config_sync_defaults -v
```

Expected: `AttributeError: 'Config' object has no attribute 'model_dir'`

- [ ] **Step 3: Add three fields to Config**

In `vlm_vision/local_agent/config.py`, add the new fields to the dataclass and `from_env()`:

```python
import os
from dataclasses import dataclass
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
    model_dir: str = "models"
    sync_interval_sec: int = 30
    model_poll_interval_sec: int = 3600

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
            model_dir=os.environ.get("MODEL_DIR", "models"),
            sync_interval_sec=int(os.environ.get("SYNC_INTERVAL_SEC", "30")),
            model_poll_interval_sec=int(os.environ.get("MODEL_POLL_INTERVAL_SEC", "3600")),
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd vlm_vision && python3 -m pytest tests/test_models.py -v
```

Expected: all 6 tests pass (5 existing + 1 new)

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/local_agent/config.py vlm_vision/tests/test_models.py
git commit -m "feat: vlm-sync add model_dir, sync_interval, model_poll_interval to Config"
```

---

## Task 2: CloudSyncClient

**Files:**
- Create: `vlm_vision/local_agent/cloud_sync_client.py`
- Create: `vlm_vision/tests/test_cloud_sync_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# vlm_vision/tests/test_cloud_sync_client.py
import json
import pytest
from unittest.mock import patch, MagicMock
from local_agent.cloud_sync_client import CloudSyncClient
from local_agent.models import PickEvent


def make_event(order_id="PO-001", result="correct") -> PickEvent:
    return PickEvent(
        order_id=order_id, sku="STL-P-100-BK", qty_picked=1,
        bay_id=1, worker_id="jmartinez", result=result,
        timestamp=1712500000.0,
    )


@patch("local_agent.cloud_sync_client.requests.post")
def test_push_picks_sends_post_with_events(mock_post):
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
    client = CloudSyncClient(base_url="http://catalyst.example.com")

    events = [make_event("PO-001"), make_event("PO-002")]
    result = client.push_picks(events)

    assert result is True
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "/picks/sync" in call_args[0][0]
    body = call_args[1]["json"]
    assert len(body["events"]) == 2
    assert body["events"][0]["order_id"] == "PO-001"


@patch("local_agent.cloud_sync_client.requests.post")
def test_push_picks_returns_false_on_http_error(mock_post):
    mock_post.return_value = MagicMock(status_code=500)
    client = CloudSyncClient(base_url="http://catalyst.example.com")

    result = client.push_picks([make_event()])
    assert result is False


@patch("local_agent.cloud_sync_client.requests.post")
def test_push_picks_returns_false_on_network_error(mock_post):
    mock_post.side_effect = ConnectionError("offline")
    client = CloudSyncClient(base_url="http://catalyst.example.com")

    result = client.push_picks([make_event()])
    assert result is False


@patch("local_agent.cloud_sync_client.requests.post")
def test_push_picks_with_empty_list_is_noop(mock_post):
    client = CloudSyncClient(base_url="http://catalyst.example.com")
    result = client.push_picks([])
    assert result is True
    mock_post.assert_not_called()


@patch("local_agent.cloud_sync_client.requests.get")
def test_check_model_version_returns_version_string(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200, json=lambda: {"version": "v3", "url": "http://example.com/model.onnx"}
    )
    client = CloudSyncClient(base_url="http://catalyst.example.com")

    info = client.check_model_version()
    assert info["version"] == "v3"
    assert "url" in info


@patch("local_agent.cloud_sync_client.requests.get")
def test_check_model_version_returns_none_on_error(mock_get):
    mock_get.side_effect = ConnectionError("offline")
    client = CloudSyncClient(base_url="http://catalyst.example.com")

    info = client.check_model_version()
    assert info is None


@patch("local_agent.cloud_sync_client.requests.get")
def test_download_model_writes_file(mock_get, tmp_path):
    mock_get.return_value = MagicMock(
        status_code=200,
        iter_content=lambda chunk_size: [b"ONNX_DATA_CHUNK1", b"ONNX_DATA_CHUNK2"],
    )
    client = CloudSyncClient(base_url="http://catalyst.example.com")
    dest = tmp_path / "model.onnx"

    ok = client.download_model(url="http://example.com/model.onnx", dest=str(dest))
    assert ok is True
    assert dest.read_bytes() == b"ONNX_DATA_CHUNK1ONNX_DATA_CHUNK2"


@patch("local_agent.cloud_sync_client.requests.get")
def test_download_model_returns_false_on_error(mock_get, tmp_path):
    mock_get.side_effect = ConnectionError("offline")
    client = CloudSyncClient(base_url="http://catalyst.example.com")
    dest = tmp_path / "model.onnx"

    ok = client.download_model(url="http://example.com/model.onnx", dest=str(dest))
    assert ok is False
    assert not dest.exists()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd vlm_vision && python3 -m pytest tests/test_cloud_sync_client.py -v
```

Expected: `ImportError: cannot import name 'CloudSyncClient'`

- [ ] **Step 3: Implement cloud_sync_client.py**

```python
# vlm_vision/local_agent/cloud_sync_client.py
"""
HTTP client for Zoho Catalyst cloud endpoints.
Pushes confirmed pick events and checks for model updates.
"""
import logging
from typing import Dict, List, Optional

import requests

from local_agent.models import PickEvent

logger = logging.getLogger(__name__)


class CloudSyncClient:
    def __init__(self, base_url: str, timeout: int = 10) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def push_picks(self, events: List[PickEvent]) -> bool:
        """Push a batch of pick events to the cloud. Returns True on success."""
        if not events:
            return True
        payload = {
            "events": [
                {
                    "order_id": e.order_id,
                    "sku": e.sku,
                    "qty_picked": e.qty_picked,
                    "bay_id": e.bay_id,
                    "worker_id": e.worker_id,
                    "result": e.result,
                    "timestamp": e.timestamp,
                }
                for e in events
            ]
        }
        try:
            resp = requests.post(
                f"{self._base_url}/picks/sync",
                json=payload,
                timeout=self._timeout,
            )
            if resp.status_code == 200:
                return True
            logger.warning("Push picks failed: HTTP %d", resp.status_code)
            return False
        except Exception:
            logger.warning("Push picks failed: network error", exc_info=True)
            return False

    def check_model_version(self) -> Optional[Dict]:
        """Check cloud for latest model version. Returns {"version": ..., "url": ...} or None."""
        try:
            resp = requests.get(
                f"{self._base_url}/models/latest",
                timeout=self._timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            logger.debug("Model version check failed", exc_info=True)
            return None

    def download_model(self, url: str, dest: str) -> bool:
        """Download an ONNX model file to dest path. Returns True on success."""
        try:
            resp = requests.get(url, timeout=60, stream=True)
            if resp.status_code != 200:
                return False
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception:
            logger.warning("Model download failed", exc_info=True)
            return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd vlm_vision && python3 -m pytest tests/test_cloud_sync_client.py -v
```

Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/local_agent/cloud_sync_client.py vlm_vision/tests/test_cloud_sync_client.py
git commit -m "feat: vlm-sync CloudSyncClient HTTP client for Catalyst endpoints"
```

---

## Task 3: ModelRegistry

**Files:**
- Create: `vlm_vision/local_agent/model_registry.py`
- Create: `vlm_vision/tests/test_model_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
# vlm_vision/tests/test_model_registry.py
import os
import pytest
from unittest.mock import MagicMock, patch, call
from local_agent.model_registry import ModelRegistry


@pytest.fixture
def registry(tmp_path):
    client = MagicMock()
    return ModelRegistry(
        cloud_client=client,
        model_dir=str(tmp_path),
        current_model_path=str(tmp_path / "current.onnx"),
    )


def test_no_update_when_cloud_returns_none(registry):
    registry._client.check_model_version.return_value = None
    result = registry.check_and_update()
    assert result is None
    registry._client.download_model.assert_not_called()


def test_no_update_when_version_matches(registry):
    registry._current_version = "v3"
    registry._client.check_model_version.return_value = {"version": "v3", "url": "http://x/m.onnx"}
    result = registry.check_and_update()
    assert result is None
    registry._client.download_model.assert_not_called()


def test_downloads_new_model_when_version_differs(registry):
    registry._current_version = "v2"
    registry._client.check_model_version.return_value = {"version": "v3", "url": "http://x/m.onnx"}
    registry._client.download_model.return_value = True

    result = registry.check_and_update()

    assert result is not None
    assert result.endswith(".onnx")
    registry._client.download_model.assert_called_once()
    assert registry._current_version == "v3"


def test_returns_none_when_download_fails(registry):
    registry._current_version = "v2"
    registry._client.check_model_version.return_value = {"version": "v3", "url": "http://x/m.onnx"}
    registry._client.download_model.return_value = False

    result = registry.check_and_update()

    assert result is None
    # version stays at v2 since download failed
    assert registry._current_version == "v2"


def test_first_check_with_no_prior_version(registry):
    registry._current_version = None
    registry._client.check_model_version.return_value = {"version": "v1", "url": "http://x/m.onnx"}
    registry._client.download_model.return_value = True

    result = registry.check_and_update()

    assert result is not None
    assert registry._current_version == "v1"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd vlm_vision && python3 -m pytest tests/test_model_registry.py -v
```

Expected: `ImportError: cannot import name 'ModelRegistry'`

- [ ] **Step 3: Implement model_registry.py**

```python
# vlm_vision/local_agent/model_registry.py
"""
Polls the cloud for model updates and downloads new ONNX files.
Does NOT load the model — returns the new file path so the caller can hot-swap.
"""
import logging
import os
from typing import Optional

from local_agent.cloud_sync_client import CloudSyncClient

logger = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(
        self,
        cloud_client: CloudSyncClient,
        model_dir: str,
        current_model_path: str,
    ) -> None:
        self._client = cloud_client
        self._model_dir = model_dir
        self._current_model_path = current_model_path
        self._current_version: Optional[str] = None
        os.makedirs(model_dir, exist_ok=True)

    def check_and_update(self) -> Optional[str]:
        """Check cloud for a new model version.

        Returns:
            Path to the newly downloaded ONNX file if updated, else None.
        """
        info = self._client.check_model_version()
        if info is None:
            return None

        version = info.get("version")
        url = info.get("url")
        if not version or not url:
            return None

        if version == self._current_version:
            logger.debug("Model version %s is current", version)
            return None

        dest = os.path.join(self._model_dir, f"model_{version}.onnx")
        logger.info("Downloading model %s from %s", version, url)

        if self._client.download_model(url=url, dest=dest):
            self._current_version = version
            self._current_model_path = dest
            logger.info("Model updated to %s at %s", version, dest)
            return dest

        logger.warning("Model download failed for %s", version)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd vlm_vision && python3 -m pytest tests/test_model_registry.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/local_agent/model_registry.py vlm_vision/tests/test_model_registry.py
git commit -m "feat: vlm-sync ModelRegistry polls cloud for ONNX model updates"
```

---

## Task 4: SyncWorker

**Files:**
- Create: `vlm_vision/local_agent/sync_worker.py`
- Create: `vlm_vision/tests/test_sync_worker.py`

- [ ] **Step 1: Write the failing tests**

```python
# vlm_vision/tests/test_sync_worker.py
import threading
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from local_agent.sync_worker import SyncWorker
from local_agent.models import PickEvent


def make_event(order_id="PO-001") -> PickEvent:
    return PickEvent(
        order_id=order_id, sku="STL-P-100-BK", qty_picked=1,
        bay_id=1, worker_id="jmartinez", result="correct",
        timestamp=1712500000.0,
    )


def test_sync_picks_drains_queue():
    queue = MagicMock()
    client = MagicMock()
    registry = MagicMock()
    events = [make_event("PO-001"), make_event("PO-002")]
    queue.fetch_unsynced.return_value = events
    client.push_picks.return_value = True

    worker = SyncWorker(
        queue=queue, cloud_client=client, model_registry=registry,
        sync_interval=60, model_poll_interval=3600,
    )
    worker._sync_picks()

    queue.fetch_unsynced.assert_called_once()
    client.push_picks.assert_called_once_with(events)
    queue.mark_synced.assert_called_once_with(["PO-001", "PO-002"])


def test_sync_picks_does_not_mark_synced_on_failure():
    queue = MagicMock()
    client = MagicMock()
    registry = MagicMock()
    queue.fetch_unsynced.return_value = [make_event()]
    client.push_picks.return_value = False

    worker = SyncWorker(
        queue=queue, cloud_client=client, model_registry=registry,
        sync_interval=60, model_poll_interval=3600,
    )
    worker._sync_picks()

    queue.mark_synced.assert_not_called()


def test_sync_picks_skips_when_queue_empty():
    queue = MagicMock()
    client = MagicMock()
    registry = MagicMock()
    queue.fetch_unsynced.return_value = []

    worker = SyncWorker(
        queue=queue, cloud_client=client, model_registry=registry,
        sync_interval=60, model_poll_interval=3600,
    )
    worker._sync_picks()

    client.push_picks.assert_not_called()
    queue.mark_synced.assert_not_called()


def test_check_model_calls_registry():
    queue = MagicMock()
    client = MagicMock()
    registry = MagicMock()
    registry.check_and_update.return_value = "/models/model_v3.onnx"
    on_model = MagicMock()

    worker = SyncWorker(
        queue=queue, cloud_client=client, model_registry=registry,
        sync_interval=60, model_poll_interval=3600,
        on_model_updated=on_model,
    )
    worker._check_model()

    registry.check_and_update.assert_called_once()
    on_model.assert_called_once_with("/models/model_v3.onnx")


def test_check_model_no_callback_when_no_update():
    queue = MagicMock()
    client = MagicMock()
    registry = MagicMock()
    registry.check_and_update.return_value = None
    on_model = MagicMock()

    worker = SyncWorker(
        queue=queue, cloud_client=client, model_registry=registry,
        sync_interval=60, model_poll_interval=3600,
        on_model_updated=on_model,
    )
    worker._check_model()

    on_model.assert_not_called()


def test_start_and_stop():
    queue = MagicMock()
    client = MagicMock()
    registry = MagicMock()
    queue.fetch_unsynced.return_value = []
    registry.check_and_update.return_value = None

    worker = SyncWorker(
        queue=queue, cloud_client=client, model_registry=registry,
        sync_interval=0.05, model_poll_interval=0.05,
    )
    worker.start()
    assert worker.is_alive()

    time.sleep(0.15)
    worker.stop()
    worker.join(timeout=2)
    assert not worker.is_alive()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd vlm_vision && python3 -m pytest tests/test_sync_worker.py -v
```

Expected: `ImportError: cannot import name 'SyncWorker'`

- [ ] **Step 3: Implement sync_worker.py**

```python
# vlm_vision/local_agent/sync_worker.py
"""
Background daemon thread that periodically:
  1. Drains unsynced picks from OfflineQueue → pushes to Catalyst
  2. Polls ModelRegistry for ONNX model updates
"""
import logging
import threading
import time
from typing import Callable, Optional

from local_agent.cloud_sync_client import CloudSyncClient
from local_agent.model_registry import ModelRegistry
from local_agent.offline_queue import OfflineQueue

logger = logging.getLogger(__name__)


class SyncWorker(threading.Thread):
    def __init__(
        self,
        queue: OfflineQueue,
        cloud_client: CloudSyncClient,
        model_registry: ModelRegistry,
        sync_interval: float = 30,
        model_poll_interval: float = 3600,
        on_model_updated: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(daemon=True, name="sync-worker")
        self._queue = queue
        self._client = cloud_client
        self._registry = model_registry
        self._sync_interval = sync_interval
        self._model_poll_interval = model_poll_interval
        self._on_model_updated = on_model_updated
        self._stop_event = threading.Event()

    def run(self) -> None:
        last_model_check = 0.0
        while not self._stop_event.is_set():
            self._sync_picks()

            now = time.monotonic()
            if now - last_model_check >= self._model_poll_interval:
                self._check_model()
                last_model_check = now

            self._stop_event.wait(timeout=self._sync_interval)

    def stop(self) -> None:
        self._stop_event.set()

    def _sync_picks(self) -> None:
        events = self._queue.fetch_unsynced(limit=50)
        if not events:
            return
        logger.info("Syncing %d pick events to cloud", len(events))
        if self._client.push_picks(events):
            self._queue.mark_synced([e.order_id for e in events])
            logger.info("Sync complete — %d events marked synced", len(events))
        else:
            logger.warning("Sync failed — events remain in offline queue")

    def _check_model(self) -> None:
        new_path = self._registry.check_and_update()
        if new_path and self._on_model_updated:
            self._on_model_updated(new_path)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd vlm_vision && python3 -m pytest tests/test_sync_worker.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/local_agent/sync_worker.py vlm_vision/tests/test_sync_worker.py
git commit -m "feat: vlm-sync SyncWorker background pick sync and model polling"
```

---

## Task 5: Wire SyncWorker into main.py

**Files:**
- Modify: `vlm_vision/local_agent/main.py`

- [ ] **Step 1: Read current main.py to confirm import locations**

```bash
head -20 vlm_vision/local_agent/main.py
```

- [ ] **Step 2: Add imports for sync components**

In `vlm_vision/local_agent/main.py`, add after the existing imports:

```python
from local_agent.cloud_sync_client import CloudSyncClient
from local_agent.model_registry import ModelRegistry
from local_agent.sync_worker import SyncWorker
```

- [ ] **Step 3: Wire SyncWorker into main()**

Replace the `main()` function in `vlm_vision/local_agent/main.py` with:

```python
def main():
    config = Config.from_env()
    detector = Detector(model_path=config.model_path)
    modula = ModulaClient(base_url=config.modula_wms_url)
    queue = OfflineQueue(db_path=config.db_path)

    # Cloud sync setup
    cloud_client = CloudSyncClient(base_url=config.cloud_sync_url)
    model_registry = ModelRegistry(
        cloud_client=cloud_client,
        model_dir=config.model_dir,
        current_model_path=config.model_path,
    )

    def on_model_updated(new_path: str):
        nonlocal detector
        detector = Detector(model_path=new_path)

    sync_worker = SyncWorker(
        queue=queue,
        cloud_client=cloud_client,
        model_registry=model_registry,
        sync_interval=config.sync_interval_sec,
        model_poll_interval=config.model_poll_interval_sec,
        on_model_updated=on_model_updated,
    )
    sync_worker.start()

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
```

- [ ] **Step 4: Run all tests to confirm no regression**

```bash
cd vlm_vision && python3 -m pytest tests/ -v --tb=short
```

Expected: all tests pass (25 existing + 1 config + 8 cloud_sync + 5 model_registry + 6 sync_worker = 45)

- [ ] **Step 5: Commit**

```bash
git add vlm_vision/local_agent/main.py
git commit -m "feat: vlm-sync wire SyncWorker into main.py for background sync"
```

---

## Task 6: Final verification

- [ ] **Step 1: Run all tests one final time**

```bash
cd vlm_vision && python3 -m pytest tests/ -v --tb=short
```

Expected: 45 passed

- [ ] **Step 2: Verify file structure matches plan**

```bash
ls vlm_vision/local_agent/cloud_sync_client.py vlm_vision/local_agent/model_registry.py vlm_vision/local_agent/sync_worker.py
ls vlm_vision/tests/test_cloud_sync_client.py vlm_vision/tests/test_model_registry.py vlm_vision/tests/test_sync_worker.py
```

- [ ] **Step 3: Final commit**

```bash
git commit --allow-empty -m "chore: vlm-sync plan 3 complete — 45 tests passing"
```
