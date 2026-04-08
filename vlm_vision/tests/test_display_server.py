# vlm_vision/tests/test_display_server.py
import numpy as np
import pytest
from fastapi.testclient import TestClient


def make_frame(value: int = 128) -> np.ndarray:
    return np.full((480, 640, 3), value, dtype=np.uint8)


def test_update_frame_stores_frame():
    from local_agent.display_server import update_frame, frame_store
    update_frame(bay_id=1, frame=make_frame(99))
    result = frame_store.get(bay_id=1)
    assert result is not None
    assert result.shape == (480, 640, 3)


def test_mjpeg_endpoint_returns_503_without_frame(monkeypatch):
    import local_agent.display_server as ds
    from local_agent.display_server import app
    from local_agent.frame_store import FrameStore
    # Replace frame_store with empty one
    monkeypatch.setattr(ds, "frame_store", FrameStore())

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/bay/99/video")
    assert response.status_code == 503
