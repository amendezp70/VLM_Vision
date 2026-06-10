# vlm_vision/local_agent/traceability/cloud_sync.py
"""
CloudSync -- pushes locally-recorded evidence to the Zoho Catalyst cloud.

The local EventStore is the source of truth and the offline buffer. This
client periodically takes whatever has NOT been uploaded yet and sends it up:

Flow for each pending clip:
    1. upload the .mp4 to the Catalyst File Store  ->  returns a file reference
    2. POST /video/clips (the function) with metadata + that reference
    3. mark the clip uploaded locally so it is never sent twice

Step 1 uploads directly to the File Store using a token from CatalystAuth
(which auto-refreshes). The upload response gives a numeric file id; we store a
canonical file reference URL as the clip's cloud_url.

Request shapes match functions/vlm_vision_function/routes/video.js:
  - POST /video/clips    requires clip_id, event_id, cloud_url
  - POST /video/segments requires segment_id, cloud_url
Cloud column names follow services/video_datastore.js.
"""
import logging
import os
from typing import Dict, List, Optional

import requests

from local_agent.traceability.catalyst_auth import CatalystAuth, CatalystAuthError

logger = logging.getLogger(__name__)

_FILESTORE_BASE = "https://api.catalyst.zoho.com/baas/v1"


class FileUploadNotConfigured(Exception):
    """Raised when the File Store upload can't run (missing auth/ids)."""


class CloudSync:
    def __init__(
        self,
        event_store,
        function_base_url: str,
        request_timeout: float = 30.0,
        enable_file_upload: bool = False,
        auth: Optional[CatalystAuth] = None,
        project_id: str = "",
        folder_evidence_clips: str = "",
        folder_video_segments: str = "",
        filestore_base: str = _FILESTORE_BASE,
    ):
        self.store = event_store
        self.base_url = function_base_url.rstrip("/")
        self.timeout = request_timeout
        self.enable_file_upload = enable_file_upload
        self.auth = auth
        self.project_id = project_id
        self.folder_evidence_clips = folder_evidence_clips
        self.folder_video_segments = folder_video_segments
        self.filestore_base = filestore_base.rstrip("/")

    @classmethod
    def from_config(cls, cfg, event_store, enable_file_upload: bool = False) -> "CloudSync":
        """Build a CloudSync from a TraceabilityConfig. Builds a CatalystAuth
        from the .env credentials when they are present."""
        auth = None
        try:
            candidate = CatalystAuth.from_config(cfg)
            if candidate.has_credentials():
                auth = candidate
        except Exception as e:
            logger.error("Could not build CatalystAuth: %s", e)
        return cls(
            event_store=event_store,
            function_base_url=cfg.catalyst_function_base_url,
            enable_file_upload=enable_file_upload,
            auth=auth,
            project_id=cfg.catalyst_project_id,
            folder_evidence_clips=cfg.catalyst_folder_evidence_clips,
            folder_video_segments=cfg.catalyst_folder_video_segments,
        )

    # ---- health -----------------------------------------------------------

    def health_check(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            return r.ok and r.json().get("status") == "ok"
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return False

    # ---- File Store upload (real) -----------------------------------------

    def _upload_file_to_filestore(self, local_path: str, folder: str = "evidence_clips") -> str:
        """Upload a local file to the Catalyst File Store and return a canonical
        file reference URL (stored as the clip's cloud_url).

        Resolves the folder name to its configured folder id, gets a valid
        token from CatalystAuth, POSTs the file, and parses the returned id.
        """
        if self.auth is None or not self.project_id:
            raise FileUploadNotConfigured("Catalyst auth/project_id not configured")
        folder_id = (self.folder_evidence_clips if folder == "evidence_clips"
                     else self.folder_video_segments)
        if not folder_id:
            raise FileUploadNotConfigured(f"No folder id configured for '{folder}'")
        if not (local_path and os.path.isfile(local_path)):
            raise FileUploadNotConfigured(f"Local file not found: {local_path}")

        token = self.auth.get_token()
        url = f"{self.filestore_base}/project/{self.project_id}/folder/{folder_id}/file"
        fname = os.path.basename(local_path)
        # Zoho's File Store rejects a file part with no content-type ("Invalid
        # content type"). curl sets one automatically; requests does not unless
        # we pass it explicitly, so guess it from the extension like curl does.
        import mimetypes
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        with open(local_path, "rb") as fh:
            r = requests.post(
                url,
                headers={"Authorization": f"Zoho-oauthtoken {token}"},
                files={"code": (fname, fh, ctype)},
                data={"file_name": fname},
                timeout=self.timeout,
            )
        try:
            payload = r.json()
        except Exception:
            raise FileUploadNotConfigured(f"Upload returned non-JSON (HTTP {r.status_code})")
        if payload.get("status") != "success":
            raise FileUploadNotConfigured(f"Upload failed: {payload}")
        file_id = payload.get("data", {}).get("id")
        if not file_id:
            raise FileUploadNotConfigured(f"No file id in upload response: {payload}")
        # Canonical reference to the stored file (dashboard builds the download).
        return f"{self.filestore_base}/project/{self.project_id}/folder/{folder_id}/file/{file_id}"

    # ---- mapping local rows -> cloud request bodies -----------------------

    def _clip_to_cloud_body(self, clip: Dict, cloud_url: str) -> Dict:
        return {
            "clip_id": clip.get("clip_id"),
            "event_id": clip.get("event_id"),
            "segment_id": clip.get("segment_id") or "",
            "clip_start_sec": clip.get("clip_start"),
            "clip_end_sec": clip.get("clip_end"),
            "cloud_url": cloud_url,
            "generated_at": clip.get("created_at"),
            "retained_indefinitely": True,
        }

    # ---- posting to the function -----------------------------------------

    def _post_clip(self, body: Dict) -> bool:
        try:
            r = requests.post(f"{self.base_url}/video/clips", json=body, timeout=self.timeout)
            if r.ok:
                return True
            logger.error("POST /video/clips rejected (%s): %s", r.status_code, r.text)
            return False
        except Exception as e:
            logger.error("POST /video/clips failed: %s", e)
            return False

    # ---- the main loop ----------------------------------------------------

    def sync_pending(self) -> Dict[str, int]:
        uploaded = blocked = failed = 0
        pending = self.store.pending_uploads()
        logger.info("CloudSync: %d clip(s) pending", len(pending))

        for clip in pending:
            clip_id = clip.get("clip_id")
            local_path = clip.get("file_path")

            if not self.enable_file_upload:
                blocked += 1
                continue
            try:
                cloud_url = self._upload_file_to_filestore(local_path, "evidence_clips")
            except (FileUploadNotConfigured, CatalystAuthError) as e:
                logger.warning("Upload not done for %s: %s", clip_id, e)
                blocked += 1
                continue
            except Exception as e:
                logger.error("Upload failed for %s: %s", clip_id, e)
                failed += 1
                continue

            body = self._clip_to_cloud_body(clip, cloud_url)
            if not (body["clip_id"] and body["event_id"] and body["cloud_url"]):
                logger.error("Clip %s missing required fields for cloud insert", clip_id)
                failed += 1
                continue
            if not self._post_clip(body):
                failed += 1
                continue

            try:
                self.store.mark_uploaded(clip_id, cloud_url)
                uploaded += 1
            except Exception as e:
                logger.error("Marked-uploaded failed for %s: %s", clip_id, e)
                failed += 1

        result = {"uploaded": uploaded, "blocked": blocked, "failed": failed}
        logger.info("CloudSync result: %s", result)
        return result