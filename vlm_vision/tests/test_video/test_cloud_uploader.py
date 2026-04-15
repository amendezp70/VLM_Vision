import os
import sqlite3
import tempfile
import time

import pytest

from local_agent.video.cloud_uploader import CloudUploader
from local_agent.video.video_segmenter import VideoSegment


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def make_segment(tmp_dir, segment_id="seg001", camera_id=0) -> VideoSegment:
    file_path = os.path.join(tmp_dir, f"{segment_id}.mp4")
    with open(file_path, "wb") as f:
        f.write(b"\x00" * 1024)
    return VideoSegment(
        segment_id=segment_id,
        camera_id=camera_id,
        start_time=time.time() - 300,
        end_time=time.time(),
        duration=300,
        file_path=file_path,
        file_size=1024,
        expires_at=time.time() + 86400 * 60,
    )


def test_enqueue_creates_db_record(tmp_dir):
    db_path = os.path.join(tmp_dir, "queue.db")
    uploader = CloudUploader(cloud_base_url="http://localhost", db_path=db_path)
    seg = make_segment(tmp_dir)
    uploader.enqueue(seg)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT segment_id, uploaded FROM upload_queue").fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][0] == "seg001"
    assert rows[0][1] == 0  # not uploaded yet


def test_pending_count(tmp_dir):
    db_path = os.path.join(tmp_dir, "queue.db")
    uploader = CloudUploader(cloud_base_url="http://localhost", db_path=db_path)

    uploader.enqueue(make_segment(tmp_dir, "seg001"))
    uploader.enqueue(make_segment(tmp_dir, "seg002"))

    assert uploader.get_pending_count() == 2
    assert uploader.get_uploaded_count() == 0


def test_mark_uploaded_via_db(tmp_dir):
    db_path = os.path.join(tmp_dir, "queue.db")
    uploader = CloudUploader(cloud_base_url="http://localhost", db_path=db_path)
    uploader.enqueue(make_segment(tmp_dir, "seg001"))

    # Simulate manual upload marking
    uploader._mark_uploaded("seg001", "https://cloud.example.com/seg001.mp4")

    assert uploader.get_pending_count() == 0
    assert uploader.get_uploaded_count() == 1
