# vlm_vision/local_agent/video/cloud_uploader.py
"""
Background upload queue for video segments to Catalyst File Store.
Retries on failure with exponential backoff. Non-blocking to recording.
"""
import os
import sqlite3
import threading
import time
from typing import Optional

import httpx

from local_agent.video.video_segmenter import VideoSegment


class CloudUploader:
    """Queues video segments for background upload to cloud storage."""

    def __init__(
        self,
        cloud_base_url: str,
        db_path: str = "video_queue.db",
        max_retries: int = 5,
        base_delay: float = 5.0,
        upload_interval: float = 10.0,
    ):
        self._cloud_base_url = cloud_base_url
        self._db_path = db_path
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._upload_interval = upload_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS upload_queue (
                segment_id TEXT PRIMARY KEY,
                camera_id INTEGER,
                file_path TEXT,
                start_time REAL,
                end_time REAL,
                duration REAL,
                file_size INTEGER,
                expires_at REAL,
                retry_count INTEGER DEFAULT 0,
                uploaded INTEGER DEFAULT 0,
                cloud_url TEXT DEFAULT ''
            )
        """)
        conn.commit()
        conn.close()

    def enqueue(self, segment: VideoSegment) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            """INSERT OR REPLACE INTO upload_queue
               (segment_id, camera_id, file_path, start_time, end_time,
                duration, file_size, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                segment.segment_id, segment.camera_id, segment.file_path,
                segment.start_time, segment.end_time, segment.duration,
                segment.file_size, segment.expires_at,
            ),
        )
        conn.commit()
        conn.close()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._upload_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _upload_loop(self) -> None:
        while not self._stop_event.is_set():
            self._process_pending()
            self._stop_event.wait(timeout=self._upload_interval)

    def _process_pending(self) -> None:
        conn = sqlite3.connect(self._db_path)
        rows = conn.execute(
            """SELECT segment_id, file_path, retry_count
               FROM upload_queue
               WHERE uploaded = 0 AND retry_count < ?
               ORDER BY start_time ASC LIMIT 5""",
            (self._max_retries,),
        ).fetchall()
        conn.close()

        for segment_id, file_path, retry_count in rows:
            if self._stop_event.is_set():
                break
            self._upload_one(segment_id, file_path, retry_count)

    def _upload_one(self, segment_id: str, file_path: str, retry_count: int) -> None:
        if not os.path.exists(file_path):
            self._mark_uploaded(segment_id, "")  # file gone, skip
            return

        try:
            cloud_url = self._do_upload(file_path, segment_id)
            self._mark_uploaded(segment_id, cloud_url)
        except Exception:
            delay = self._base_delay * (2 ** retry_count)
            self._increment_retry(segment_id)
            time.sleep(min(delay, 300))

    def _do_upload(self, file_path: str, segment_id: str) -> str:
        url = f"{self._cloud_base_url}/video/segments"
        with open(file_path, "rb") as f:
            resp = httpx.post(
                url,
                files={"file": (os.path.basename(file_path), f, "video/mp4")},
                data={"segment_id": segment_id},
                timeout=300,
            )
        resp.raise_for_status()
        return resp.json().get("cloud_url", "")

    def _mark_uploaded(self, segment_id: str, cloud_url: str) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE upload_queue SET uploaded = 1, cloud_url = ? WHERE segment_id = ?",
            (cloud_url, segment_id),
        )
        conn.commit()
        conn.close()

    def _increment_retry(self, segment_id: str) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE upload_queue SET retry_count = retry_count + 1 WHERE segment_id = ?",
            (segment_id,),
        )
        conn.commit()
        conn.close()

    def get_pending_count(self) -> int:
        conn = sqlite3.connect(self._db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM upload_queue WHERE uploaded = 0"
        ).fetchone()[0]
        conn.close()
        return count

    def get_uploaded_count(self) -> int:
        conn = sqlite3.connect(self._db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM upload_queue WHERE uploaded = 1"
        ).fetchone()[0]
        conn.close()
        return count
