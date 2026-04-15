# vlm_vision/local_agent/video/multi_camera_recorder.py
"""
Continuous H.264 recording from multiple cameras.
One recording thread per camera. Frames written to VideoWriter
and passed to VideoSegmenter for 5-minute splitting.
"""
import threading
import time
from typing import Callable, Dict, List, Optional

import cv2
import numpy as np


class CameraRecorder(threading.Thread):
    """Records a single camera stream to segmented video files."""

    def __init__(
        self,
        camera_id: int,
        fps: int,
        resolution: tuple,
        codec: str,
        bitrate: int,
        on_frame: Optional[Callable[[int, np.ndarray, float], None]] = None,
    ):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.fps = fps
        self.resolution = resolution
        self.codec = codec
        self.bitrate = bitrate
        self._on_frame = on_frame
        self._stop_event = threading.Event()
        self._cap: Optional[cv2.VideoCapture] = None

    def run(self) -> None:
        self._cap = cv2.VideoCapture(self.camera_id)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])

        interval = 1.0 / self.fps
        while not self._stop_event.is_set():
            start = time.monotonic()
            ok, frame = self._cap.read()
            if ok and self._on_frame:
                self._on_frame(self.camera_id, frame, time.time())
            elapsed = time.monotonic() - start
            sleep_for = interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def stop(self) -> None:
        self._stop_event.set()
        if self._cap:
            self._cap.release()


class MultiCameraRecorder:
    """Manages CameraRecorder threads for all configured cameras."""

    def __init__(
        self,
        camera_ids: List[int],
        fps: int = 15,
        resolution: tuple = (1920, 1080),
        codec: str = "h264",
        bitrate: int = 2_000_000,
        on_frame: Optional[Callable[[int, np.ndarray, float], None]] = None,
    ):
        self._recorders: Dict[int, CameraRecorder] = {}
        for cam_id in camera_ids:
            self._recorders[cam_id] = CameraRecorder(
                camera_id=cam_id,
                fps=fps,
                resolution=resolution,
                codec=codec,
                bitrate=bitrate,
                on_frame=on_frame,
            )

    def start(self) -> None:
        for recorder in self._recorders.values():
            recorder.start()

    def stop(self) -> None:
        for recorder in self._recorders.values():
            recorder.stop()

    @property
    def camera_ids(self) -> List[int]:
        return list(self._recorders.keys())
