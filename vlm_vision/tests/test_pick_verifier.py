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
