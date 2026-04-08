import os
from local_agent.models import Detection, PickOrder, PickEvent, BayStatus
from local_agent.config import Config

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
