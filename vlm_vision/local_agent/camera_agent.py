# vlm_vision/local_agent/camera_agent.py
"""
Captures frames from a single camera and puts them onto a Queue.
One CameraAgent instance per bay. Runs in its own thread.

Platform support:
  - macOS:   AVFoundation backend, fallback to lower resolution
  - Windows: DirectShow backend
  - Linux:   V4L2 backend (default)
"""
import platform
import threading
import time
import cv2
import numpy as np
from queue import Queue, Full
from typing import Optional

# Preferred resolution tiers (width, height) — tried in order
_RESOLUTION_TIERS = [
    (3840, 2160),  # 4K
    (1920, 1080),  # Full HD
    (1280, 720),   # HD
]


def _camera_backend() -> int:
    """Return the best OpenCV backend for the current OS."""
    system = platform.system()
    if system == "Darwin":
        return cv2.CAP_AVFOUNDATION
    if system == "Windows":
        return cv2.CAP_DSHOW
    return cv2.CAP_V4L2  # Linux


class CameraAgent(threading.Thread):
    def __init__(self, camera_id: int, frame_queue: Queue, fps: int = 10):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self._queue = frame_queue
        self._interval = 1.0 / fps
        self._stop_event = threading.Event()
        self._cap: Optional[cv2.VideoCapture] = None

    def _open_camera(self) -> cv2.VideoCapture:
        backend = _camera_backend()
        cap = cv2.VideoCapture(self.camera_id, backend)
        if not cap.isOpened():
            # Fallback: let OpenCV pick the backend automatically
            cap = cv2.VideoCapture(self.camera_id)

        # Try resolutions from highest to lowest
        for w, h in _RESOLUTION_TIERS:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if actual_w >= w and actual_h >= h:
                break

        return cap

    def run(self) -> None:
        self._cap = self._open_camera()

        while not self._stop_event.is_set():
            start = time.monotonic()
            ok, frame = self._cap.read()
            if ok:
                try:
                    self._queue.put_nowait(frame)
                except Full:
                    # Drop oldest frame to keep queue fresh
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(frame)
                    except Exception:
                        pass
            elapsed = time.monotonic() - start
            sleep_for = self._interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def stop(self) -> None:
        self._stop_event.set()
        if self._cap:
            self._cap.release()
