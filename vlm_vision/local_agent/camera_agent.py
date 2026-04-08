# vlm_vision/local_agent/camera_agent.py
"""
Captures frames from a single camera and puts them onto a Queue.
One CameraAgent instance per bay. Runs in its own thread.
"""
import threading
import time
import cv2
import numpy as np
from queue import Queue, Full
from typing import Optional


class CameraAgent(threading.Thread):
    def __init__(self, camera_id: int, frame_queue: Queue, fps: int = 10):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self._queue = frame_queue
        self._interval = 1.0 / fps
        self._stop_event = threading.Event()
        self._cap: Optional[cv2.VideoCapture] = None

    def run(self) -> None:
        self._cap = cv2.VideoCapture(self.camera_id)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)

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
