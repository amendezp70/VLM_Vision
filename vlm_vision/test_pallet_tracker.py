import sys
from local_agent.traceability.pallet_tracker import (
    PalletTracker, Pallet, BoxOnPallet, PalletStatus,
)

_p=_f=0
def check(n,c,d=""):
    global _p,_f; _p+=c; _f+=(not c); print(f"  [{'PASS' if c else 'FAIL'}] {n}"+(f"  ({d})" if d else ""))

# ---- start_pallet ----
print("start_pallet")
pt = PalletTracker()
p1 = pt.start_pallet(shipment_id="SHIP-1")
check("returns a Pallet", isinstance(p1, Pallet))
check("status ASSEMBLING", p1.status==PalletStatus.ASSEMBLING)
check("shipment_id set", p1.shipment_id=="SHIP-1")
check("pallet_id format PAL-", p1.pallet_id.startswith("PAL-"))
check("now 1 active pallet", pt.summary()["active_pallets"]==1)
check("get_active_pallet returns it", pt.get_active_pallet().pallet_id==p1.pallet_id)
p2 = pt.start_pallet()
check("unique pallet ids", p1.pallet_id != p2.pallet_id)
check("get_active returns the LATEST", pt.get_active_pallet().pallet_id==p2.pallet_id)
check("2 active now", pt.summary()["active_pallets"]==2)

# ---- add boxes ----
print("\nadd_box_to_pallet")
b1 = pt.add_box_to_pallet(p1.pallet_id, "BOX-1", "0687456223537")
check("returns a BoxOnPallet", isinstance(b1, BoxOnPallet))
check("box position starts at 1", b1.position==1)
check("box barcode stored", b1.barcode=="0687456223537")
b2 = pt.add_box_to_pallet(p1.pallet_id, "BOX-2", "0687456223538")
check("second box position 2", b2.position==2)
check("pallet box_count is 2", pt.get_pallet(p1.pallet_id).box_count==2)
check("get_barcodes lists both", pt.get_pallet(p1.pallet_id).get_barcodes()==["0687456223537","0687456223538"])
check("summary total_boxes_active counts them", pt.summary()["total_boxes_active"]==2)
check("add to unknown pallet -> None", pt.add_box_to_pallet("PAL-NOPE","B","x") is None)

# ---- complete ----
print("\ncomplete_pallet")
done = pt.complete_pallet(p1.pallet_id)
check("returns the pallet", done is not None and done.pallet_id==p1.pallet_id)
check("status COMPLETED", done.status==PalletStatus.COMPLETED)
check("is_complete property", done.is_complete)
check("assembly_end set", done.assembly_end is not None)
check("moved out of active", p1.pallet_id not in [p.pallet_id for p in pt.get_all_active()])
check("now in completed list", p1.pallet_id in [p.pallet_id for p in pt.get_all_completed()])
check("active count dropped to 1", pt.summary()["active_pallets"]==1)
check("completed count is 1", pt.summary()["completed_pallets"]==1)
check("get_pallet still finds completed one", pt.get_pallet(p1.pallet_id) is not None)
check("complete unknown -> None", pt.complete_pallet("PAL-NOPE") is None)

# ---- mark loaded ----
print("\nmark_pallet_loaded")
loaded = pt.mark_pallet_loaded(p1.pallet_id)
check("returns the pallet", loaded is not None)
check("status LOADED", loaded.status==PalletStatus.LOADED)
check("is_loaded property", loaded.is_loaded)
check("loaded_at set", loaded.loaded_at is not None)
loaded2 = pt.mark_pallet_loaded(p2.pallet_id)
check("can load an active pallet (skip-complete fallback)", loaded2 is not None and loaded2.is_loaded)
check("mark loaded unknown -> None", pt.mark_pallet_loaded("PAL-NOPE") is None)

# ---- events log ----
print("\nevents")
events = pt.get_events()
types = [e["event_type"] for e in events]
check("logged pallet_started", "pallet_started" in types)
check("logged box_placed_on_pallet", "box_placed_on_pallet" in types)
check("logged pallet_completed", "pallet_completed" in types)
check("logged pallet_loaded", "pallet_loaded" in types)
check("get_events returns a copy", pt.get_events() is not events)
check("every event has a timestamp", all("timestamp" in e for e in events))

# ---- empty tracker ----
print("\nempty state")
empty = PalletTracker()
check("no active pallet -> None", empty.get_active_pallet() is None)
check("empty summary zeros", empty.summary()=={"active_pallets":0,"completed_pallets":0,"total_boxes_active":0,"total_boxes_completed":0})
check("get unknown pallet -> None", empty.get_pallet("PAL-X") is None)

print(f"\n  RESULTS: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)