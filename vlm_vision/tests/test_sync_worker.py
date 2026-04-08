# vlm_vision/tests/test_sync_worker.py
import time
import pytest
from unittest.mock import MagicMock
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
