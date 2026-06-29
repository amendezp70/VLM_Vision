import sys, os, json, shutil, time
from local_agent.traceability.evidence_generator import (
    EvidenceGenerator, EvidenceRequest, EvidenceReason,
)
from local_agent.traceability.event_correlator import CorrelationEvent, MatchStatus

_p=_f=0
def check(n,c,d=""):
    global _p,_f; _p+=c; _f+=(not c); print(f"  [{'PASS' if c else 'FAIL'}] {n}"+(f"  ({d})" if d else ""))

ROOT = "test_evidence_output"
if os.path.isdir(ROOT): shutil.rmtree(ROOT)

# ---- init creates the dir ----
print("init")
eg = EvidenceGenerator(requests_dir=ROOT, clip_margin_sec=30.0)
check("requests dir created", os.path.isdir(ROOT))
check("starts with no requests", eg.get_requests()==[])

# ---- request_clip writes a file + computes the window ----
print("\nrequest_clip")
req = eg.request_clip(zone_id=2, event_timestamp=1000.0, reason=EvidenceReason.BARCODE_MISMATCH,
                      box_id="BOX-1", barcode_camera="AAA", barcode_scanner="BBB")
check("returns an EvidenceRequest", isinstance(req, EvidenceRequest))
check("clip_start = ts - margin", req.clip_start==970.0, str(req.clip_start))
check("clip_end = ts + margin", req.clip_end==1030.0, str(req.clip_end))
check("zone 2 -> camera 3 (map)", req.camera_id==3)
check("reason stored", req.reason==EvidenceReason.BARCODE_MISMATCH)
check("box_id stored", req.box_id=="BOX-1")
check("request_id format CLIP-", req.request_id.startswith("CLIP-"))
check("logged in _requests", len(eg.get_requests())==1)

# ---- the JSON file actually got written and is valid ----
print("\nJSON file on disk")
files = [f for f in os.listdir(ROOT) if f.endswith(".json")]
check("one json file written", len(files)==1, str(files))
with open(os.path.join(ROOT, files[0])) as f:
    data = json.load(f)
check("json has the reason as string", data["reason"]=="barcode_mismatch")
check("json clip_start correct", data["clip_start"]==970.0)
check("json camera_id correct", data["camera_id"]==3)
check("json barcode values", data["barcode_camera"]=="AAA" and data["barcode_scanner"]=="BBB")

# ---- unique request ids ----
print("\nunique ids")
req2 = eg.request_clip(zone_id=1, event_timestamp=2000.0, reason=EvidenceReason.WRONG_SKU)
check("second request unique id", req.request_id != req2.request_id)
check("zone 1 -> camera 2", req2.camera_id==2)

# ---- on_correlation_event: only fires on MISMATCH ----
print("\non_correlation_event")
eg2 = EvidenceGenerator(requests_dir=ROOT+"/c")
mismatch = CorrelationEvent(box_id="B9", zone_id=2, barcode_camera="X", barcode_scanner="Y",
                            match_status=MatchStatus.MISMATCH, timestamp=500.0)
eg2.on_correlation_event(mismatch)
check("mismatch -> a clip requested", len(eg2.get_requests())==1)
check("uses BARCODE_MISMATCH reason", eg2.get_requests()[0].reason==EvidenceReason.BARCODE_MISMATCH)
check("carries the box_id", eg2.get_requests()[0].box_id=="B9")
match = CorrelationEvent(box_id="B10", zone_id=2, barcode_camera="Z", barcode_scanner="Z",
                         match_status=MatchStatus.MATCH, timestamp=600.0)
eg2.on_correlation_event(match)
check("MATCH -> no new clip", len(eg2.get_requests())==1)
partial = CorrelationEvent(box_id="B11", zone_id=2, barcode_camera="Q", barcode_scanner=None,
                           match_status=MatchStatus.PARTIAL, timestamp=700.0)
eg2.on_correlation_event(partial)
check("PARTIAL -> no clip (only mismatch triggers)", len(eg2.get_requests())==1)

# ---- wiring as EventCorrelator alert callback (integration) ----
print("\nwired to EventCorrelator")
from local_agent.traceability.event_correlator import EventCorrelator
from local_agent.traceability.barcode_reader import BarcodeResult
eg3 = EvidenceGenerator(requests_dir=ROOT+"/d")
ec = EventCorrelator()
ec.on_alert(eg3.on_correlation_event)
ec.add_camera_read(BarcodeResult("AAA","camera",time.time()))
ec.add_scanner_read(BarcodeResult("BBB","scanner",time.time()))
check("correlator mismatch auto-generates a clip", len(eg3.get_requests())==1)

# ---- manual clip ----
print("\nmanual clip")
m = eg.request_manual_clip(zone_id=3, timestamp=9000.0, box_id="BOXM")
check("manual reason set", m.reason==EvidenceReason.MANUAL_REQUEST)
check("manual zone 3 -> camera 4", m.camera_id==4)

# ---- pending requests ----
print("\npending requests")
pend = eg.get_pending_requests()
check("pending lists the json files", len(pend)>=2, f"{len(pend)} files")

# ---- custom margin + unknown zone fallback ----
print("\nmargin + zone fallback")
eg4 = EvidenceGenerator(requests_dir=ROOT+"/e", clip_margin_sec=10.0)
r4 = eg4.request_clip(zone_id=99, event_timestamp=100.0, reason=EvidenceReason.MANUAL_REQUEST)
check("custom margin applied", r4.clip_start==90.0 and r4.clip_end==110.0)
check("unknown zone falls back to zone_id as camera", r4.camera_id==99)

shutil.rmtree(ROOT)
print(f"\n  RESULTS: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)