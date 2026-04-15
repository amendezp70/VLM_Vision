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


def _make_detector_with_mock_yolo(mock_model):
    """Create a Detector that uses the ultralytics backend with a mock model."""
    with patch.dict("sys.modules", {"ultralytics": MagicMock()}):
        import importlib
        import local_agent.detector as det_mod
        importlib.reload(det_mod)

    detector = det_mod.Detector.__new__(det_mod.Detector)
    detector._backend = "ultralytics"
    detector._model = mock_model
    detector._session = None
    detector._names = {}
    return detector


def test_detect_returns_list_of_detections():
    mock_model = MagicMock()
    mock_model.return_value = make_mock_result()
    detector = _make_detector_with_mock_yolo(mock_model)

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    results = detector.detect(frame)

    assert len(results) == 1
    assert isinstance(results[0], Detection)
    assert results[0].sku == "STL-P-100-BK"
    assert results[0].color == "black"
    assert results[0].confidence == pytest.approx(0.94, abs=0.01)
    assert results[0].bbox == (10, 20, 110, 80)


def test_detect_returns_empty_on_no_detections():
    mock_model = MagicMock()
    empty_result = MagicMock()
    empty_result.boxes.xyxy = []
    empty_result.boxes.conf = []
    empty_result.boxes.cls = []
    empty_result.names = {}
    mock_model.return_value = [empty_result]
    detector = _make_detector_with_mock_yolo(mock_model)

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    results = detector.detect(frame)

    assert results == []
