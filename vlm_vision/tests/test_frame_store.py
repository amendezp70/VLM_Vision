# vlm_vision/tests/test_frame_store.py
import numpy as np
import threading
import pytest
from local_agent.frame_store import FrameStore


def make_frame(value: int = 128) -> np.ndarray:
    return np.full((480, 640, 3), value, dtype=np.uint8)


def test_get_returns_none_before_any_update():
    store = FrameStore()
    assert store.get(bay_id=1) is None


def test_update_and_get_returns_frame():
    store = FrameStore()
    frame = make_frame(100)
    store.update(bay_id=1, frame=frame)
    result = store.get(bay_id=1)
    assert result is not None
    assert result.shape == (480, 640, 3)
    assert result[0, 0, 0] == 100


def test_update_stores_copy_not_reference():
    store = FrameStore()
    frame = make_frame(50)
    store.update(bay_id=1, frame=frame)
    frame[0, 0, 0] = 255  # mutate original
    result = store.get(bay_id=1)
    assert result[0, 0, 0] == 50  # store is unaffected


def test_separate_bays_are_independent():
    store = FrameStore()
    store.update(bay_id=1, frame=make_frame(10))
    store.update(bay_id=2, frame=make_frame(20))
    assert store.get(bay_id=1)[0, 0, 0] == 10
    assert store.get(bay_id=2)[0, 0, 0] == 20
    assert store.get(bay_id=3) is None


def test_concurrent_updates_are_safe():
    store = FrameStore()
    errors = []

    def writer(bay_id, value):
        try:
            for _ in range(100):
                store.update(bay_id=bay_id, frame=make_frame(value))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i, i * 10)) for i in range(1, 4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    for i in range(1, 4):
        assert store.get(bay_id=i) is not None
