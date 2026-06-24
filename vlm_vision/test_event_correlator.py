import sys, time
from local_agent.traceability.barcode_reader import BarcodeResult
from local_agent.traceability.event_correlator import (
    EventCorrelator, CorrelationEvent, MatchStatus,
)

_p=_f=0
def check(n,c,d=""):
    global _p,_f; _p+=c; _f+=(not c); print(f"  [{'PASS' if c else 'FAIL'}] {n}"+(f"  ({d})" if d else ""))

def cam(val, ts=None): return BarcodeResult(value=val, source="camera", timestamp=ts or time.time())
def scn(val, ts=None): return BarcodeResult(value=val, source="scanner", timestamp=ts or time.time())

print("MatchStatus enum")
check("has PARTIAL member (bug fix)", hasattr(MatchStatus, "PARTIAL"))

print("\nMATCH path")
ec = EventCorrelator(match_window_sec=5.0)
r = ec.add_camera_read(cam("SKU-100"))
check("camera read alone returns None (waiting)", r is None)
ev = ec.add_scanner_read(scn("SKU-100"))
check("scanner read completes correlation", ev is not None)
check("status MATCH", ev.match_status==MatchStatus.MATCH)
check("is_verified True", ev.is_verified)
check("needs_alert False", not ev.needs_alert)
check("camera value recorded", ev.barcode_camera=="SKU-100")
check("scanner value recorded", ev.barcode_scanner=="SKU-100")
check("time_delta computed", ev.time_delta_sec is not None)
check("pending cleared after correlate", ec._pending_camera is None and ec._pending_scanner is None)

print("\nMISMATCH path + alert")
ec2 = EventCorrelator()
alerts = []
ec2.on_alert(lambda e: alerts.append(e))
ec2.add_camera_read(cam("SKU-AAA"))
ev2 = ec2.add_scanner_read(scn("SKU-BBB"))
check("status MISMATCH", ev2.match_status==MatchStatus.MISMATCH)
check("is_verified False", not ev2.is_verified)
check("needs_alert True", ev2.needs_alert)
check("alert callback fired once", len(alerts)==1)
check("alert carries the event", alerts[0].match_status==MatchStatus.MISMATCH)
ec2.add_camera_read(cam("X")); ec2.add_scanner_read(scn("X"))
check("alert count still 1 after a match", len(alerts)==1)

print("\nScanner-first ordering")
ec3 = EventCorrelator()
check("scanner read alone returns None", ec3.add_scanner_read(scn("Z1")) is None)
ev3 = ec3.add_camera_read(cam("Z1"))
check("camera completes it -> MATCH", ev3 is not None and ev3.match_status==MatchStatus.MATCH)

print("\nPARTIAL path (expiry) -- this used to crash")
ec4 = EventCorrelator(match_window_sec=0.05)
ec4.add_camera_read(cam("ONLY-CAM"))
time.sleep(0.1)
ev4 = ec4.add_scanner_read(scn("LATE-SCAN"))
check("expired camera -> PARTIAL event (no crash)", ev4 is not None and ev4.match_status==MatchStatus.PARTIAL)
check("partial keeps the camera value", ev4.barcode_camera=="ONLY-CAM")
check("partial scanner side is None", ev4.barcode_scanner is None)
ec5 = EventCorrelator(match_window_sec=0.05)
ec5.add_scanner_read(scn("ONLY-SCAN"))
time.sleep(0.1)
ev5 = ec5.add_camera_read(cam("LATE-CAM"))
check("expired scanner -> PARTIAL (no crash)", ev5 is not None and ev5.match_status==MatchStatus.PARTIAL)
check("partial keeps scanner value", ev5.barcode_scanner=="ONLY-SCAN")

print("\nevent log / mismatches / clear")
ec6 = EventCorrelator()
ec6.add_camera_read(cam("A")); ec6.add_scanner_read(scn("A"))
ec6.add_camera_read(cam("B")); ec6.add_scanner_read(scn("C"))
ec6.add_camera_read(cam("D")); ec6.add_scanner_read(scn("E"))
check("all events logged", len(ec6.get_events())==3)
check("get_mismatches returns only mismatches", len(ec6.get_mismatches())==2)
check("get_events returns a copy", ec6.get_events() is not ec6._events)
ec6.clear()
check("clear empties events", ec6.get_events()==[])
check("clear empties pending", ec6._pending_camera is None and ec6._pending_scanner is None)

print("\nfrom_env")
import os
os.environ["BARCODE_MATCH_WINDOW_SEC"]="7.5"
ecf = EventCorrelator.from_env()
check("reads window from env", ecf.match_window_sec==7.5)
check("zone_id defaults to 2", ecf.zone_id==2)

print("\nbox_id")
ec7 = EventCorrelator()
ec7.add_camera_read(cam("Q"), box_id="BOX-42")
evb = ec7.add_scanner_read(scn("Q"), box_id="BOX-42")
check("box_id recorded on event", evb.box_id=="BOX-42")

print(f"\n  RESULTS: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)