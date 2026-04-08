import os
from dataclasses import dataclass
from typing import List


@dataclass
class Config:
    model_path: str
    camera_ids: List[int]
    modula_wms_url: str
    cloud_sync_url: str
    detection_fps: int = 10
    websocket_port: int = 8765
    db_path: str = "picks.db"
    model_dir: str = "models"
    sync_interval_sec: int = 30
    model_poll_interval_sec: int = 3600

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            model_path=os.environ["MODEL_PATH"],
            camera_ids=[
                int(os.environ.get("CAMERA_BAY1", "0")),
                int(os.environ.get("CAMERA_BAY2", "1")),
            ],
            modula_wms_url=os.environ["MODULA_WMS_URL"],
            cloud_sync_url=os.environ["CLOUD_SYNC_URL"],
            detection_fps=int(os.environ.get("DETECTION_FPS", "10")),
            websocket_port=int(os.environ.get("WEBSOCKET_PORT", "8765")),
            db_path=os.environ.get("DB_PATH", "picks.db"),
            model_dir=os.environ.get("MODEL_DIR", "models"),
            sync_interval_sec=int(os.environ.get("SYNC_INTERVAL_SEC", "30")),
            model_poll_interval_sec=int(os.environ.get("MODEL_POLL_INTERVAL_SEC", "3600")),
        )
