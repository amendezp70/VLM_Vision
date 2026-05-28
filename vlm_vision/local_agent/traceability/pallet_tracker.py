"""
PalletTracker — tracks boxes being placed onto pallets at Zone 4.
Maintains the state of which boxes are on which pallet,
when assembly started/completed, and how many boxes are on each pallet.
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class PalletStatus(Enum):
    """Current state of a pallet."""
    ASSEMBLING = "assembling"   # Boxes being added
    COMPLETED = "completed"     # Pallet is full / assembly done
    LOADED = "loaded"           # Pallet loaded onto truck


@dataclass
class BoxOnPallet:
    """A box that has been placed on a pallet."""
    box_id: str
    barcode: str
    placed_at: float
    position: Optional[int] = None  # Slot position on pallet


@dataclass
class Pallet:
    """
    A single pallet being assembled at Zone 4.
    Tracks all boxes placed on it and its current status.
    """
    pallet_id: str
    shipment_id: Optional[str]
    pallet_number: int
    assembly_start: float
    status: PalletStatus = PalletStatus.ASSEMBLING
    boxes: List[BoxOnPallet] = field(default_factory=list)
    assembly_end: Optional[float] = None
    loaded_at: Optional[float] = None

    @property
    def box_count(self) -> int:
        return len(self.boxes)

    @property
    def is_complete(self) -> bool:
        return self.status == PalletStatus.COMPLETED

    @property
    def is_loaded(self) -> bool:
        return self.status == PalletStatus.LOADED

    def add_box(self, box_id: str, barcode: str) -> BoxOnPallet:
        """Add a box to this pallet."""
        position = len(self.boxes) + 1
        box = BoxOnPallet(
            box_id=box_id,
            barcode=barcode,
            placed_at=time.time(),
            position=position,
        )
        self.boxes.append(box)
        logger.info(f"Box {box_id} added to pallet {self.pallet_id} — position {position}")
        return box

    def complete(self):
        """Mark pallet assembly as complete."""
        self.status = PalletStatus.COMPLETED
        self.assembly_end = time.time()
        duration = self.assembly_end - self.assembly_start
        logger.info(f"Pallet {self.pallet_id} completed — {self.box_count} boxes in {duration:.1f}s")

    def mark_loaded(self):
        """Mark pallet as loaded onto truck."""
        self.status = PalletStatus.LOADED
        self.loaded_at = time.time()
        logger.info(f"Pallet {self.pallet_id} loaded onto truck")

    def get_barcodes(self) -> List[str]:
        """Return list of all barcodes on this pallet."""
        return [b.barcode for b in self.boxes]

    def __str__(self):
        return (
            f"Pallet({self.pallet_id}, "
            f"boxes={self.box_count}, "
            f"status={self.status.value})"
        )


class PalletTracker:
    """
    Manages all active and completed pallets.
    Called by the Traceability Agent when Zone 4 detects
    a box being placed on a pallet.
    """

    def __init__(self):
        self._active_pallets: Dict[str, Pallet] = {}
        self._completed_pallets: Dict[str, Pallet] = {}
        self._pallet_counter: int = 0
        self._events: List[dict] = []
        logger.info("PalletTracker initialized")

    def _generate_pallet_id(self) -> str:
        """Generate a unique pallet ID."""
        self._pallet_counter += 1
        timestamp = int(time.time())
        return f"PAL-{timestamp}-{self._pallet_counter:04d}"

    def start_pallet(self, shipment_id: Optional[str] = None) -> Pallet:
        """
        Start tracking a new pallet.
        Called when Zone 4 camera detects a new empty pallet.
        """
        pallet_id = self._generate_pallet_id()
        pallet = Pallet(
            pallet_id=pallet_id,
            shipment_id=shipment_id,
            pallet_number=self._pallet_counter,
            assembly_start=time.time(),
        )
        self._active_pallets[pallet_id] = pallet
        logger.info(f"New pallet started: {pallet_id}")
        self._log_event("pallet_started", pallet_id=pallet_id, shipment_id=shipment_id)
        return pallet

    def add_box_to_pallet(
        self,
        pallet_id: str,
        box_id: str,
        barcode: str,
    ) -> Optional[BoxOnPallet]:
        """
        Record a box being placed on a pallet.
        Called when Zone 4 camera detects a box placement.
        """
        pallet = self._active_pallets.get(pallet_id)
        if pallet is None:
            logger.warning(f"Cannot add box — pallet {pallet_id} not found or not active")
            return None

        box = pallet.add_box(box_id=box_id, barcode=barcode)
        self._log_event(
            "box_placed_on_pallet",
            pallet_id=pallet_id,
            box_id=box_id,
            barcode=barcode,
            position=box.position,
        )
        return box

    def complete_pallet(self, pallet_id: str) -> Optional[Pallet]:
        """
        Mark a pallet as fully assembled.
        Called when operator signals pallet is ready or
        AI detects the pallet is full.
        """
        pallet = self._active_pallets.get(pallet_id)
        if pallet is None:
            logger.warning(f"Cannot complete — pallet {pallet_id} not found")
            return None

        pallet.complete()
        self._completed_pallets[pallet_id] = pallet
        del self._active_pallets[pallet_id]
        self._log_event("pallet_completed", pallet_id=pallet_id, box_count=pallet.box_count)
        return pallet

    def mark_pallet_loaded(self, pallet_id: str) -> Optional[Pallet]:
        """
        Mark a pallet as loaded onto a truck at Zone 5.
        """
        # Check completed pallets first
        pallet = self._completed_pallets.get(pallet_id)
        if pallet is None:
            # Also check active pallets in case complete was skipped
            pallet = self._active_pallets.get(pallet_id)
        if pallet is None:
            logger.warning(f"Cannot mark loaded — pallet {pallet_id} not found")
            return None

        pallet.mark_loaded()
        self._log_event("pallet_loaded", pallet_id=pallet_id)
        return pallet

    def get_active_pallet(self) -> Optional[Pallet]:
        """Return the most recently started active pallet."""
        if not self._active_pallets:
            return None
        return list(self._active_pallets.values())[-1]

    def get_pallet(self, pallet_id: str) -> Optional[Pallet]:
        """Find a pallet by ID in active or completed."""
        return self._active_pallets.get(pallet_id) or self._completed_pallets.get(pallet_id)

    def get_all_active(self) -> List[Pallet]:
        """Return all currently active pallets."""
        return list(self._active_pallets.values())

    def get_all_completed(self) -> List[Pallet]:
        """Return all completed pallets."""
        return list(self._completed_pallets.values())

    def get_events(self) -> List[dict]:
        """Return all pallet events for cloud sync."""
        return self._events.copy()

    def _log_event(self, event_type: str, **kwargs):
        """Log a pallet event for cloud sync."""
        event = {
            "event_type": event_type,
            "timestamp": time.time(),
            **kwargs
        }
        self._events.append(event)
        logger.debug(f"Pallet event: {event_type} — {kwargs}")

    def summary(self) -> dict:
        """Return a summary of current pallet state."""
        return {
            "active_pallets": len(self._active_pallets),
            "completed_pallets": len(self._completed_pallets),
            "total_boxes_active": sum(p.box_count for p in self._active_pallets.values()),
            "total_boxes_completed": sum(p.box_count for p in self._completed_pallets.values()),
        }