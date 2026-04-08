from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple


class BayStatus(Enum):
    WAITING = "waiting"
    ACTIVE = "active"
    CONFIRMING = "confirming"


@dataclass
class Detection:
    sku: str
    color: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2


@dataclass
class PickOrder:
    order_id: str
    sku: str
    qty: int
    tray_id: str


@dataclass
class PickEvent:
    order_id: str
    sku: str
    qty_picked: int
    bay_id: int
    worker_id: str
    result: str  # "correct" | "wrong" | "short"
    timestamp: float
    synced: bool = False
