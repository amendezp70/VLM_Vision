#!/usr/bin/env python
"""
test_clip_extractor.py  --  standalone test for clip_extractor.py
Run from the vlm_vision/ directory with venv active:
    python test_clip_extractor.py
Makes its own 100s test video (timestamp burned into each frame), runs
ClipExtractor across several scenarios, prints PASS/FAIL, and leaves the
clips in test_clip_output/ so you can open them and verify by eye.
"""

import os
import sys
import cv2
import numpy as np

from local_agent.video.clip_extractor import ClipExtractor, EvidenceClip

TEST_DIR = "test_clip_output"
SOURCE_VIDEO = os.path.join(TEST_DIR, "synthetic_source.mp4")
FPS = 15
DURATION_SEC = 100
WIDTH, HEIGHT = 640, 480
DUR_TOL = 2.5  # seeking inside compressed mp4 is only ~frame-accurate

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


def make_synthetic_video():
    os.makedirs(TEST_DIR, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(SOURCE_VIDEO, fourcc, FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        print("ERROR: could not open VideoWriter. mp4v codec may be missing.")
        sys.exit(1)
    for i in range(FPS * DURATION_SEC):
        sec = i / FPS
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        frame[:] = (int(sec * 2) % 255, 60, 120)
        cv2.putText(frame, f"t = {sec:6.2f} s", (40, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
        cv2.putText(frame, f"frame {i}", (40, 310),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
        writer.write(frame)
    writer.release()
    print(f"Created source video: {SOURCE_VIDEO}  ({DURATION_SEC}s @ {FPS}fps)\n")


def measured_duration(path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return (frames / fps) if fps else 0.0


def run():
    make_synthetic_video()
    extractor = ClipExtractor(output_dir=TEST_DIR, margin_sec=30)

    print("Test 1: offset=50s, default margin=30s  (expect window 20s -> 80s)")
    clip = extractor.extract(SOURCE_VIDEO, offset_sec=50,
                             event_id="evt1", segment_id="seg1")
    if check("returned an EvidenceClip", isinstance(clip, EvidenceClip)):
        check("output file was created", os.path.exists(clip.file_path))
        check("clip_start_sec == 20", abs(clip.clip_start_sec - 20) < 0.1,
              f"got {clip.clip_start_sec}")
        check("clip_end_sec == 80", abs(clip.clip_end_sec - 80) < 0.1,
              f"got {clip.clip_end_sec}")
        d = measured_duration(clip.file_path)
        check("clip is ~60s long", abs(d - 60) <= DUR_TOL, f"measured {d:.2f}s")

    print("\nTest 2: offset=5s, margin=30s  (start clamped to 0 -> 0s -> 35s)")
    clip = extractor.extract(SOURCE_VIDEO, offset_sec=5,
                             event_id="evt2", segment_id="seg1")
    if check("returned an EvidenceClip", isinstance(clip, EvidenceClip)):
        check("clip_start_sec clamped to 0", abs(clip.clip_start_sec - 0) < 0.1,
              f"got {clip.clip_start_sec}")
        check("clip_end_sec == 35", abs(clip.clip_end_sec - 35) < 0.1,
              f"got {clip.clip_end_sec}")
        d = measured_duration(clip.file_path)
        check("clip is ~35s long", abs(d - 35) <= DUR_TOL, f"measured {d:.2f}s")

    print("\nTest 3: offset=95s, margin=30s  (end clamped to 100 -> 65s -> 100s)")
    clip = extractor.extract(SOURCE_VIDEO, offset_sec=95,
                             event_id="evt3", segment_id="seg1")
    if check("returned an EvidenceClip", isinstance(clip, EvidenceClip)):
        check("clip_start_sec == 65", abs(clip.clip_start_sec - 65) < 0.1,
              f"got {clip.clip_start_sec}")
        check("clip_end_sec clamped to ~100", abs(clip.clip_end_sec - 100) < 0.5,
              f"got {clip.clip_end_sec}")

    print("\nTest 4: offset=50s, margin override=10s  (expect window 40s -> 60s)")
    clip = extractor.extract(SOURCE_VIDEO, offset_sec=50,
                             event_id="evt4", segment_id="seg1", margin_sec=10)
    if check("returned an EvidenceClip", isinstance(clip, EvidenceClip)):
        check("clip_start_sec == 40", abs(clip.clip_start_sec - 40) < 0.1,
              f"got {clip.clip_start_sec}")
        check("clip_end_sec == 60", abs(clip.clip_end_sec - 60) < 0.1,
              f"got {clip.clip_end_sec}")
        d = measured_duration(clip.file_path)
        check("clip is ~20s long", abs(d - 20) <= DUR_TOL, f"measured {d:.2f}s")

    print("\nTest 5: nonexistent source file  (expect None, handled gracefully)")
    clip = extractor.extract("does_not_exist.mp4", offset_sec=10,
                             event_id="evt5", segment_id="seg1")
    check("returned None for missing file", clip is None)

    print("\n" + "=" * 48)
    print(f"  RESULTS: {_passed} passed, {_failed} failed")
    print("=" * 48)
    print(f"\nOpen the clips in '{TEST_DIR}\\' and read the burned-in")
    print("timestamps to confirm each clip grabbed the expected window.")
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    run()