"""
EventCorrelator — matches camera barcode reads with USB scanner reads.
This is the dual verification system. Both sources must agree within
a 5-second window for a box to be marked as barcode_verified = True.
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from local_agent.traceability.barcode_reader import BarcodeResult

logger = logging.getLogger(__name__)


class MatchStatus(Enum):
    """Result of comparing camera vs scanner barcode reads."""
    MATCH = "match"         # Both sources read the same value ✅
    MISMATCH = "mismatch"   # Both sources read but values differ ❌
    PARTIAL = "partial"     # Only one source read successfully ⚠️
    PENDING = "pending"     # Waiting for second source to read


@dataclass
class CorrelationEvent:
    """
    The result of correlating a camera read with a scanner read.
    This gets saved to the database and triggers alerts on mismatch.
    """
    box_id: Optional[str]
    zone_id: int
    barcode_camera: Optional[str]      # Value read by camera
    barcode_scanner: Optional[str]     # Value read by USB scanner
    match_status: MatchStatus
    timestamp: float
    camera_timestamp: Optional[float] = None
    scanner_timestamp: Optional[float] = None
    time_delta_sec: Optional[float] = None  # How far apart the two reads were

    @property
    def is_verified(self) -> bool:
        """True only if both sources matched."""
        return self.match_status == MatchStatus.MATCH

    @property
    def needs_alert(self) -> bool:
        """True if this event should trigger an alert and evidence clip."""
        return self.match_status == MatchStatus.MISMATCH

    def __str__(self):
        return (
            f"CorrelationEvent(status={self.match_status.value}, "
            f"camera={self.barcode_camera}, scanner={self.barcode_scanner}, "
            f"verified={self.is_verified})"
        )


@dataclass
class PendingRead:
    """A barcode read waiting to be matched with its counterpart."""
    result: BarcodeResult
    expires_at: float  # Unix timestamp after which this read expires


class EventCorrelator:
    """
    Matches camera barcode reads with USB scanner reads within a time window.

    How it works:
    - Camera reads a barcode → stored as pending camera read
    - Scanner reads a barcode → stored as pending scanner read
    - When both are present within the match window → compare values
    - MATCH: barcode_verified = True, log success event
    - MISMATCH: barcode_verified = False, fire alert, generate evidence clip
    - PARTIAL: only one source read, log warning

    The match window is configurable (default 5 seconds per spec).
    """

    def __init__(self, match_window_sec: float = 5.0, zone_id: int = 2):
        self.match_window_sec = match_window_sec
        self.zone_id = zone_id
        self._pending_camera: Optional[PendingRead] = None
        self._pending_scanner: Optional[PendingRead] = None
        self._events: List[CorrelationEvent] = []
        self._alert_callbacks: List = []
        logger.info(f"EventCorrelator initialized — zone {zone_id}, window {match_window_sec}s")

    def on_alert(self, callback):
        """Register a callback that fires on MISMATCH events."""
        self._alert_callbacks.append(callback)

    def _fire_alerts(self, event: CorrelationEvent):
        """Call all registered alert callbacks."""
        for cb in self._alert_callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    def _is_expired(self, pending: PendingRead) -> bool:
        """Check if a pending read has passed its expiry time."""
        return time.time() > pending.expires_at

    def _make_expires_at(self) -> float:
        """Calculate expiry timestamp for a new pending read."""
        return time.time() + self.match_window_sec

    def add_camera_read(self, result: BarcodeResult, box_id: Optional[str] = None) -> Optional[CorrelationEvent]:
        """
        Called when the camera detects and decodes a barcode.
        If a scanner read is already pending, attempt to correlate immediately.
        """
        # Clean up expired pending reads
        if self._pending_scanner and self._is_expired(self._pending_scanner):
            logger.warning("Scanner read expired before camera read arrived — PARTIAL")
            event = self._make_partial_event(
                scanner_result=self._pending_scanner.result,
                box_id=box_id
            )
            self._pending_scanner = None
            self._save_event(event)
            return event

        self._pending_camera = PendingRead(
            result=result,
            expires_at=self._make_expires_at()
        )
        logger.debug(f"Camera read stored: {result.value} — waiting for scanner")

        # If scanner read is already waiting, correlate now
        if self._pending_scanner:
            return self._correlate(box_id=box_id)

        return None

    def add_scanner_read(self, result: BarcodeResult, box_id: Optional[str] = None) -> Optional[CorrelationEvent]:
        """
        Called when the USB scanner reads a barcode.
        If a camera read is already pending, attempt to correlate immediately.
        """
        # Clean up expired pending reads
        if self._pending_camera and self._is_expired(self._pending_camera):
            logger.warning("Camera read expired before scanner read arrived — PARTIAL")
            event = self._make_partial_event(
                camera_result=self._pending_camera.result,
                box_id=box_id
            )
            self._pending_camera = None
            self._save_event(event)
            return event

        self._pending_scanner = PendingRead(
            result=result,
            expires_at=self._make_expires_at()
        )
        logger.debug(f"Scanner read stored: {result.value} — waiting for camera")

        # If camera read is already waiting, correlate now
        if self._pending_camera:
            return self._correlate(box_id=box_id)

        return None

    def _correlate(self, box_id: Optional[str] = None) -> CorrelationEvent:
        """
        Compare camera and scanner reads and produce a CorrelationEvent.
        Called when both reads are available.
        """
        camera = self._pending_camera.result
        scanner = self._pending_scanner.result

        # Clear pending reads
        self._pending_camera = None
        self._pending_scanner = None

        time_delta = abs(camera.timestamp - scanner.timestamp)

        if camera.value == scanner.value:
            status = MatchStatus.MATCH
            logger.info(f"✅ MATCH: {camera.value} — delta {time_delta:.2f}s")
        else:
            status = MatchStatus.MISMATCH
            logger.warning(f"❌ MISMATCH: camera={camera.value} scanner={scanner.value}")

        event = CorrelationEvent(
            box_id=box_id,
            zone_id=self.zone_id,
            barcode_camera=camera.value,
            barcode_scanner=scanner.value,
            match_status=status,
            timestamp=time.time(),
            camera_timestamp=camera.timestamp,
            scanner_timestamp=scanner.timestamp,
            time_delta_sec=time_delta,
        )

        self._save_event(event)

        if event.needs_alert:
            logger.warning(f"🚨 Alert triggered for mismatch — generating evidence clip")
            self._fire_alerts(event)

        return event

    def _make_partial_event(
        self,
        camera_result: Optional[BarcodeResult] = None,
        scanner_result: Optional[BarcodeResult] = None,
        box_id: Optional[str] = None,
    ) -> CorrelationEvent:
        """Create a PARTIAL event when only one source read."""
        return CorrelationEvent(
            box_id=box_id,
            zone_id=self.zone_id,
            barcode_camera=camera_result.value if camera_result else None,
            barcode_scanner=scanner_result.value if scanner_result else None,
            match_status=MatchStatus.PARTIAL,
            timestamp=time.time(),
        )

    def _save_event(self, event: CorrelationEvent):
        """Save event to internal log."""
        self._events.append(event)
        logger.info(f"Event saved: {event}")

    def get_events(self) -> List[CorrelationEvent]:
        """Return all correlation events."""
        return self._events.copy()

    def get_mismatches(self) -> List[CorrelationEvent]:
        """Return only mismatch events — for dashboard alerts."""
        return [e for e in self._events if e.match_status == MatchStatus.MISMATCH]

    def clear(self):
        """Clear all pending reads and event log."""
        self._pending_camera = None
        self._pending_scanner = None
        self._events.clear()

    @classmethod
    def from_env(cls) -> "EventCorrelator":
        """Build from environment variables."""
        import os
        return cls(
            match_window_sec=float(os.environ.get("BARCODE_MATCH_WINDOW_SEC", "5.0")),
            zone_id=2,
        )