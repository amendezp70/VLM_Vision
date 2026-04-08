import httpx
from typing import Optional
from local_agent.models import PickOrder


class ModulaClient:
    def __init__(self, base_url: str, timeout: int = 5):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def fetch_active_order(self, bay_id: int) -> Optional[PickOrder]:
        url = f"{self._base_url}/api/v1/bays/{bay_id}/active-order"
        response = httpx.get(url, timeout=self._timeout)
        if response.status_code == 204:
            return None
        response.raise_for_status()
        data = response.json()
        return PickOrder(
            order_id=data["order_id"],
            sku=data["sku"],
            qty=int(data["qty"]),
            tray_id=data["tray_id"],
        )

    def confirm_pick(self, order_id: str, result: str) -> None:
        url = f"{self._base_url}/api/v1/orders/{order_id}/confirm"
        response = httpx.post(
            url,
            json={"result": result},
            timeout=self._timeout,
        )
        response.raise_for_status()
