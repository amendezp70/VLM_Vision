import json
import sqlite3
from typing import List
from local_agent.models import PickEvent


class OfflineQueue:
    def __init__(self, db_path: str = "picks.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_table()

    def _create_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS pick_events (
                order_id TEXT NOT NULL,
                payload  TEXT NOT NULL,
                synced   INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.commit()

    def enqueue(self, event: PickEvent) -> None:
        payload = json.dumps({
            "order_id": event.order_id,
            "sku": event.sku,
            "qty_picked": event.qty_picked,
            "bay_id": event.bay_id,
            "worker_id": event.worker_id,
            "result": event.result,
            "timestamp": event.timestamp,
        })
        self._conn.execute(
            "INSERT INTO pick_events (order_id, payload, synced) VALUES (?, ?, 0)",
            (event.order_id, payload),
        )
        self._conn.commit()

    def fetch_unsynced(self, limit: int = 50) -> List[PickEvent]:
        rows = self._conn.execute(
            "SELECT payload FROM pick_events WHERE synced = 0 LIMIT ?", (limit,)
        ).fetchall()
        events = []
        for (payload,) in rows:
            data = json.loads(payload)
            events.append(PickEvent(**data))
        return events

    def mark_synced(self, order_ids: List[str]) -> None:
        self._conn.executemany(
            "UPDATE pick_events SET synced = 1 WHERE order_id = ?",
            [(oid,) for oid in order_ids],
        )
        self._conn.commit()

    def unsynced_count(self) -> int:
        (count,) = self._conn.execute(
            "SELECT COUNT(*) FROM pick_events WHERE synced = 0"
        ).fetchone()
        return count

    def close(self) -> None:
        self._conn.close()
