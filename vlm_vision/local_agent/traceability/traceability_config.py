# vlm_vision/local_agent/traceability/traceability_config.py
"""
TraceabilityConfig -- reads .env and hands out the traceability + cloud
settings by name.

Named distinctly so it does NOT collide with the existing Process 1
local_agent/config.py (the bay agent's Config), which we never touch.

That existing Config reads straight from os.environ and does not load .env at
all -- so this loader is also the piece that actually READS the .env file
(via python-dotenv) for the traceability and cloud side.

Load order for each value (first hit wins):
    1. the .env file
    2. the real process environment (os.environ)
    3. a sensible built-in default

.env is located reliably (walking up from this file to the project root), so
it loads correctly no matter which directory Python is launched from -- which
matters once this runs unattended on the factory PC. Never raises if .env is
missing; falls back to defaults.

Usage:
    from local_agent.traceability.traceability_config import TraceabilityConfig
    cfg = TraceabilityConfig.load()
    if cfg.is_cloud_configured():
        ...
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from dotenv import dotenv_values

logger = logging.getLogger(__name__)

_PLACEHOLDER = "YOUR_FUNCTION_BASE_URL"


def _find_env_file() -> Optional[str]:
    """Find the project's .env by walking up from this file's location.

    This module lives at <project>/local_agent/traceability/, so the project
    root (where .env sits) is two directories up. We still walk up a few levels
    to be safe in case the layout shifts. Returns the path, or None if no .env
    is found (in which case the loader uses defaults).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    d = here
    for _ in range(5):
        candidate = os.path.join(d, ".env")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:  # reached filesystem root
            break
        d = parent
    return None


@dataclass
class TraceabilityConfig:
    # local paths
    traceability_db_path: str = "data/traceability.db"
    clip_requests_dir: str = "data/clip_requests"
    video_output_dir: str = "data/video"
    video_clip_dir: str = "data/clips"

    # traceability
    barcode_match_window_sec: float = 5.0
    evidence_clip_margin_sec: float = 30.0

    # video recorder
    video_fps: int = 15
    video_segment_minutes: int = 5
    video_retention_days: int = 60
    video_camera_ids: List[int] = field(default_factory=lambda: [0, 1])

    # cloud (Zoho Catalyst)
    catalyst_project_id: str = ""
    catalyst_folder_evidence_clips: str = ""
    catalyst_folder_video_segments: str = ""
    catalyst_function_base_url: str = ""
    cloud_sync_interval_sec: float = 60.0
    catalyst_client_id: str = ""
    catalyst_client_secret: str = ""
    catalyst_refresh_token: str = ""
    catalyst_accounts_url: str = "https://accounts.zoho.com"

    # ---- loading ----------------------------------------------------------

    @classmethod
    def load(cls, env_path: Optional[str] = None) -> "TraceabilityConfig":
        """Build from a .env file, the environment, and built-in defaults.

        If env_path is given, that file is used. Otherwise the project's .env
        is located automatically (works from any working directory).
        """
        if env_path is None:
            env_path = _find_env_file()
        # dotenv_values reads the file WITHOUT mutating os.environ -- keeps this
        # predictable and test-friendly.
        file_vals = dotenv_values(env_path) if (env_path and os.path.isfile(env_path)) else {}

        def get(key: str, default):
            v = file_vals.get(key)
            if v is None or v == "":
                v = os.environ.get(key)
            return v if v not in (None, "") else default

        def get_int(key, default):
            try:
                return int(get(key, default))
            except (TypeError, ValueError):
                return default

        def get_float(key, default):
            try:
                return float(get(key, default))
            except (TypeError, ValueError):
                return default

        def get_camera_ids(key, default):
            raw = get(key, None)
            if not raw:
                return list(default)
            try:
                return [int(x.strip()) for x in str(raw).split(",") if x.strip() != ""]
            except ValueError:
                return list(default)

        return cls(
            traceability_db_path=get("TRACEABILITY_DB_PATH", "data/traceability.db"),
            clip_requests_dir=get("CLIP_REQUESTS_DIR", "data/clip_requests"),
            video_output_dir=get("VIDEO_OUTPUT_DIR", "data/video"),
            video_clip_dir=get("VIDEO_CLIP_DIR", "data/clips"),
            barcode_match_window_sec=get_float("BARCODE_MATCH_WINDOW_SEC", 5.0),
            evidence_clip_margin_sec=get_float("EVIDENCE_CLIP_MARGIN_SEC", 30.0),
            video_fps=get_int("VIDEO_FPS", 15),
            video_segment_minutes=get_int("VIDEO_SEGMENT_MINUTES", 5),
            video_retention_days=get_int("VIDEO_RETENTION_DAYS", 60),
            video_camera_ids=get_camera_ids("VIDEO_CAMERA_IDS", [0, 1]),
            catalyst_project_id=get("CATALYST_PROJECT_ID", ""),
            catalyst_folder_evidence_clips=get("CATALYST_FOLDER_EVIDENCE_CLIPS", ""),
            catalyst_folder_video_segments=get("CATALYST_FOLDER_VIDEO_SEGMENTS", ""),
            catalyst_function_base_url=get("CATALYST_FUNCTION_BASE_URL", ""),
            cloud_sync_interval_sec=get_float("CLOUD_SYNC_INTERVAL_SEC", 60.0),
            catalyst_client_id=get("CATALYST_CLIENT_ID", ""),
            catalyst_client_secret=get("CATALYST_CLIENT_SECRET", ""),
            catalyst_refresh_token=get("CATALYST_REFRESH_TOKEN", ""),
            catalyst_accounts_url=get("CATALYST_ACCOUNTS_URL", "https://accounts.zoho.com"),
        )

    # ---- helpers ----------------------------------------------------------

    def is_cloud_configured(self) -> bool:
        """True only if every secret is filled AND the function URL is real
        (not the placeholder). Lets the agent decide whether to start syncing."""
        secrets_present = all([
            self.catalyst_client_id,
            self.catalyst_client_secret,
            self.catalyst_refresh_token,
        ])
        url_real = bool(self.catalyst_function_base_url) and _PLACEHOLDER not in self.catalyst_function_base_url
        return secrets_present and url_real

    def safe_summary(self) -> Dict[str, object]:
        """A view of the config safe to log -- secrets are masked."""
        def mask(s: str) -> str:
            if not s:
                return "(empty)"
            return s[:4] + "..." if len(s) > 4 else "***"
        return {
            "traceability_db_path": self.traceability_db_path,
            "video_camera_ids": self.video_camera_ids,
            "catalyst_project_id": self.catalyst_project_id or "(empty)",
            "catalyst_function_base_url": self.catalyst_function_base_url or "(empty)",
            "cloud_sync_interval_sec": self.cloud_sync_interval_sec,
            "catalyst_client_id": mask(self.catalyst_client_id),
            "catalyst_client_secret": mask(self.catalyst_client_secret),
            "catalyst_refresh_token": mask(self.catalyst_refresh_token),
            "is_cloud_configured": self.is_cloud_configured(),
        }