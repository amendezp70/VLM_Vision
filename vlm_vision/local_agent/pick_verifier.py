import time
from typing import List, Optional, Dict
from local_agent.models import Detection, PickOrder, PickEvent


def _count_by_sku(detections: List[Detection]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for d in detections:
        counts[d.sku] = counts.get(d.sku, 0) + 1
    return counts


class PickVerifier:
    def __init__(self, bay_id: int, worker_id: str):
        self.bay_id = bay_id
        self.worker_id = worker_id

    def verify(
        self,
        order: PickOrder,
        before: List[Detection],
        after: List[Detection],
    ) -> Optional[PickEvent]:
        before_counts = _count_by_sku(before)
        after_counts = _count_by_sku(after)

        # Find which SKU decreased
        removed: Dict[str, int] = {}
        for sku, count in before_counts.items():
            after_count = after_counts.get(sku, 0)
            if after_count < count:
                removed[sku] = count - after_count

        if not removed:
            return None

        # Check if correct SKU was removed
        if order.sku in removed:
            qty_picked = removed[order.sku]
            if qty_picked >= order.qty:
                result = "correct"
            else:
                result = "short"
            picked_sku = order.sku
        else:
            # Wrong part picked — report the first removed SKU
            picked_sku = next(iter(removed))
            qty_picked = removed[picked_sku]
            result = "wrong"

        return PickEvent(
            order_id=order.order_id,
            sku=picked_sku,
            qty_picked=qty_picked,
            bay_id=self.bay_id,
            worker_id=self.worker_id,
            result=result,
            timestamp=time.time(),
        )
