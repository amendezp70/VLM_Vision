# vlm_vision/local_agent/video/clip_extractor.py
"""
On-demand extraction of evidence clips from video segments.
Given a segment file and an offset, extracts ±margin seconds
and saves as a separate MP4 file.
"""
import os
from dataclasses import dataclass
from typing import Optional

import cv2


@dataclass
class EvidenceClip:
    clip_id: str
    event_id: str
    segment_id: str
    clip_start_sec: float
    clip_end_sec: float
    file_path: str
    cloud_url: str = ""
    generated_at: float = 0.0
    retained_indefinitely: bool = True


class ClipExtractor:
    """Extracts short evidence clips from video segment files."""

    def __init__(
        self,
        output_dir: str,
        margin_sec: int = 30,
    ):
        self._output_dir = output_dir
        self._margin_sec = margin_sec
        os.makedirs(output_dir, exist_ok=True)

    def extract(
        self,
        segment_file: str,
        offset_sec: float,
        event_id: str,
        segment_id: str,
        margin_sec: Optional[int] = None,
    ) -> Optional[EvidenceClip]:
        """Extract a clip from segment_file centered on offset_sec.

        Returns an EvidenceClip with the local file_path, or None if extraction fails.
        """
        if not os.path.exists(segment_file):
            return None

        margin = margin_sec if margin_sec is not None else self._margin_sec
        cap = cv2.VideoCapture(segment_file)
        if not cap.isOpened():
            return None

        fps = cap.get(cv2.CAP_PROP_FPS) or 15
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        total_duration = total_frames / fps

        clip_start = max(0, offset_sec - margin)
        clip_end = min(total_duration, offset_sec + margin)

        if clip_start >= clip_end:
            cap.release()
            return None

        # Seek to start frame
        start_frame = int(clip_start * fps)
        end_frame = int(clip_end * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        # Read frame dimensions
        ok, sample = cap.read()
        if not ok:
            cap.release()
            return None
        h, w = sample.shape[:2]
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        # Write clip
        clip_filename = f"clip_{event_id}_{segment_id}.mp4"
        clip_path = os.path.join(self._output_dir, clip_filename)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(clip_path, fourcc, fps, (w, h))

        current_frame = start_frame
        while current_frame < end_frame:
            ok, frame = cap.read()
            if not ok:
                break
            writer.write(frame)
            current_frame += 1

        writer.release()
        cap.release()

        import time
        clip_id = f"clip_{event_id}"
        return EvidenceClip(
            clip_id=clip_id,
            event_id=event_id,
            segment_id=segment_id,
            clip_start_sec=clip_start,
            clip_end_sec=clip_end,
            file_path=clip_path,
            generated_at=time.time(),
        )
