#!/usr/bin/env python
"""
test_cloud_sync.py  --  test the cloud sync client WITHOUT touching real Zoho.

RUN (from the vlm_vision/ directory, venv active):
    python test_cloud_sync.py

It starts a tiny local web server that imitates the Catalyst function's video
routes -- including the SAME required-field checks as routes/video.js
(clip_id, event_id, cloud_url). Then it:
  * checks health_check() works,
  * confirms that with file-upload OFF, clips are reported "blocked" and NOT
    faked or marked uploaded,
  * with file-upload simulated ON, confirms the clip is posted with the
    correct cloud column names and then marked uploaded locally,
  * confirms the server actually received the right request body.

Pure local sockets -- no internet, no credentials.
"""

import json
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from local_agent.traceability.event_store import EventStore
from local_agent.traceability.cloud_sync import CloudSync

TEST_DIR = "test_cloudsync_output"
DB_PATH = os.path.join(TEST_DIR, "traceability.db")

_passed = 0
_failed = 0


def check(name, condition, detail=""):
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
    line = f"  [{'PASS' if condition else 'FAIL'}] {name}"
    if detail:
        line += f"   ({detail})"
    print(line)
    return condition


# ---- a fake "Catalyst function" that mimics routes/video.js -----------------

RECEIVED = {"clips": [], "segments": []}


class FakeFunctionHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence the default request logging

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "service": "vlm_vision_function"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/video/clips":
            # same validation as routes/video.js
            if not (body.get("clip_id") and body.get("event_id") and body.get("cloud_url")):
                return self._send(400, {"error": "clip_id, event_id, and cloud_url are required"})
            RECEIVED["clips"].append(body)
            self._send(200, {"ok": True, "clip": body})
        elif self.path == "/video/segments":
            if not (body.get("segment_id") and body.get("cloud_url")):
                return self._send(400, {"error": "segment_id and cloud_url are required"})
            RECEIVED["segments"].append(body)
            self._send(200, {"ok": True, "segment": body})
        else:
            self._send(404, {"error": "not found"})


class MatchStatus(Enum):
    MATCH = "match"
    MISMATCH = "mismatch"


@dataclass
class FakeEvent:
    box_id: Optional[str]
    zone_id: int
    barcode_camera: Optional[str]
    barcode_scanner: Optional[str]
    match_status: MatchStatus
    timestamp: float

    @property
    def is_verified(self):
        return self.match_status == MatchStatus.MATCH


def run():
    if os.path.isdir(TEST_DIR):
        shutil.rmtree(TEST_DIR)
    os.makedirs(TEST_DIR, exist_ok=True)

    # start the fake function on a free port
    server = HTTPServer(("127.0.0.1", 0), FakeFunctionHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{port}"
    print(f"Fake function listening at {base_url}\n")

    # seed the store with one mismatch event + its clip (so it is pending)
    store = EventStore(db_path=DB_PATH)
    ts = time.time()
    ev = FakeEvent("BOX-9", 2, "0687456223537", "9999999999999", MatchStatus.MISMATCH, ts)
    store.record_event(ev)
    store.record_clip(
        clip_id="CLIP-9", request_id="CLIP-9", event_timestamp=ts,
        reason="barcode_mismatch", zone_id=2, camera_id=3, box_id="BOX-9",
        clip_start=ts - 30, clip_end=ts + 30, segment_file="cam3_x.mp4",
        offset_sec=60.0, file_path=os.path.join(TEST_DIR, "clip.mp4"),
    )
    # create a dummy local file so a future real upload would have something
    with open(os.path.join(TEST_DIR, "clip.mp4"), "wb") as f:
        f.write(b"fake video bytes")

    sync = CloudSync(store, function_base_url=base_url)

    # ---- health ----
    print("Health check")
    check("function health is ok", sync.health_check())

    # ---- file upload OFF: should be reported blocked, not faked ----
    print("\nFile upload OFF (the real situation until Dhar answers)")
    res = sync.sync_pending()
    check("1 clip reported blocked", res["blocked"] == 1, str(res))
    check("0 uploaded while blocked", res["uploaded"] == 0)
    check("nothing posted to the function yet", len(RECEIVED["clips"]) == 0)
    check("clip still pending locally (not faked)", len(store.pending_uploads()) == 1)

    # ---- simulate file upload ON by replacing just the stub method ----
    print("\nFile upload simulated ON (replacing only the stub method)")
    sync.enable_file_upload = True
    sync._upload_file_to_filestore = (
        lambda local_path, folder: f"https://filestore.example/{folder}/CLIP-9.mp4"
    )
    res = sync.sync_pending()
    check("1 clip uploaded", res["uploaded"] == 1, str(res))
    check("0 blocked now", res["blocked"] == 0)
    check("function received exactly 1 clip", len(RECEIVED["clips"]) == 1)

    if RECEIVED["clips"]:
        body = RECEIVED["clips"][0]
        check("body has clip_id", body.get("clip_id") == "CLIP-9")
        check("body has event_id (linked)", bool(body.get("event_id")))
        check("body has cloud_url", body.get("cloud_url", "").endswith("CLIP-9.mp4"))
        # local clip_start -> cloud clip_start_sec mapping
        check("mapped clip_start -> clip_start_sec", "clip_start_sec" in body)
        check("uses cloud column names, not local",
              "clip_start" not in body and "clip_start_sec" in body)

    check("clip now marked uploaded locally", len(store.pending_uploads()) == 0)

    # ---- rerun is safe: nothing left to send ----
    print("\nRerun safety")
    res = sync.sync_pending()
    check("rerun sends nothing (idempotent)",
          res == {"uploaded": 0, "blocked": 0, "failed": 0}, str(res))

    server.shutdown()
    print("\n" + "=" * 52)
    print(f"  RESULTS: {_passed} passed, {_failed} failed")
    print("=" * 52)
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    run()