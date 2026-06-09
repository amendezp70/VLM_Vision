# vlm_vision/local_agent/traceability/clip_request_processor.py
"""
ClipRequestProcessor -- the bridge between Process 2 (Traceability) and the
recorded video segments produced by Process 3 (Video Recorder).

EvidenceGenerator writes clip-request JSON files into data/clip_requests/.
Each request says, in effect: "camera C had an event at unix time T."
This processor turns that into an actual clip:

  1. read each request JSON,
  2. find the recorded segment(s) covering the +/- margin window around T,
  3. cut the clip -- from one segment (via the existing ClipExtractor), or,
     when the window crosses a 5-minute segment boundary, stitch the pieces
     from two adjacent segments into ONE continuous clip,
  4. record the clip + move the request to processed/.

Why the stitch matters: recordings roll into a new file every 5 minutes. An
event in the last ~30s (or first ~30s) of a segment has its surrounding
footage split across two files. Without stitching the clip would be cut short
at the boundary -- exactly the evidence you can't afford to lose in a dispute.

It does NOT modify any Process 3 file. It READS the segment files and reuses
the verified ClipExtractor for the common single-segment case.
"""
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

import cv2

from local_agent.video.clip_extractor import ClipExtractor

logger = logging.getLogger(__name__)

# Segment files look like:  cam2_2026-05-28_14-02-59.mp4
_SEGMENT_RE = re.compile(r"^cam(\d+)_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.mp4$")
_SEGMENT_TIME_FMT = "%Y-%m-%d_%H-%M-%S"
_BOUNDARY_EPS = 0.5  # seconds of slack before we bother stitching


@dataclass
class ProcessResult:
    """Outcome of trying to turn one request into a clip."""
    request_id: str
    status: str          # extracted | stitched | no_segment | extract_failed | bad_request
    clip_path: str = ""
    segment_file: str = ""
    offset_sec: float = 0.0
    detail: str = ""


@dataclass
class _Segment:
    start: float
    path: str
    seg_id: str
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


class ClipRequestProcessor:
    def __init__(
        self,
        requests_dir: str = "data/clip_requests",
        video_dir: str = "data/video",
        output_dir: str = "data/clips",
        segment_seconds: int = 300,
        event_store=None,
    ):
        self.requests_dir = requests_dir
        self.video_dir = video_dir
        self.output_dir = output_dir
        self.segment_seconds = segment_seconds
        self.event_store = event_store
        self.processed_dir = os.path.join(requests_dir, "processed")
        self.failed_dir = os.path.join(requests_dir, "failed")
        os.makedirs(self.processed_dir, exist_ok=True)
        os.makedirs(self.failed_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        self.extractor = ClipExtractor(output_dir=output_dir)

    def process_all(self) -> List[ProcessResult]:
        """Process every *.json request sitting in the requests folder."""
        results = []
        for name in sorted(os.listdir(self.requests_dir)):
            path = os.path.join(self.requests_dir, name)
            if name.endswith(".json") and os.path.isfile(path):
                results.append(self.process_request(path))
        return results

    def process_request(self, request_path: str) -> ProcessResult:
        name = os.path.basename(request_path)
        try:
            with open(request_path, "r") as f:
                req = json.load(f)
        except Exception as e:
            self._move(request_path, self.failed_dir)
            return ProcessResult(name, "bad_request", detail=f"could not read JSON: {e}")

        request_id = req.get("request_id", name)
        camera_id = req.get("camera_id")
        event_ts = req.get("event_timestamp")
        if camera_id is None or event_ts is None:
            self._move(request_path, self.failed_dir)
            return ProcessResult(request_id, "bad_request",
                                 detail="missing camera_id or event_timestamp")
        camera_id = int(camera_id)
        event_ts = float(event_ts)

        # Honour the margin the generator chose: (clip_end - clip_start) / 2.
        margin = 30.0
        cs, ce = req.get("clip_start"), req.get("clip_end")
        if cs is not None and ce is not None and ce > cs:
            margin = (ce - cs) / 2.0

        segments = self._all_segments(camera_id)
        primary = self._segment_covering(segments, event_ts)
        if primary is None:
            # Leave the request in place -- the segment may not be written yet.
            return ProcessResult(request_id, "no_segment",
                                 detail=f"no segment for cam{camera_id} covering t={event_ts}")

        offset = event_ts - primary.start
        window_start = event_ts - margin
        window_end = event_ts + margin

        # Does the window spill past either edge of the primary segment, AND is
        # there an adjacent segment with that footage?
        overlapping = [s for s in segments
                       if s.end > window_start + _BOUNDARY_EPS
                       and s.start < window_end - _BOUNDARY_EPS]
        spans_boundary = len(overlapping) > 1

        if not spans_boundary:
            # Common case: single segment -> use the verified extractor as-is.
            clip = self.extractor.extract(
                segment_file=primary.path, offset_sec=offset,
                event_id=request_id, segment_id=primary.seg_id,
                margin_sec=int(round(margin)),
            )
            if clip is None:
                self._move(request_path, self.failed_dir)
                return ProcessResult(request_id, "extract_failed", segment_file=primary.path,
                                     offset_sec=offset, detail="ClipExtractor returned None")
            status, clip_path = "extracted", clip.file_path
            seg_label = primary.path
        else:
            # Boundary case: stitch the overlapping segments into one clip.
            out_path = os.path.join(self.output_dir, f"clip_{request_id}_stitched.mp4")
            ok = self._stitch(overlapping, window_start, window_end, out_path)
            if not ok:
                self._move(request_path, self.failed_dir)
                return ProcessResult(request_id, "extract_failed",
                                     segment_file=primary.path, offset_sec=offset,
                                     detail="stitch produced no frames")
            status, clip_path = "stitched", out_path
            seg_label = " + ".join(os.path.basename(s.path) for s in overlapping)

        self._move(request_path, self.processed_dir)

        if self.event_store is not None:
            try:
                self.event_store.record_clip(
                    clip_id=request_id, request_id=request_id,
                    event_timestamp=req.get("event_timestamp"),
                    reason=req.get("reason"), zone_id=req.get("zone_id"),
                    camera_id=req.get("camera_id"), box_id=req.get("box_id"),
                    clip_start=req.get("clip_start"), clip_end=req.get("clip_end"),
                    segment_file=seg_label, offset_sec=offset,
                    file_path=clip_path, notes=req.get("notes", ""),
                )
            except Exception as e:
                logger.error("EventStore.record_clip failed for %s: %s", request_id, e)

        return ProcessResult(request_id, status, clip_path=clip_path,
                             segment_file=seg_label, offset_sec=offset, detail="ok")

    # ---- segment discovery -------------------------------------------------

    def _all_segments(self, camera_id: int) -> List[_Segment]:
        """All segments for a camera, sorted by start time, with real durations."""
        if not os.path.isdir(self.video_dir):
            return []
        out = []
        for name in os.listdir(self.video_dir):
            m = _SEGMENT_RE.match(name)
            if not m or int(m.group(1)) != camera_id:
                continue
            try:
                start = datetime.strptime(m.group(2), _SEGMENT_TIME_FMT).timestamp()
            except ValueError:
                continue
            path = os.path.join(self.video_dir, name)
            seg_id = f"cam{camera_id}_{datetime.fromtimestamp(start).strftime('%Y%m%d%H%M%S')}"
            out.append(_Segment(start, path, seg_id, self._duration(path)))
        out.sort(key=lambda s: s.start)
        return out

    @staticmethod
    def _duration(path: str) -> float:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return frames / fps if fps else 0.0

    @staticmethod
    def _segment_covering(segments: List[_Segment], event_ts: float) -> Optional[_Segment]:
        """The segment whose recording window contains event_ts (latest start
        at or before it)."""
        chosen = None
        for s in segments:
            if s.start <= event_ts:
                chosen = s
            else:
                break
        return chosen

    # ---- stitching ---------------------------------------------------------

    def _stitch(self, segments: List[_Segment], window_start: float,
                window_end: float, out_path: str) -> bool:
        """Cut the overlapping sub-range from each segment (in time order) and
        write them into a single continuous clip. Returns True if any frames
        were written."""
        writer = None
        fps = 15.0
        size = None
        total = 0
        try:
            for seg in sorted(segments, key=lambda s: s.start):
                sub_start = max(0.0, window_start - seg.start)
                sub_end = min(seg.duration, window_end - seg.start)
                if sub_end <= sub_start:
                    continue
                cap = cv2.VideoCapture(seg.path)
                if not cap.isOpened():
                    continue
                seg_fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
                start_frame = int(sub_start * seg_fps)
                end_frame = int(sub_end * seg_fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                cur = start_frame
                while cur < end_frame:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if writer is None:
                        h, w = frame.shape[:2]
                        size = (w, h)
                        fps = seg_fps
                        writer = cv2.VideoWriter(
                            out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
                    # guard against a resolution change between segments
                    if (frame.shape[1], frame.shape[0]) != size:
                        frame = cv2.resize(frame, size)
                    writer.write(frame)
                    total += 1
                    cur += 1
                cap.release()
        finally:
            if writer is not None:
                writer.release()
        if total == 0:
            logger.warning("Stitch wrote 0 frames for %s", out_path)
            return False
        return True

    def _move(self, src: str, dest_dir: str) -> None:
        try:
            dest = os.path.join(dest_dir, os.path.basename(src))
            if os.path.exists(dest):
                os.remove(dest)
            shutil.move(src, dest)
        except Exception as e:
            logger.error("Could not move %s -> %s: %s", src, dest_dir, e)