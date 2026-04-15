import os
import tempfile

import cv2
import numpy as np
import pytest

from local_agent.video.clip_extractor import ClipExtractor


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def create_test_video(path, fps=10, duration_sec=60, resolution=(320, 240)):
    """Create a small test MP4 file."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, resolution)
    total_frames = int(fps * duration_sec)
    for i in range(total_frames):
        frame = np.full((*resolution[::-1], 3), i % 256, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_extract_creates_clip(tmp_dir):
    video_path = os.path.join(tmp_dir, "segment.mp4")
    create_test_video(video_path, fps=10, duration_sec=60)

    extractor = ClipExtractor(output_dir=tmp_dir, margin_sec=5)
    clip = extractor.extract(
        segment_file=video_path, offset_sec=30.0,
        event_id="evt001", segment_id="seg001",
    )

    assert clip is not None
    assert os.path.exists(clip.file_path)
    assert clip.clip_start_sec == 25.0
    assert clip.clip_end_sec == 35.0
    assert clip.event_id == "evt001"
    assert clip.retained_indefinitely is True


def test_extract_clamps_to_start(tmp_dir):
    video_path = os.path.join(tmp_dir, "segment.mp4")
    create_test_video(video_path, fps=10, duration_sec=60)

    extractor = ClipExtractor(output_dir=tmp_dir, margin_sec=30)
    clip = extractor.extract(
        segment_file=video_path, offset_sec=10.0,
        event_id="evt002", segment_id="seg002",
    )

    assert clip is not None
    assert clip.clip_start_sec == 0.0  # clamped to start
    assert clip.clip_end_sec == 40.0


def test_extract_clamps_to_end(tmp_dir):
    video_path = os.path.join(tmp_dir, "segment.mp4")
    create_test_video(video_path, fps=10, duration_sec=60)

    extractor = ClipExtractor(output_dir=tmp_dir, margin_sec=30)
    clip = extractor.extract(
        segment_file=video_path, offset_sec=50.0,
        event_id="evt003", segment_id="seg003",
    )

    assert clip is not None
    assert clip.clip_start_sec == 20.0
    assert clip.clip_end_sec == 60.0  # clamped to end


def test_extract_returns_none_for_missing_file(tmp_dir):
    extractor = ClipExtractor(output_dir=tmp_dir)
    clip = extractor.extract(
        segment_file="/nonexistent/file.mp4", offset_sec=30.0,
        event_id="evt004", segment_id="seg004",
    )
    assert clip is None


def test_extract_clip_file_is_valid_video(tmp_dir):
    video_path = os.path.join(tmp_dir, "segment.mp4")
    create_test_video(video_path, fps=10, duration_sec=60)

    extractor = ClipExtractor(output_dir=tmp_dir, margin_sec=5)
    clip = extractor.extract(
        segment_file=video_path, offset_sec=30.0,
        event_id="evt005", segment_id="seg005",
    )

    assert clip is not None
    cap = cv2.VideoCapture(clip.file_path)
    assert cap.isOpened()
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    assert frame_count > 0
    cap.release()
