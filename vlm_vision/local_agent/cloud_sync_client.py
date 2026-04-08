# vlm_vision/local_agent/cloud_sync_client.py
"""
HTTP client for Zoho Catalyst cloud endpoints.
Pushes confirmed pick events and checks for model updates.
"""
import logging
from typing import Dict, List, Optional

import requests

from local_agent.models import PickEvent

logger = logging.getLogger(__name__)


class CloudSyncClient:
    def __init__(self, base_url: str, timeout: int = 10) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def push_picks(self, events: List[PickEvent]) -> bool:
        """Push a batch of pick events to the cloud. Returns True on success."""
        if not events:
            return True
        payload = {
            "events": [
                {
                    "order_id": e.order_id,
                    "sku": e.sku,
                    "qty_picked": e.qty_picked,
                    "bay_id": e.bay_id,
                    "worker_id": e.worker_id,
                    "result": e.result,
                    "timestamp": e.timestamp,
                }
                for e in events
            ]
        }
        try:
            resp = requests.post(
                f"{self._base_url}/picks/sync",
                json=payload,
                timeout=self._timeout,
            )
            if resp.status_code == 200:
                return True
            logger.warning("Push picks failed: HTTP %d", resp.status_code)
            return False
        except Exception:
            logger.warning("Push picks failed: network error", exc_info=True)
            return False

    def check_model_version(self) -> Optional[Dict]:
        """Check cloud for latest model version. Returns {"version": ..., "url": ...} or None."""
        try:
            resp = requests.get(
                f"{self._base_url}/models/latest",
                timeout=self._timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            logger.debug("Model version check failed", exc_info=True)
            return None

    def download_model(self, url: str, dest: str) -> bool:
        """Download an ONNX model file to dest path. Returns True on success."""
        try:
            resp = requests.get(url, timeout=60, stream=True)
            if resp.status_code != 200:
                return False
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception:
            logger.warning("Model download failed", exc_info=True)
            return False
