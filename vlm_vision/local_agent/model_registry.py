# vlm_vision/local_agent/model_registry.py
"""
Polls the cloud for model updates and downloads new ONNX files.
Does NOT load the model — returns the new file path so the caller can hot-swap.
"""
import logging
import os
from typing import Optional

from local_agent.cloud_sync_client import CloudSyncClient

logger = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(
        self,
        cloud_client: CloudSyncClient,
        model_dir: str,
        current_model_path: str,
    ) -> None:
        self._client = cloud_client
        self._model_dir = model_dir
        self._current_model_path = current_model_path
        self._current_version: Optional[str] = None
        os.makedirs(model_dir, exist_ok=True)

    def check_and_update(self) -> Optional[str]:
        """Check cloud for a new model version.

        Returns:
            Path to the newly downloaded ONNX file if updated, else None.
        """
        info = self._client.check_model_version()
        if info is None:
            return None

        version = info.get("version")
        url = info.get("url")
        if not version or not url:
            return None

        if version == self._current_version:
            logger.debug("Model version %s is current", version)
            return None

        dest = os.path.join(self._model_dir, f"model_{version}.onnx")
        logger.info("Downloading model %s from %s", version, url)

        if self._client.download_model(url=url, dest=dest):
            self._current_version = version
            self._current_model_path = dest
            logger.info("Model updated to %s at %s", version, dest)
            return dest

        logger.warning("Model download failed for %s", version)
        return None
