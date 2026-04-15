import os
import sqlite3
import tempfile
import time

import pytest

from local_agent.video.cloud_uploader import CloudUploader
from local_agent.video.retention_manager import RetentionManager
from local_agent.video.video_segmenter import VideoSegment


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def setup_db_with_segment(tmp_dir, segment_id, uploaded, start_time, expires_at):
    db_path = os.path.join(tmp_dir, "queue.db")
    file_path = os.path.join(tmp_dir, f"{segment_id}.mp4")
    with open(file_path, "wb") as f:
        f.write(b"\x00" * 512)

    uploader = CloudUploader(cloud_base_url="http://localhost", db_path=db_path)
    seg = VideoSegment(
        segment_id=segment_id, camera_id=0, start_time=start_time,
        end_time=start_time + 300, duration=300, file_path=file_path,
        file_size=512, expires_at=expires_at,
    )
    uploader.enqueue(seg)

    if uploaded:
        uploader._mark_uploaded(segment_id, "https://cloud.example.com/test.mp4")

    return db_path, file_path


def test_cleanup_local_deletes_old_uploaded(tmp_dir):
    old_time = time.time() - 90000  # 25 hours ago
    db_path, file_path = setup_db_with_segment(
        tmp_dir, "seg_old", uploaded=True, start_time=old_time,
        expires_at=old_time + 86400 * 60,
    )
    assert os.path.exists(file_path)

    retention = RetentionManager(db_path=db_path, local_buffer_hours=24)
    deleted = retention.cleanup_local()

    assert deleted == 1
    assert not os.path.exists(file_path)


def test_cleanup_local_keeps_recent(tmp_dir):
    recent_time = time.time() - 3600  # 1 hour ago
    db_path, file_path = setup_db_with_segment(
        tmp_dir, "seg_new", uploaded=True, start_time=recent_time,
        expires_at=recent_time + 86400 * 60,
    )

    retention = RetentionManager(db_path=db_path, local_buffer_hours=24)
    deleted = retention.cleanup_local()

    assert deleted == 0
    assert os.path.exists(file_path)


def test_find_expired_cloud(tmp_dir):
    expired_time = time.time() - 100  # already expired
    db_path, _ = setup_db_with_segment(
        tmp_dir, "seg_expired", uploaded=True, start_time=time.time() - 86400 * 61,
        expires_at=expired_time,
    )

    retention = RetentionManager(db_path=db_path, retention_days=60)
    expired = retention.find_expired_cloud()

    assert len(expired) == 1
    assert expired[0][0] == "seg_expired"
