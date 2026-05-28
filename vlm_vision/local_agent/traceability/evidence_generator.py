"""
EvidenceGenerator — generates evidence clip requests when bad events occur.
When a barcode mismatch or other error is detected, this module writes
a clip extraction request that the Video Recorder process picks up
and cuts a ±30 second clip from the stored video.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from local_agent.traceability.event_correlator import CorrelationEvent, MatchStatus

logger = logging.getLogger(__name__)


class EvidenceReason(Enum):
    """Why an evidence clip was requested."""
    BARCODE_MISMATCH = "barcode_mismatch"       # Camera vs scanner disagreed
    BOX_UNSEALED = "box_unsealed"               # Box left unsealed at Zone 3
    WRONG_SKU = "wrong_sku"                     # Wrong product detected at Zone 1
    MANUAL_REQUEST = "manual_request"           # Dashboard user requested clip
    PALLET_ERROR = "pallet_error"               # Error during pallet assembly


@dataclass
class EvidenceRequest:
    """
    A request to extract a video clip as evidence.
    Written to disk as a JSON file — the Video Recorder
    process watches the requests folder and processes these.
    """
    request_id: str
    zone_id: int
    camera_id: int
    event_timestamp: float          # The moment the event occurred
    clip_start: float               # event_timestamp - margin
    clip_end: float                 # event_timestamp + margin
    reason: EvidenceReason
    box_id: Optional[str] = None
    pallet_id: Optional[str] = None
    barcode_camera: Optional[str] = None
    barcode_scanner: Optional[str] = None
    notes: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "request_id": self.request_id,
            "zone_id": self.zone_id,
            "camera_id": self.camera_id,
            "event_timestamp": self.event_timestamp,
            "clip_start": self.clip_start,
            "clip_end": self.clip_end,
            "reason": self.reason.value,
            "box_id": self.box_id,
            "pallet_id": self.pallet_id,
            "barcode_camera": self.barcode_camera,
            "barcode_scanner": self.barcode_scanner,
            "notes": self.notes,
            "created_at": self.created_at,
        }


class EvidenceGenerator:
    """
    Generates evidence clip requests for bad events.

    How it works:
    - Listens for mismatch events from EventCorrelator
    - Writes a JSON request file to the requests folder
    - Video Recorder process watches that folder
    - Video Recorder cuts the clip and uploads to Zoho File Store
    - Evidence clip URL saved to database forever

    This is the communication bridge between Process 2 (Traceability)
    and Process 3 (Video Recorder) — using filesystem signals
    as described in the spec.
    """

    def __init__(
        self,
        requests_dir: str = "data/clip_requests",
        clip_margin_sec: float = 30.0,
        zone_camera_map: Optional[dict] = None,
    ):
        self.requests_dir = requests_dir
        self.clip_margin_sec = clip_margin_sec
        # Map zone_id to camera_id — default matches our 5 zones
        self.zone_camera_map = zone_camera_map or {
            1: 2, 2: 3, 3: 4, 4: 5, 5: 6
        }
        self._requests: List[EvidenceRequest] = []
        self._ensure_requests_dir()
        logger.info(f"EvidenceGenerator initialized — requests dir: {requests_dir}")

    def _ensure_requests_dir(self):
        """Create the requests directory if it doesn't exist."""
        os.makedirs(self.requests_dir, exist_ok=True)

    def _generate_request_id(self) -> str:
        """Generate a unique request ID."""
        return f"CLIP-{int(time.time())}-{len(self._requests) + 1:04d}"

    def _get_camera_for_zone(self, zone_id: int) -> int:
        """Get the camera ID for a given zone."""
        return self.zone_camera_map.get(zone_id, zone_id)

    def request_clip(
        self,
        zone_id: int,
        event_timestamp: float,
        reason: EvidenceReason,
        box_id: Optional[str] = None,
        pallet_id: Optional[str] = None,
        barcode_camera: Optional[str] = None,
        barcode_scanner: Optional[str] = None,
        notes: str = "",
    ) -> EvidenceRequest:
        """
        Request an evidence clip for an event.
        Writes a JSON file to the requests folder for the Video Recorder.
        """
        request = EvidenceRequest(
            request_id=self._generate_request_id(),
            zone_id=zone_id,
            camera_id=self._get_camera_for_zone(zone_id),
            event_timestamp=event_timestamp,
            clip_start=event_timestamp - self.clip_margin_sec,
            clip_end=event_timestamp + self.clip_margin_sec,
            reason=reason,
            box_id=box_id,
            pallet_id=pallet_id,
            barcode_camera=barcode_camera,
            barcode_scanner=barcode_scanner,
            notes=notes,
        )

        # Write request file for Video Recorder to pick up
        self._write_request_file(request)
        self._requests.append(request)

        logger.warning(
            f"Evidence clip requested: {request.request_id} — "
            f"reason={reason.value}, zone={zone_id}, box={box_id}"
        )
        return request

    def _write_request_file(self, request: EvidenceRequest):
        """Write the request as a JSON file to the requests directory."""
        filename = f"{request.request_id}.json"
        filepath = os.path.join(self.requests_dir, filename)
        try:
            with open(filepath, "w") as f:
                json.dump(request.to_dict(), f, indent=2)
            logger.debug(f"Clip request written: {filepath}")
        except Exception as e:
            logger.error(f"Failed to write clip request file: {e}")

    def on_correlation_event(self, event: CorrelationEvent):
        """
        Called automatically when EventCorrelator fires an alert.
        Registers this as the alert callback in EventCorrelator.
        """
        if event.match_status == MatchStatus.MISMATCH:
            self.request_clip(
                zone_id=event.zone_id,
                event_timestamp=event.timestamp,
                reason=EvidenceReason.BARCODE_MISMATCH,
                box_id=event.box_id,
                barcode_camera=event.barcode_camera,
                barcode_scanner=event.barcode_scanner,
                notes=f"Camera read {event.barcode_camera} but scanner read {event.barcode_scanner}",
            )

    def request_manual_clip(
        self,
        zone_id: int,
        timestamp: float,
        box_id: Optional[str] = None,
        notes: str = "Manual request from dashboard",
    ) -> EvidenceRequest:
        """
        Request a clip manually — called from the admin dashboard.
        """
        return self.request_clip(
            zone_id=zone_id,
            event_timestamp=timestamp,
            reason=EvidenceReason.MANUAL_REQUEST,
            box_id=box_id,
            notes=notes,
        )

    def get_requests(self) -> List[EvidenceRequest]:
        """Return all evidence requests made this session."""
        return self._requests.copy()

    def get_pending_requests(self) -> List[EvidenceRequest]:
        """
        Return requests that have been written but not yet
        processed by the Video Recorder.
        Checks for JSON files still in the requests directory.
        """
        pending = []
        try:
            for filename in os.listdir(self.requests_dir):
                if filename.endswith(".json"):
                    pending.append(filename)
        except Exception as e:
            logger.error(f"Error checking pending requests: {e}")
        return pending

    @classmethod
    def from_env(cls) -> "EvidenceGenerator":
        """Build from environment variables."""
        return cls(
            requests_dir=os.environ.get("CLIP_REQUESTS_DIR", "data/clip_requests"),
            clip_margin_sec=float(os.environ.get("EVIDENCE_CLIP_MARGIN_SEC", "30.0")),
        )