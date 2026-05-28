"""
ZoneManager — manages the 5 camera zones for the traceability module.
Each zone has a camera, an AI model, and a zone type that defines what
events it generates. Routes frames to the correct detector per zone.
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)


class ZoneType(Enum):
    """The type of zone determines which AI model runs and what events fire."""
    PACKING = "packing"           # Zone 1 — box packing + SKU detection
    BARCODE_SCAN = "barcode_scan" # Zone 2 — dual barcode verification
    SEALING = "sealing"           # Zone 3 — box sealed confirmation
    PALLET_ASSEMBLY = "pallet_assembly"  # Zone 4 — pallet building
    TRUCK_LOADING = "truck_loading"      # Zone 5 — truck departure


@dataclass
class ZoneConfig:
    """Configuration for a single zone."""
    zone_id: int
    zone_type: ZoneType
    camera_id: int
    model_path: str
    enabled: bool = True
    description: str = ""


@dataclass
class Detection:
    """A single detection result from the AI model."""
    label: str
    confidence: float
    bbox: List[float]  # [x1, y1, x2, y2] in pixels


@dataclass
class ZoneFrame:
    """A frame captured from a zone camera with its detections."""
    zone_id: int
    zone_type: ZoneType
    camera_id: int
    frame: np.ndarray
    detections: List[Detection] = field(default_factory=list)
    timestamp: float = 0.0


class ZoneManager:
    """
    Manages all 5 traceability zones.
    - Holds the config for each zone
    - Tracks which zones are active
    - Routes frames to the correct detector
    - Returns ZoneFrame results for the EventCorrelator to process
    """

    def __init__(self, zones: List[ZoneConfig]):
        self.zones: Dict[int, ZoneConfig] = {z.zone_id: z for z in zones}
        self._detectors: Dict[int, object] = {}  # loaded lazily
        logger.info(f"ZoneManager initialized with {len(self.zones)} zones")
        for zone in zones:
            logger.info(f"  Zone {zone.zone_id}: {zone.zone_type.value} — camera {zone.camera_id} — {'enabled' if zone.enabled else 'DISABLED'}")

    def get_zone(self, zone_id: int) -> Optional[ZoneConfig]:
        """Return config for a specific zone."""
        return self.zones.get(zone_id)

    def get_enabled_zones(self) -> List[ZoneConfig]:
        """Return only the zones that are currently enabled."""
        return [z for z in self.zones.values() if z.enabled]

    def get_camera_ids(self) -> List[int]:
        """Return camera IDs for all enabled zones."""
        return [z.camera_id for z in self.get_enabled_zones()]

    def enable_zone(self, zone_id: int) -> bool:
        """Enable a zone by ID. Returns True if successful."""
        if zone_id in self.zones:
            self.zones[zone_id].enabled = True
            logger.info(f"Zone {zone_id} enabled")
            return True
        logger.warning(f"Cannot enable zone {zone_id} — not found")
        return False

    def disable_zone(self, zone_id: int) -> bool:
        """Disable a zone without restarting. Returns True if successful."""
        if zone_id in self.zones:
            self.zones[zone_id].enabled = False
            logger.info(f"Zone {zone_id} disabled")
            return True
        logger.warning(f"Cannot disable zone {zone_id} — not found")
        return False

    def get_zone_for_camera(self, camera_id: int) -> Optional[ZoneConfig]:
        """Find which zone a given camera belongs to."""
        for zone in self.zones.values():
            if zone.camera_id == camera_id:
                return zone
        return None

    def process_frame(self, zone_id: int, frame: np.ndarray, timestamp: float, detector=None) -> Optional[ZoneFrame]:
        """
        Process a single frame from a zone camera.
        Runs the detector if provided and returns a ZoneFrame with detections.
        """
        zone = self.zones.get(zone_id)
        if zone is None:
            logger.warning(f"Frame received for unknown zone {zone_id}")
            return None

        if not zone.enabled:
            return None

        detections = []
        if detector is not None:
            try:
                raw = detector.detect(frame)
                detections = [
                    Detection(
                        label=d.get("label", "unknown"),
                        confidence=d.get("confidence", 0.0),
                        bbox=d.get("bbox", [0, 0, 0, 0]),
                    )
                    for d in raw
                ]
            except Exception as e:
                logger.error(f"Detection failed on zone {zone_id}: {e}")

        return ZoneFrame(
            zone_id=zone_id,
            zone_type=zone.zone_type,
            camera_id=zone.camera_id,
            frame=frame,
            detections=detections,
            timestamp=timestamp,
        )

    @classmethod
    def from_env(cls) -> "ZoneManager":
        """
        Build a ZoneManager from environment variables.
        Matches the pattern used in config.py.
        """
        import os
        zones = [
            ZoneConfig(
                zone_id=1,
                zone_type=ZoneType.PACKING,
                camera_id=int(os.environ.get("CAMERA_ZONE1", "2")),
                model_path=os.environ.get("MODEL_PATH", "models/metwall.onnx"),
                description="Box packing and SKU detection",
            ),
            ZoneConfig(
                zone_id=2,
                zone_type=ZoneType.BARCODE_SCAN,
                camera_id=int(os.environ.get("CAMERA_ZONE2", "3")),
                model_path=os.environ.get("MODEL_BARCODE_PATH", "models/barcode.onnx"),
                description="Dual barcode verification",
            ),
            ZoneConfig(
                zone_id=3,
                zone_type=ZoneType.SEALING,
                camera_id=int(os.environ.get("CAMERA_ZONE3", "4")),
                model_path=os.environ.get("MODEL_BOXSTATE_PATH", "models/box_state.onnx"),
                description="Box sealing confirmation",
            ),
            ZoneConfig(
                zone_id=4,
                zone_type=ZoneType.PALLET_ASSEMBLY,
                camera_id=int(os.environ.get("CAMERA_ZONE4", "5")),
                model_path=os.environ.get("MODEL_PALLET_PATH", "models/pallet.onnx"),
                description="Pallet assembly tracking",
            ),
            ZoneConfig(
                zone_id=5,
                zone_type=ZoneType.TRUCK_LOADING,
                camera_id=int(os.environ.get("CAMERA_ZONE5", "6")),
                model_path=os.environ.get("MODEL_PALLET_PATH", "models/pallet.onnx"),
                description="Truck loading confirmation",
            ),
        ]
        return cls(zones=zones)