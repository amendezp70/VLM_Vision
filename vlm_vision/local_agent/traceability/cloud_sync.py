# vlm_vision/local_agent/traceability/cloud_sync.py
"""
CloudSync -- pushes locally-recorded evidence to the Zoho Catalyst cloud.

The local EventStore is the source of truth and the offline buffer. This
client periodically takes whatever has NOT been uploaded yet and sends it to
the Catalyst function (the Node/Express service in functions/vlm_vision_function),
which writes the rows into the Datastore tables.

Flow for each pending clip:
    1. upload the .mp4 file to the File Store  ->  returns a cloud_url
       *** THIS STEP IS A STUB -- see _upload_file_to_filestore() ***
    2. POST /video/clips with the metadata + cloud_url   (records the DB row)
    3. mark the clip uploaded locally so it is never sent twice

Only step 1 is blocked (needs a File Store credential / endpoint from Dhar).
Steps 2 and 3 are complete and match the function's real request shapes:
  - POST /video/clips    requires clip_id, event_id, cloud_url
  - POST /video/segments requires segment_id, cloud_url
(see functions/vlm_vision_function/routes/video.js)

The cloud column names differ slightly from our local ones; the mapping
below follows the schema documented in services/video_datastore.js.
"""
import logging
import os
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class FileUploadNotConfigured(Exception):
    """Raised by the file-upload stub until the real upload is wired in."""


class CloudSync:
    def __init__(
        self,
        event_store,
        function_base_url: str,
        request_timeout: float = 15.0,
        enable_file_upload: bool = False,
    ):
        # function_base_url example:
        #   https://<project>.development.catalystserverless.com/server/vlm_vision_function
        self.store = event_store
        self.base_url = function_base_url.rstrip("/")
        self.timeout = request_timeout
        # Stays False until Dhar gives us the File Store upload method. While
        # False, sync_pending() reports clips as "blocked" instead of faking it.
        self.enable_file_upload = enable_file_upload

    @classmethod
    def from_config(cls, cfg, event_store, enable_file_upload: bool = False) -> "CloudSync":
        """Build a CloudSync from a TraceabilityConfig.

        enable_file_upload stays False by default: the file-upload step needs
        a File Store scope we don't have yet, so the agent leaves it off until
        that's wired in (then flips it to True).
        """
        return cls(
            event_store=event_store,
            function_base_url=cfg.catalyst_function_base_url,
            enable_file_upload=enable_file_upload,
        )

    # ---- health -----------------------------------------------------------

    def health_check(self) -> bool:
        """Return True if the function's /health endpoint answers ok."""
        try:
            r = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            return r.ok and r.json().get("status") == "ok"
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return False

    # ---- the blocked step -------------------------------------------------

    def _upload_file_to_filestore(self, local_path: str, folder: str) -> str:
        """Upload a local file to the Catalyst File Store and return its URL.

        *** STUB -- NOT YET IMPLEMENTED ***
        We are waiting on one of two things from Dhar (see the message we sent):
          (a) a File Store upload credential/scope so we can upload from here, OR
          (b) a new upload endpoint on his function so we never hold a credential.
        Until then this raises, and sync_pending() treats the clip as blocked
        (left pending, to retry once this is wired in). Nothing is faked.
        """
        raise FileUploadNotConfigured(
            "File Store upload not configured yet -- waiting on Dhar "
            "(credential or an upload endpoint). local_path=%s folder=%s"
            % (local_path, folder)
        )

    # ---- mapping local rows -> cloud request bodies -----------------------

    def _clip_to_cloud_body(self, clip: Dict, cloud_url: str) -> Dict:
        """Map a local clips-row to the body POST /video/clips expects.

        Cloud column names come from services/video_datastore.js:
          clip_id, event_id, segment_id, clip_start_sec, clip_end_sec,
          cloud_url, generated_at, retained_indefinitely
        """
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

    def _post_segment(self, body: Dict) -> bool:
        try:
            r = requests.post(f"{self.base_url}/video/segments", json=body, timeout=self.timeout)
            if r.ok:
                return True
            logger.error("POST /video/segments rejected (%s): %s", r.status_code, r.text)
            return False
        except Exception as e:
            logger.error("POST /video/segments failed: %s", e)
            return False

    # ---- the main loop ----------------------------------------------------

    def sync_pending(self) -> Dict[str, int]:
        """Try to push every not-yet-uploaded clip to the cloud.

        Returns counts: {"uploaded": n, "blocked": n, "failed": n}.
        A clip is only marked uploaded locally after the cloud row is written,
        so an interruption just leaves it pending for next time (safe to rerun).
        """
        uploaded = blocked = failed = 0
        pending = self.store.pending_uploads()
        logger.info("CloudSync: %d clip(s) pending", len(pending))

        for clip in pending:
            clip_id = clip.get("clip_id")
            local_path = clip.get("file_path")

            # Step 1: get the file into the File Store (blocked for now).
            if not self.enable_file_upload:
                blocked += 1
                continue
            try:
                cloud_url = self._upload_file_to_filestore(local_path, "evidence_clips")
            except FileUploadNotConfigured:
                blocked += 1
                continue
            except Exception as e:
                logger.error("Upload failed for %s: %s", clip_id, e)
                failed += 1
                continue

            # Step 2: record the row in the cloud via the function.
            body = self._clip_to_cloud_body(clip, cloud_url)
            if not (body["clip_id"] and body["event_id"] and body["cloud_url"]):
                logger.error("Clip %s missing required fields for cloud insert", clip_id)
                failed += 1
                continue
            if not self._post_clip(body):
                failed += 1
                continue

            # Step 3: mark uploaded locally so we never send it twice.
            try:
                self.store.mark_uploaded(clip_id, cloud_url)
                uploaded += 1
            except Exception as e:
                logger.error("Marked-uploaded failed for %s: %s", clip_id, e)
                failed += 1

        result = {"uploaded": uploaded, "blocked": blocked, "failed": failed}
        logger.info("CloudSync result: %s", result)
        return result