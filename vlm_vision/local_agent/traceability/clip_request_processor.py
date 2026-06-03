# vlm_vision/local_agent/traceability/clip_request_processor.py
"""
ClipRequestProcessor -- the bridge between Process 2 (Traceability) and the
recorded video segments produced by Process 3 (Video Recorder).

EvidenceGenerator writes clip-request JSON files into data/clip_requests/.
Each request says, in effect: "camera C had an event at unix time T."
This processor turns that into an actual clip:

  1. read each request JSON,
  2. find the recorded segment file whose time window contains T,
  3. convert T into an offset (seconds from the START of that file),
  4. call the existing ClipExtractor to cut the clip,
  5. move the handled request into a 'processed/' (or 'failed/') subfolder
     so it is not processed twice.

It does NOT modify any Process 3 file. It only READS the segment files the
recorder writes and REUSES the already-verified ClipExtractor.
"""
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from local_agent.video.clip_extractor import ClipExtractor

logger = logging.getLogger(__name__)

# Segment files look like:  cam2_2026-05-28_14-02-59.mp4
# (this exactly matches VideoSegmenter._open_segment)
_SEGMENT_RE = re.compile(r"^cam(\d+)_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.mp4$")
_SEGMENT_TIME_FMT = "%Y-%m-%d_%H-%M-%S"


@dataclass
class ProcessResult:
    """Outcome of trying to turn one request into a clip."""
    request_id: str
    status: str          # extracted | no_segment | extract_failed | bad_request
    clip_path: str = ""
    segment_file: str = ""
    offset_sec: float = 0.0
    detail: str = ""


class ClipRequestProcessor:
    def __init__(
        self,
        requests_dir: str = "data/clip_requests",
        video_dir: str = "data/video",
        output_dir: str = "data/clips",
        segment_seconds: int = 300,
    ):
        self.requests_dir = requests_dir
        self.video_dir = video_dir
        self.segment_seconds = segment_seconds
        self.processed_dir = os.path.join(requests_dir, "processed")
        self.failed_dir = os.path.join(requests_dir, "failed")
        os.makedirs(self.processed_dir, exist_ok=True)
        os.makedirs(self.failed_dir, exist_ok=True)
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

        # Honour the margin the generator chose: (clip_end - clip_start) / 2.
        margin = None
        cs, ce = req.get("clip_start"), req.get("clip_end")
        if cs is not None and ce is not None and ce > cs:
            margin = int(round((ce - cs) / 2))

        found = self._find_segment_for(int(camera_id), float(event_ts))
        if found is None:
            # Leave the request in place -- the segment may simply not be
            # written to disk yet (recorder still filling the current file).
            return ProcessResult(request_id, "no_segment",
                                 detail=f"no segment for cam{camera_id} covering t={event_ts}")

        segment_file, segment_start, segment_id = found
        offset = float(event_ts) - segment_start

        clip = self.extractor.extract(
            segment_file=segment_file,
            offset_sec=offset,
            event_id=request_id,
            segment_id=segment_id,
            margin_sec=margin,
        )
        if clip is None:
            self._move(request_path, self.failed_dir)
            return ProcessResult(request_id, "extract_failed", segment_file=segment_file,
                                 offset_sec=offset, detail="ClipExtractor returned None")

        self._move(request_path, self.processed_dir)
        return ProcessResult(request_id, "extracted", clip_path=clip.file_path,
                             segment_file=segment_file, offset_sec=offset, detail="ok")

    def _find_segment_for(self, camera_id: int, event_ts: float
                          ) -> Optional[Tuple[str, float, str]]:
        """Return (file_path, segment_start_unix, segment_id) for the segment
        on `camera_id` whose recording window contains `event_ts`, or None."""
        if not os.path.isdir(self.video_dir):
            return None

        candidates = []
        for name in os.listdir(self.video_dir):
            m = _SEGMENT_RE.match(name)
            if not m or int(m.group(1)) != camera_id:
                continue
            try:
                start = datetime.strptime(m.group(2), _SEGMENT_TIME_FMT).timestamp()
            except ValueError:
                continue
            seg_id = f"cam{camera_id}_{datetime.fromtimestamp(start).strftime('%Y%m%d%H%M%S')}"
            candidates.append((start, name, seg_id))

        if not candidates:
            return None

        candidates.sort()  # ascending by start time
        chosen = None
        for start, name, seg_id in candidates:
            if start <= event_ts:
                chosen = (start, name, seg_id)
            else:
                break
        if chosen is None:
            return None

        start, name, seg_id = chosen
        if event_ts - start > self.segment_seconds + 5:
            logger.warning(
                "Event t=%s is %.0fs past the start of segment %s (window ~%ss). "
                "Footage past the segment end is in the NEXT file; this clip will "
                "be clamped to the end of this segment.",
                event_ts, event_ts - start, name, self.segment_seconds)
        return (os.path.join(self.video_dir, name), start, seg_id)

    def _move(self, src: str, dest_dir: str) -> None:
        try:
            dest = os.path.join(dest_dir, os.path.basename(src))
            if os.path.exists(dest):
                os.remove(dest)
            shutil.move(src, dest)
        except Exception as e:
            logger.error("Could not move %s -> %s: %s", src, dest_dir, e)