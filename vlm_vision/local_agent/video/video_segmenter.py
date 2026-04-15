# vlm_vision/local_agent/video/video_segmenter.py
"""
Splits continuous camera frames into 5-minute H.264 MP4 segments.
Each segment is a self-contained file that can be uploaded independently.
"""
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional

import cv2
import numpy as np


@dataclass
class VideoSegment:
    segment_id: str
    camera_id: int
    start_time: float
    end_time: float = 0.0
    duration: float = 0.0
    file_path: str = ""
    file_size: int = 0
    cloud_url: str = ""
    uploaded: bool = False
    expires_at: float = 0.0


class VideoSegmenter:
    """Receives frames and writes them into time-bounded MP4 segments."""

    def __init__(
        self,
        output_dir: str,
        segment_minutes: int = 5,
        fps: int = 15,
        resolution: tuple = (1920, 1080),
        retention_days: int = 60,
        on_segment_complete: Optional[Callable[[VideoSegment], None]] = None,
    ):
        self._output_dir = output_dir
        self._segment_seconds = segment_minutes * 60
        self._fps = fps
        self._resolution = resolution
        self._retention_days = retention_days
        self._on_segment_complete = on_segment_complete

        self._writers: Dict[int, cv2.VideoWriter] = {}
        self._segments: Dict[int, VideoSegment] = {}
        self._segment_start: Dict[int, float] = {}

        os.makedirs(output_dir, exist_ok=True)

    def write_frame(self, camera_id: int, frame: np.ndarray, timestamp: float) -> None:
        if camera_id not in self._writers or self._should_rotate(camera_id, timestamp):
            self._rotate_segment(camera_id, timestamp)

        writer = self._writers.get(camera_id)
        if writer and writer.isOpened():
            resized = cv2.resize(frame, self._resolution) if frame.shape[:2] != self._resolution[::-1] else frame
            writer.write(resized)

    def _should_rotate(self, camera_id: int, timestamp: float) -> bool:
        start = self._segment_start.get(camera_id, 0)
        return (timestamp - start) >= self._segment_seconds

    def _rotate_segment(self, camera_id: int, timestamp: float) -> None:
        self._close_segment(camera_id)
        self._open_segment(camera_id, timestamp)

    def _open_segment(self, camera_id: int, timestamp: float) -> None:
        dt = datetime.fromtimestamp(timestamp)
        filename = f"cam{camera_id}_{dt.strftime('%Y-%m-%d_%H-%M-%S')}.mp4"
        filepath = os.path.join(self._output_dir, filename)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(filepath, fourcc, self._fps, self._resolution)

        segment_id = f"cam{camera_id}_{dt.strftime('%Y%m%d%H%M%S')}"
        self._writers[camera_id] = writer
        self._segment_start[camera_id] = timestamp
        self._segments[camera_id] = VideoSegment(
            segment_id=segment_id,
            camera_id=camera_id,
            start_time=timestamp,
            file_path=filepath,
            expires_at=timestamp + (self._retention_days * 86400),
        )

    def _close_segment(self, camera_id: int) -> None:
        writer = self._writers.pop(camera_id, None)
        segment = self._segments.pop(camera_id, None)
        if writer:
            writer.release()
        if segment and segment.file_path and os.path.exists(segment.file_path):
            segment.end_time = time.time()
            segment.duration = segment.end_time - segment.start_time
            segment.file_size = os.path.getsize(segment.file_path)
            if self._on_segment_complete:
                self._on_segment_complete(segment)

    def close_all(self) -> None:
        for camera_id in list(self._writers.keys()):
            self._close_segment(camera_id)
