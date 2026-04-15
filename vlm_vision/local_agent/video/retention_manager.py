# vlm_vision/local_agent/video/retention_manager.py
"""
Enforces video retention policies:
  - Local buffer: delete files older than 24 hours (after upload confirmed)
  - Cloud segments: flag expired (60 days) for deletion
  - Evidence clips: never deleted
"""
import os
import sqlite3
import time
from typing import List, Tuple


class RetentionManager:
    """Cleans up expired video segments from local disk and cloud."""

    def __init__(
        self,
        db_path: str,
        local_buffer_hours: int = 24,
        retention_days: int = 60,
    ):
        self._db_path = db_path
        self._local_buffer_seconds = local_buffer_hours * 3600
        self._retention_seconds = retention_days * 86400

    def cleanup_local(self) -> int:
        """Delete local files older than buffer period that are already uploaded."""
        cutoff = time.time() - self._local_buffer_seconds
        conn = sqlite3.connect(self._db_path)
        rows = conn.execute(
            """SELECT segment_id, file_path FROM upload_queue
               WHERE uploaded = 1 AND start_time < ? AND file_path != ''""",
            (cutoff,),
        ).fetchall()
        conn.close()

        deleted = 0
        for segment_id, file_path in rows:
            if os.path.exists(file_path):
                os.remove(file_path)
                deleted += 1
            self._clear_local_path(segment_id)
        return deleted

    def find_expired_cloud(self) -> List[Tuple[str, str]]:
        """Return (segment_id, cloud_url) pairs that have exceeded retention."""
        now = time.time()
        conn = sqlite3.connect(self._db_path)
        rows = conn.execute(
            """SELECT segment_id, cloud_url FROM upload_queue
               WHERE uploaded = 1 AND expires_at > 0 AND expires_at < ?""",
            (now,),
        ).fetchall()
        conn.close()
        return rows

    def mark_cloud_deleted(self, segment_id: str) -> None:
        """Mark a segment as deleted from cloud (after API call to remove it)."""
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "DELETE FROM upload_queue WHERE segment_id = ?",
            (segment_id,),
        )
        conn.commit()
        conn.close()

    def _clear_local_path(self, segment_id: str) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE upload_queue SET file_path = '' WHERE segment_id = ?",
            (segment_id,),
        )
        conn.commit()
        conn.close()

    def get_local_disk_usage(self, output_dir: str) -> int:
        """Return total bytes used by local video files."""
        total = 0
        if os.path.exists(output_dir):
            for f in os.listdir(output_dir):
                fp = os.path.join(output_dir, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
        return total
