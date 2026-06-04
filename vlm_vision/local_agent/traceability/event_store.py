# vlm_vision/local_agent/traceability/event_store.py
"""
EventStore -- the local memory of the traceability system.

Right now the system detects barcode events and cuts evidence clips, then
forgets them. This module gives it a memory: a small SQLite database that
records every CorrelationEvent and every evidence clip, and lets you search
by barcode or box id -- exactly what a manager needs to investigate a dispute.

Why local SQLite first (instead of waiting on Zoho):
  * It is the SAME data that will live in the Zoho Datastore tables, just
    stored locally. When the cloud tables are ready, syncing is a thin layer
    that reads pending_uploads() from here and pushes them up -- no rebuild.
  * It doubles as the OFFLINE BUFFER: if the factory loses internet, events
    keep recording locally and sync later.
  * sqlite3 is built into Python -- no install, no external service.

This module imports only the standard library, so it has no dependency on
cameras, pyzbar, or the cloud, and can be tested on any machine.
"""
import logging
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventStore:
    def __init__(self, db_path: str = "data/traceability.db"):
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    # ---- connection helper -------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        # check_same_thread=False so the recorder (background threads) and a
        # reader (dashboard) can both use the store; WAL keeps reads/writes
        # from blocking each other.
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id          TEXT PRIMARY KEY,
                    box_id            TEXT,
                    zone_id           INTEGER,
                    barcode_camera    TEXT,
                    barcode_scanner   TEXT,
                    match_status      TEXT,
                    verified          INTEGER,
                    event_timestamp   REAL,
                    camera_timestamp  REAL,
                    scanner_timestamp REAL,
                    time_delta_sec    REAL,
                    created_at        REAL
                );

                CREATE TABLE IF NOT EXISTS clips (
                    clip_id          TEXT PRIMARY KEY,
                    request_id       TEXT,
                    event_id         TEXT,
                    reason           TEXT,
                    zone_id          INTEGER,
                    camera_id        INTEGER,
                    box_id           TEXT,
                    event_timestamp  REAL,
                    clip_start       REAL,
                    clip_end         REAL,
                    segment_file     TEXT,
                    offset_sec       REAL,
                    file_path        TEXT,
                    cloud_url        TEXT DEFAULT '',
                    uploaded         INTEGER DEFAULT 0,
                    notes            TEXT,
                    created_at       REAL
                );

                CREATE INDEX IF NOT EXISTS idx_events_camera  ON events(barcode_camera);
                CREATE INDEX IF NOT EXISTS idx_events_scanner ON events(barcode_scanner);
                CREATE INDEX IF NOT EXISTS idx_events_box     ON events(box_id);
                CREATE INDEX IF NOT EXISTS idx_clips_event    ON clips(event_id);
                CREATE INDEX IF NOT EXISTS idx_clips_upload   ON clips(uploaded);
                """
            )

    # ---- writing -----------------------------------------------------------

    def record_event(self, event: Any, event_id: Optional[str] = None) -> str:
        """Record a CorrelationEvent (or any object with the same attributes).

        Returns the event_id used (generated if not supplied).
        """
        status = event.match_status
        status = status.value if hasattr(status, "value") else str(status)
        verified = bool(getattr(event, "is_verified", status == "match"))
        ts = float(getattr(event, "timestamp", time.time()))

        if event_id is None:
            event_id = f"EVT-{int(ts * 1000)}-{uuid.uuid4().hex[:4]}"

        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO events
                   (event_id, box_id, zone_id, barcode_camera, barcode_scanner,
                    match_status, verified, event_timestamp, camera_timestamp,
                    scanner_timestamp, time_delta_sec, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    getattr(event, "box_id", None),
                    getattr(event, "zone_id", None),
                    getattr(event, "barcode_camera", None),
                    getattr(event, "barcode_scanner", None),
                    status,
                    1 if verified else 0,
                    ts,
                    getattr(event, "camera_timestamp", None),
                    getattr(event, "scanner_timestamp", None),
                    getattr(event, "time_delta_sec", None),
                    time.time(),
                ),
            )
        logger.debug("Recorded event %s (%s)", event_id, status)
        return event_id

    def record_clip(
        self,
        *,
        clip_id: Optional[str] = None,
        event_id: Optional[str] = None,
        request_id: Optional[str] = None,
        reason: Optional[str] = None,
        zone_id: Optional[int] = None,
        camera_id: Optional[int] = None,
        box_id: Optional[str] = None,
        event_timestamp: Optional[float] = None,
        clip_start: Optional[float] = None,
        clip_end: Optional[float] = None,
        segment_file: Optional[str] = None,
        offset_sec: Optional[float] = None,
        file_path: Optional[str] = None,
        notes: Optional[str] = None,
        cloud_url: str = "",
        uploaded: bool = False,
    ) -> str:
        """Record a generated evidence clip. Returns the clip_id used."""
        if clip_id is None:
            clip_id = request_id or f"CLIP-{int(time.time() * 1000)}-{uuid.uuid4().hex[:4]}"
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO clips
                   (clip_id, request_id, event_id, reason, zone_id, camera_id,
                    box_id, event_timestamp, clip_start, clip_end, segment_file,
                    offset_sec, file_path, cloud_url, uploaded, notes, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    clip_id, request_id, event_id, reason, zone_id, camera_id,
                    box_id, event_timestamp, clip_start, clip_end, segment_file,
                    offset_sec, file_path, cloud_url, 1 if uploaded else 0,
                    notes, time.time(),
                ),
            )
        logger.debug("Recorded clip %s for event %s", clip_id, event_id)
        return clip_id

    def mark_uploaded(self, clip_id: str, cloud_url: str) -> None:
        """Mark a clip as synced to the cloud (used by the future Zoho layer)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE clips SET uploaded = 1, cloud_url = ? WHERE clip_id = ?",
                (cloud_url, clip_id),
            )

    # ---- reading / searching ----------------------------------------------

    def _attach_clips(self, conn: sqlite3.Connection, events: List[Dict]) -> List[Dict]:
        for ev in events:
            rows = conn.execute(
                "SELECT * FROM clips WHERE event_id = ? ORDER BY created_at",
                (ev["event_id"],),
            ).fetchall()
            ev["clips"] = [dict(r) for r in rows]
        return events

    def search_by_barcode(self, barcode: str) -> List[Dict]:
        """Find events where either the camera or the scanner read this barcode,
        newest first, each with its evidence clips attached."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM events
                   WHERE barcode_camera = ? OR barcode_scanner = ?
                   ORDER BY event_timestamp DESC""",
                (barcode, barcode),
            ).fetchall()
            return self._attach_clips(conn, [dict(r) for r in rows])

    def search_by_box(self, box_id: str) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE box_id = ? ORDER BY event_timestamp DESC",
                (box_id,),
            ).fetchall()
            return self._attach_clips(conn, [dict(r) for r in rows])

    def get_event(self, event_id: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if not row:
                return None
            return self._attach_clips(conn, [dict(row)])[0]

    def recent_events(self, limit: int = 50) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY event_timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def pending_uploads(self) -> List[Dict]:
        """Clips not yet pushed to the cloud -- the future Zoho sync reads this."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM clips WHERE uploaded = 0 ORDER BY created_at"
            ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> Dict[str, int]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            mism = conn.execute(
                "SELECT COUNT(*) FROM events WHERE match_status = 'mismatch'"
            ).fetchone()[0]
            clips = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM clips WHERE uploaded = 0"
            ).fetchone()[0]
            return {
                "events": total,
                "mismatches": mism,
                "clips": clips,
                "pending_upload": pending,
            }