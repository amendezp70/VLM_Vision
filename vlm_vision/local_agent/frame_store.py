# vlm_vision/local_agent/frame_store.py
"""
Thread-safe per-bay frame buffer.
Holds the latest captured frame for each bay so the MJPEG endpoint
can serve it without touching the detection queue.
"""
import threading
import numpy as np
from typing import Dict, Optional


class FrameStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frames: Dict[int, np.ndarray] = {}

    def update(self, bay_id: int, frame: np.ndarray) -> None:
        with self._lock:
            self._frames[bay_id] = frame.copy()

    def get(self, bay_id: int) -> Optional[np.ndarray]:
        with self._lock:
            return self._frames.get(bay_id)
