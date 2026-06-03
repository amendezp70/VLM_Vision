#!/usr/bin/env python
"""
test_clip_request_processor.py  --  end-to-end test of the bridge between
the traceability events and the recorded video segments.

RUN (from the vlm_vision/ directory, venv active):
    python test_clip_request_processor.py

WHAT IT DOES (no camera / no real recording needed):
  1. Makes a fake recorded segment named EXACTLY the way VideoSegmenter names
     real files -- cam2_<start-time>.mp4 -- with the timestamp burned into
     every frame.
  2. Uses your REAL EvidenceGenerator to write a real clip-request JSON for an
     event 60s into that segment (this proves the two real modules agree on
     the JSON contract -- nothing is faked).
  3. Runs ClipRequestProcessor, which must find the segment, compute the right
     offset, and cut the clip via your already-verified ClipExtractor.
  4. Also checks the "no segment yet" and "garbage request" paths.
  5. Leaves clips in test_bridge_output/clips/ so you can open them and read
     the burned-in timestamps to confirm the right window was cut.
"""

import os
import shutil
import sys
import time
from datetime import datetime

import cv2
import numpy as np

from local_agent.traceability.evidence_generator import EvidenceGenerator, EvidenceReason
from local_agent.traceability.clip_request_processor import ClipRequestProcessor

ROOT = "test_bridge_output"
VIDEO_DIR = os.path.join(ROOT, "video")
REQ_DIR = os.path.join(ROOT, "clip_requests")
CLIP_DIR = os.path.join(ROOT, "clips")
FPS = 15
SEG_DURATION = 180          # the fake segment is 3 minutes long
WIDTH, HEIGHT = 640, 480

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


def fresh_dirs():
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT)
    for d in (VIDEO_DIR, REQ_DIR, CLIP_DIR):
        os.makedirs(d, exist_ok=True)


def make_segment(camera_id, start_unix):
    """Write a fake segment file named the same way VideoSegmenter names them."""
    dt = datetime.fromtimestamp(start_unix)
    filename = f"cam{camera_id}_{dt.strftime('%Y-%m-%d_%H-%M-%S')}.mp4"
    path = os.path.join(VIDEO_DIR, filename)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        print("ERROR: could not open VideoWriter (mp4v codec missing?)")
        sys.exit(1)
    for i in range(FPS * SEG_DURATION):
        sec = i / FPS
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        frame[:] = (int(sec * 2) % 255, 60, 120)
        cv2.putText(frame, f"seg t = {sec:6.2f} s", (30, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
        writer.write(frame)
    writer.release()
    print(f"Created fake segment: {filename}  ({SEG_DURATION}s, starts at unix {int(start_unix)})")
    return path


def run():
    fresh_dirs()

    # Whole-second start time well in the past so it never collides with "now".
    seg_start = float(int(time.time()) - 5000)
    make_segment(camera_id=2, start_unix=seg_start)

    # Event happens 60s into that segment. Zone 1 maps to camera 2 in the
    # generator's default zone_camera_map, so this lands on our fake segment.
    event_ts = seg_start + 60.0

    gen = EvidenceGenerator(requests_dir=REQ_DIR, clip_margin_sec=30.0)
    req = gen.request_clip(
        zone_id=1,
        event_timestamp=event_ts,
        reason=EvidenceReason.BARCODE_MISMATCH,
        box_id="BOX-TEST-1",
        barcode_camera="0687456223537",
        barcode_scanner="0687456999999",
        notes="test mismatch",
    )
    print(f"EvidenceGenerator wrote request {req.request_id} (camera_id={req.camera_id})\n")
    check("generator routed zone 1 -> camera 2", req.camera_id == 2)

    processor = ClipRequestProcessor(
        requests_dir=REQ_DIR, video_dir=VIDEO_DIR, output_dir=CLIP_DIR, segment_seconds=300
    )

    # ---- Main path: request should resolve to the segment and cut a clip ----
    print("\nMain path: process the real request")
    results = processor.process_all()
    check("exactly one result", len(results) == 1, f"got {len(results)}")
    r = results[0] if results else None
    if r:
        check("status is 'extracted'", r.status == "extracted", r.detail)
        check("offset ~= 60s", abs(r.offset_sec - 60) <= 1.5, f"got {r.offset_sec:.2f}")
        check("clip file exists", bool(r.clip_path) and os.path.exists(r.clip_path))
        # clip should be ~60s (event +/- 30, fully inside the segment)
        if r.clip_path and os.path.exists(r.clip_path):
            cap = cv2.VideoCapture(r.clip_path)
            dur = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) / (cap.get(cv2.CAP_PROP_FPS) or FPS)
            cap.release()
            check("clip is ~60s long", abs(dur - 60) <= 2.5, f"measured {dur:.2f}s")
        check("request moved to processed/",
              os.path.exists(os.path.join(REQ_DIR, "processed", f"{req.request_id}.json")))
        check("request no longer in main folder",
              not os.path.exists(os.path.join(REQ_DIR, f"{req.request_id}.json")))

    # ---- No-segment path: event on a camera with no footage stays pending ----
    print("\nNo-segment path: request for a camera with no recordings")
    gen2 = EvidenceGenerator(requests_dir=REQ_DIR, clip_margin_sec=30.0)
    req2 = gen2.request_clip(zone_id=4, event_timestamp=event_ts,  # zone 4 -> camera 5
                             reason=EvidenceReason.PALLET_ERROR, notes="no footage")
    results = processor.process_all()
    r2 = next((x for x in results if x.request_id == req2.request_id), None)
    if check("got a result for the no-footage request", r2 is not None):
        check("status is 'no_segment'", r2.status == "no_segment", r2.detail)
        check("request left in place for retry",
              os.path.exists(os.path.join(REQ_DIR, f"{req2.request_id}.json")))

    # ---- Bad-request path: a non-JSON .json file is quarantined ----
    print("\nBad-request path: corrupt request file")
    bad_path = os.path.join(REQ_DIR, "CLIP-broken.json")
    with open(bad_path, "w") as f:
        f.write("this is not json {{{")
    results = processor.process_all()
    rb = next((x for x in results if x.request_id == "CLIP-broken.json"), None)
    if check("got a result for the broken file", rb is not None):
        check("status is 'bad_request'", rb.status == "bad_request", rb.detail)
        check("broken file moved to failed/",
              os.path.exists(os.path.join(REQ_DIR, "failed", "CLIP-broken.json")))

    print("\n" + "=" * 50)
    print(f"  RESULTS: {_passed} passed, {_failed} failed")
    print("=" * 50)
    print(f"\nOpen {CLIP_DIR}\\ and play the clip -- the burned-in 'seg t' value")
    print("should run from ~30s to ~90s (the event was at seg t = 60s).")
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    run()