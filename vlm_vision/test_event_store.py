#!/usr/bin/env python
"""
test_event_store.py  --  test for local_agent/traceability/event_store.py

RUN (from the vlm_vision/ directory, venv active):
    python test_event_store.py

It records events and clips, searches them, checks the cloud-upload tracking,
and proves the data really survives on disk (reopen the DB and it is still
there). No camera, no cloud, no installs -- pure SQLite.
"""

import os
import shutil
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from local_agent.traceability.event_store import EventStore

TEST_DIR = "test_eventstore_output"
DB_PATH = os.path.join(TEST_DIR, "traceability.db")

_passed = 0
_failed = 0


def check(name, condition, detail=""):
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
    line = f"  [{'PASS' if condition else 'FAIL'}] {name}"
    if detail:
        line += f"   ({detail})"
    print(line)
    return condition


# These mirror the real CorrelationEvent / MatchStatus fields exactly, so the
# store is exercised the same way it will be in production. (Defined locally so
# the test has no camera/pyzbar import chain and runs anywhere.)
class MatchStatus(Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    PENDING = "pending"


@dataclass
class FakeEvent:
    box_id: Optional[str]
    zone_id: int
    barcode_camera: Optional[str]
    barcode_scanner: Optional[str]
    match_status: MatchStatus
    timestamp: float
    camera_timestamp: Optional[float] = None
    scanner_timestamp: Optional[float] = None
    time_delta_sec: Optional[float] = None

    @property
    def is_verified(self):
        return self.match_status == MatchStatus.MATCH


def run():
    if os.path.isdir(TEST_DIR):
        shutil.rmtree(TEST_DIR)
    store = EventStore(db_path=DB_PATH)
    now = time.time()

    # ---- record a MATCH and a MISMATCH event ----
    print("Recording events")
    match_ev = FakeEvent("BOX-100", 2, "0687456223537", "0687456223537",
                         MatchStatus.MATCH, now, now, now + 0.4, 0.4)
    mism_ev = FakeEvent("BOX-200", 2, "0687456223537", "9999999999999",
                        MatchStatus.MISMATCH, now + 10, now + 10, now + 11, 1.0)
    match_id = store.record_event(match_ev)
    mism_id = store.record_event(mism_ev)
    check("got an id for the match event", bool(match_id))
    check("got an id for the mismatch event", bool(mism_id))

    ev = store.get_event(match_id)
    check("match event reads back verified=1", ev and ev["verified"] == 1,
          f"verified={ev['verified'] if ev else '?'}")
    ev = store.get_event(mism_id)
    check("mismatch event reads back verified=0", ev and ev["verified"] == 0)
    check("mismatch status stored correctly", ev and ev["match_status"] == "mismatch")

    # ---- record an evidence clip for the mismatch ----
    print("\nRecording an evidence clip for the mismatch")
    clip_id = store.record_clip(
        clip_id="CLIP-EVT-200", event_id=mism_id, request_id="CLIP-200",
        reason="barcode_mismatch", zone_id=2, camera_id=2, box_id="BOX-200",
        event_timestamp=now + 10, clip_start=now - 20, clip_end=now + 40,
        segment_file="data/video/cam2_2026-06-03_13-45-47.mp4", offset_sec=60.0,
        file_path="data/clips/clip_CLIP-200.mp4", notes="camera vs scanner",
    )
    check("got a clip id", bool(clip_id))

    # ---- search by barcode: the shared camera barcode hits BOTH events ----
    print("\nSearch by barcode 0687456223537 (both events read it on camera)")
    results = store.search_by_barcode("0687456223537")
    check("search returns 2 events", len(results) == 2, f"got {len(results)}")
    # newest first -> mismatch (now+10) should be first
    check("newest event first", results and results[0]["event_id"] == mism_id)
    # the mismatch event should carry its clip
    mism_result = next((r for r in results if r["event_id"] == mism_id), None)
    check("mismatch event has its clip attached",
          mism_result and len(mism_result["clips"]) == 1)
    check("attached clip points to the right file",
          mism_result and mism_result["clips"][0]["file_path"].endswith("clip_CLIP-200.mp4"))

    # ---- search by the scanner-only barcode hits ONLY the mismatch ----
    print("\nSearch by 9999999999999 (only the scanner side of the mismatch)")
    only = store.search_by_barcode("9999999999999")
    check("returns exactly 1 event", len(only) == 1, f"got {len(only)}")

    # ---- search by box ----
    print("\nSearch by box id")
    box = store.search_by_box("BOX-100")
    check("box search finds the match event", len(box) == 1 and box[0]["event_id"] == match_id)

    # ---- cloud-upload tracking (the future Zoho sync hook) ----
    print("\nCloud-upload tracking")
    pending = store.pending_uploads()
    check("clip starts as pending upload", len(pending) == 1)
    store.mark_uploaded("CLIP-EVT-200", "https://zoho.example/clips/CLIP-200.mp4")
    pending = store.pending_uploads()
    check("nothing pending after mark_uploaded", len(pending) == 0)

    # ---- stats ----
    print("\nStats")
    s = store.stats()
    check("stats: 2 events", s["events"] == 2, str(s))
    check("stats: 1 mismatch", s["mismatches"] == 1)
    check("stats: 1 clip", s["clips"] == 1)
    check("stats: 0 pending", s["pending_upload"] == 0)

    # ---- persistence: reopen a fresh store on the same file ----
    print("\nPersistence: reopen the DB in a brand-new EventStore instance")
    store2 = EventStore(db_path=DB_PATH)
    again = store2.search_by_barcode("0687456223537")
    check("data still there after reopen", len(again) == 2, f"got {len(again)}")
    check("uploaded flag persisted",
          store2.get_event(mism_id)["clips"][0]["uploaded"] == 1)

    print("\n" + "=" * 50)
    print(f"  RESULTS: {_passed} passed, {_failed} failed")
    print("=" * 50)
    print(f"\nThe database file is at: {DB_PATH}")
    print("This is the local mirror of the future Zoho tables.")
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    run()