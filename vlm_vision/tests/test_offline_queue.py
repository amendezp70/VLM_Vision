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
