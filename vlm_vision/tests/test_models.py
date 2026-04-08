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
