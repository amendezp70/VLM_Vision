# vlm_vision/local_agent/sync_worker.py
"""
Background daemon thread that periodically:
  1. Drains unsynced picks from OfflineQueue -> pushes to Catalyst
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
