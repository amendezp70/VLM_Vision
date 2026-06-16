import sys
import numpy as np
from local_agent.traceability.zone_manager import (
    ZoneManager, ZoneConfig, ZoneType, Detection, ZoneFrame,
)

_p=_f=0
def check(n,c,d=""):
    global _p,_f; _p+=c; _f+=(not c); print(f"  [{'PASS' if c else 'FAIL'}] {n}"+(f"  ({d})" if d else ""))

frame = np.zeros((100,100,3), np.uint8)

class FakeDetector:
    def __init__(self, dets): self._dets = dets
    def detect(self, frame): return self._dets
class BrokenDetector:
    def detect(self, frame): raise RuntimeError("boom")

# ---- from_env: the 5-zone setup ----
print("from_env zone setup")
zm = ZoneManager.from_env()
check("5 zones created", len(zm.zones)==5)
check("all enabled by default", len(zm.get_enabled_zones())==5)
check("zone1 = PACKING", zm.get_zone(1).zone_type==ZoneType.PACKING)
check("zone2 = BARCODE_SCAN", zm.get_zone(2).zone_type==ZoneType.BARCODE_SCAN)
check("zone5 = TRUCK_LOADING", zm.get_zone(5).zone_type==ZoneType.TRUCK_LOADING)
check("zone->camera map 1->2", zm.get_zone(1).camera_id==2)
check("zone->camera map 2->3", zm.get_zone(2).camera_id==3)
check("zone->camera map 5->6", zm.get_zone(5).camera_id==6)
check("camera ids list", zm.get_camera_ids()==[2,3,4,5,6])

# ---- lookups ----
print("\nlookups")
check("get_zone unknown -> None", zm.get_zone(99) is None)
check("get_zone_for_camera 4 -> zone 3", zm.get_zone_for_camera(4).zone_id==3)
check("get_zone_for_camera unknown -> None", zm.get_zone_for_camera(999) is None)

# ---- enable/disable ----
print("\nenable/disable")
check("disable zone 3 returns True", zm.disable_zone(3) is True)
check("disabled zone drops from enabled list", len(zm.get_enabled_zones())==4)
check("disabled camera drops from camera ids", 4 not in zm.get_camera_ids())
check("enable zone 3 returns True", zm.enable_zone(3) is True)
check("re-enabled zone back in list", len(zm.get_enabled_zones())==5)
check("disable unknown -> False", zm.disable_zone(99) is False)
check("enable unknown -> False", zm.enable_zone(99) is False)

# ---- process_frame: routing + detector dict->Detection ----
print("\nprocess_frame")
zf = zm.process_frame(2, frame, 123.0, detector=FakeDetector([
    {"label":"barcode","confidence":0.9,"bbox":[1,2,3,4]},
]))
check("returns a ZoneFrame", isinstance(zf, ZoneFrame))
check("routed zone_type correct (BARCODE_SCAN)", zf.zone_type==ZoneType.BARCODE_SCAN)
check("camera_id attached", zf.camera_id==3)
check("timestamp passed through", zf.timestamp==123.0)
check("dict converted to Detection", len(zf.detections)==1 and isinstance(zf.detections[0], Detection))
d = zf.detections[0]
check("Detection.label", d.label=="barcode")
check("Detection.confidence", d.confidence==0.9)
check("Detection.bbox", d.bbox==[1,2,3,4])

zf2 = zm.process_frame(1, frame, 1.0, detector=FakeDetector([{}]))
check("missing label -> 'unknown'", zf2.detections[0].label=="unknown")
check("missing confidence -> 0.0", zf2.detections[0].confidence==0.0)
check("missing bbox -> [0,0,0,0]", zf2.detections[0].bbox==[0,0,0,0])

zf3 = zm.process_frame(1, frame, 1.0)
check("no detector -> empty detections", zf3 is not None and zf3.detections==[])

check("unknown zone -> None", zm.process_frame(99, frame, 1.0) is None)

zm.disable_zone(4)
check("disabled zone -> None", zm.process_frame(4, frame, 1.0) is None)
zm.enable_zone(4)

zf4 = zm.process_frame(2, frame, 1.0, detector=BrokenDetector())
check("detector exception caught -> empty detections, frame still returned",
      zf4 is not None and zf4.detections==[])

zf5 = zm.process_frame(4, frame, 1.0, detector=FakeDetector([
    {"label":"pallet_full","confidence":0.8,"bbox":[0,0,10,10]},
    {"label":"forklift","confidence":0.6,"bbox":[5,5,20,20]},
]))
check("multiple detections preserved", len(zf5.detections)==2)

print(f"\n  RESULTS: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)