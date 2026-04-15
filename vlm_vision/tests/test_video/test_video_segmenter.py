import os
import tempfile
import time
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from local_agent.video.video_segmenter import VideoSegmenter, VideoSegment


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def test_write_frame_creates_segment_file(tmp_dir):
    completed = []
    segmenter = VideoSegmenter(
        output_dir=tmp_dir, segment_minutes=1, fps=10, resolution=(320, 240),
        on_segment_complete=completed.append,
    )
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    segmenter.write_frame(0, frame, time.time())
    segmenter.close_all()

    assert len(completed) == 1
    seg = completed[0]
    assert seg.camera_id == 0
    assert os.path.exists(seg.file_path)
    assert seg.file_size > 0
    assert seg.duration > 0


def test_segment_rotation_after_interval(tmp_dir):
    completed = []
    segmenter = VideoSegmenter(
        output_dir=tmp_dir, segment_minutes=1, fps=10, resolution=(320, 240),
        on_segment_complete=completed.append,
    )
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    now = time.time()

    segmenter.write_frame(0, frame, now)
    # Simulate 61 seconds later — should trigger rotation
    segmenter.write_frame(0, frame, now + 61)
    segmenter.close_all()

    assert len(completed) == 2  # first segment closed on rotation + second on close_all


def test_multiple_cameras(tmp_dir):
    completed = []
    segmenter = VideoSegmenter(
        output_dir=tmp_dir, segment_minutes=5, fps=10, resolution=(320, 240),
        on_segment_complete=completed.append,
    )
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    now = time.time()

    segmenter.write_frame(0, frame, now)
    segmenter.write_frame(1, frame, now)
    segmenter.close_all()

    assert len(completed) == 2
    cam_ids = {seg.camera_id for seg in completed}
    assert cam_ids == {0, 1}


def test_segment_has_correct_expiry(tmp_dir):
    completed = []
    segmenter = VideoSegmenter(
        output_dir=tmp_dir, segment_minutes=5, fps=10, resolution=(320, 240),
        retention_days=60, on_segment_complete=completed.append,
    )
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    now = time.time()
    segmenter.write_frame(0, frame, now)
    segmenter.close_all()

    seg = completed[0]
    expected_expiry = now + (60 * 86400)
    assert abs(seg.expires_at - expected_expiry) < 1
