#!/usr/bin/env python
"""
demo_pipeline.py  --  full traceability pipeline on your laptop, no factory.

RUN (from the vlm_vision/ directory, venv active):
    python demo_pipeline.py

It runs the REAL components end to end against simulated input:

  RecordingEventCorrelator  (records every event to the EventStore)
        |
        |-- a MATCH    (camera and scanner agree)      -> stored, no clip
        |-- a MISMATCH (camera and scanner disagree)   -> stored + alert
                  |
                  v
            EvidenceGenerator  (writes a clip-request JSON)
                  |
                  v
            ClipRequestProcessor  (finds the segment, cuts the clip,
                                   records the clip linked to its event)
                  |
                  v
            EventStore  -- search by barcode returns the event WITH its clip

The only thing faked is the input: barcode "reads" and one pre-made video
segment. Everything else is the production code path. This is the demo you
can show: type a barcode, get back what happened and the proof clip.
"""

import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

from local_agent.traceability.event_store import EventStore
from local_agent.traceability.recording_correlator import RecordingEventCorrelator
from local_agent.traceability.evidence_generator import EvidenceGenerator
from local_agent.traceability.clip_request_processor import ClipRequestProcessor

ROOT = "demo_output"
VIDEO_DIR = os.path.join(ROOT, "video")
REQ_DIR = os.path.join(ROOT, "clip_requests")
CLIP_DIR = os.path.join(ROOT, "clips")
DB_PATH = os.path.join(ROOT, "traceability.db")

GOOD_BARCODE = "0687456223537"
BAD_BARCODE = "9999999999999"

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


# A barcode "read". The real BarcodeReader produces richer objects, but the
# correlator only uses .value and .timestamp, so this stands in cleanly.
@dataclass
class Read:
    value: str
    timestamp: float


def make_segment(camera_id, start_unix, seconds=150, fps=10):
    """Write one fake video segment named the way VideoSegmenter names them."""
    os.makedirs(VIDEO_DIR, exist_ok=True)
    dt = datetime.fromtimestamp(start_unix)
    name = f"cam{camera_id}_{dt.strftime('%Y-%m-%d_%H-%M-%S')}.mp4"
    path = os.path.join(VIDEO_DIR, name)
    w, h = 320, 240
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        print("ERROR: VideoWriter could not open (mp4v codec missing?)")
        sys.exit(1)
    for i in range(seconds * fps):
        sec = i / fps
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:] = (int(sec * 2) % 255, 60, 120)
        cv2.putText(frame, f"seg t={sec:5.1f}s", (20, 130),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    print(f"Prepared video segment {name} ({seconds}s)\n")
    return name


def run():
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT)
    for d in (VIDEO_DIR, REQ_DIR, CLIP_DIR):
        os.makedirs(d, exist_ok=True)

    # Zone 2 (barcode scan) maps to camera 3 in EvidenceGenerator's default map,
    # so the evidence request will point at camera 3 -- prepare that segment.
    t0 = time.time()
    seg_start = int(t0) - 60          # event will land ~60s into the segment
    make_segment(camera_id=3, start_unix=seg_start)

    # --- wire the real pipeline ---
    store = EventStore(db_path=DB_PATH)
    correlator = RecordingEventCorrelator.from_env(store)        # zone_id=2
    evidence = EvidenceGenerator(requests_dir=REQ_DIR, clip_margin_sec=30.0)
    correlator.on_alert(evidence.on_correlation_event)
    processor = ClipRequestProcessor(
        requests_dir=REQ_DIR, video_dir=VIDEO_DIR, output_dir=CLIP_DIR,
        segment_seconds=300, event_store=store,
    )

    # --- simulate a GOOD box: camera and scanner agree -> MATCH, no clip ---
    print("Simulating a MATCH (camera == scanner)")
    now = time.time()
    correlator.add_camera_read(Read(GOOD_BARCODE, now), box_id="BOX-OK")
    match_event = correlator.add_scanner_read(Read(GOOD_BARCODE, now + 0.3), box_id="BOX-OK")
    check("match event produced", match_event is not None and match_event.is_verified)

    # --- simulate a BAD box: camera and scanner disagree -> MISMATCH + clip ---
    print("Simulating a MISMATCH (camera != scanner)")
    now = time.time()
    correlator.add_camera_read(Read(GOOD_BARCODE, now), box_id="BOX-BAD")
    mism_event = correlator.add_scanner_read(Read(BAD_BARCODE, now + 0.3), box_id="BOX-BAD")
    check("mismatch event produced", mism_event is not None and not mism_event.is_verified)

    # the mismatch should have written exactly one clip request
    pending_files = [f for f in os.listdir(REQ_DIR) if f.endswith(".json")]
    check("one clip request was written", len(pending_files) == 1, f"got {len(pending_files)}")

    # --- run the bridge: cut the clip and record it ---
    print("\nProcessing clip requests")
    results = processor.process_all()
    extracted = [r for r in results if r.status == "extracted"]
    check("one clip extracted", len(extracted) == 1, f"got {len(extracted)}")
    if extracted:
        check("clip file exists", os.path.exists(extracted[0].clip_path))

    # --- the payoff: search by barcode, get the event AND its clip ---
    print("\nSearching the store by barcode", GOOD_BARCODE)
    hits = store.search_by_barcode(GOOD_BARCODE)
    check("search returns 2 events (match + mismatch)", len(hits) == 2, f"got {len(hits)}")

    mism_hit = next((h for h in hits if h["match_status"] == "mismatch"), None)
    check("mismatch event found in search", mism_hit is not None)
    if mism_hit:
        check("mismatch event has its clip linked", len(mism_hit["clips"]) == 1,
              f"clips={len(mism_hit['clips'])}")
        if mism_hit["clips"]:
            check("linked clip file path present",
                  bool(mism_hit["clips"][0]["file_path"]))

    match_hit = next((h for h in hits if h["match_status"] == "match"), None)
    check("match event has no clip (nothing to prove)",
          match_hit is not None and len(match_hit["clips"]) == 0)

    # --- show what a manager would see ---
    print("\n" + "-" * 58)
    print("WHAT A MANAGER SEES when searching barcode " + GOOD_BARCODE + ":")
    for h in hits:
        when = datetime.fromtimestamp(h["event_timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        status = h["match_status"].upper()
        line = f"  {when}  zone {h['zone_id']}  box {h['box_id']}  -> {status}"
        print(line)
        for c in h["clips"]:
            print(f"        evidence clip: {c['file_path']}")
    print("-" * 58)
    print("Store stats:", store.stats())

    print("\n" + "=" * 58)
    print(f"  RESULTS: {_passed} passed, {_failed} failed")
    print("=" * 58)
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    run()