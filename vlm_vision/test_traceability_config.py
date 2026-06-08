#!/usr/bin/env python
"""
test_traceability_config.py  --  test the .env config loader.

RUN (from the vlm_vision/ directory, venv active):
    python test_traceability_config.py
"""

import os
import shutil
import sys

from local_agent.traceability.traceability_config import TraceabilityConfig

TEST_DIR = "test_config_output"
ENV_PATH = os.path.join(TEST_DIR, ".env")

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


def write_env(text):
    os.makedirs(TEST_DIR, exist_ok=True)
    with open(ENV_PATH, "w") as f:
        f.write(text)


def run():
    if os.path.isdir(TEST_DIR):
        shutil.rmtree(TEST_DIR)

    print("Fully-configured .env")
    write_env(
        "TRACEABILITY_DB_PATH=data/custom.db\n"
        "VIDEO_FPS=20\n"
        "BARCODE_MATCH_WINDOW_SEC=7.5\n"
        "VIDEO_CAMERA_IDS=2,3,4\n"
        "CATALYST_PROJECT_ID=35344000000152001\n"
        "CATALYST_FUNCTION_BASE_URL=https://realurl.example/server/vlm_vision_function\n"
        "CLOUD_SYNC_INTERVAL_SEC=45\n"
        "CATALYST_CLIENT_ID=1000.ABCDEF\n"
        "CATALYST_CLIENT_SECRET=supersecretvalue\n"
        "CATALYST_REFRESH_TOKEN=1000.refreshvalue\n"
    )
    cfg = TraceabilityConfig.load(ENV_PATH)
    check("string value read", cfg.traceability_db_path == "data/custom.db")
    check("int value converted", cfg.video_fps == 20 and isinstance(cfg.video_fps, int))
    check("float value converted", cfg.barcode_match_window_sec == 7.5)
    check("camera id list parsed", cfg.video_camera_ids == [2, 3, 4])
    check("project id read", cfg.catalyst_project_id == "35344000000152001")
    check("cloud_sync_interval is float", cfg.cloud_sync_interval_sec == 45.0)
    check("is_cloud_configured() True when all set", cfg.is_cloud_configured())

    print("\nSecret masking")
    summary = cfg.safe_summary()
    check("client_secret is masked", summary["catalyst_client_secret"] != "supersecretvalue",
          f"got {summary['catalyst_client_secret']}")
    check("refresh_token is masked", "refreshvalue" not in str(summary["catalyst_refresh_token"]))
    check("project id NOT masked (not a secret)",
          summary["catalyst_project_id"] == "35344000000152001")

    print("\nMissing keys fall back to defaults")
    write_env("VIDEO_FPS=12\n")
    cfg2 = TraceabilityConfig.load(ENV_PATH)
    check("present key read", cfg2.video_fps == 12)
    check("missing string -> default", cfg2.traceability_db_path == "data/traceability.db")
    check("missing float -> default", cfg2.evidence_clip_margin_sec == 30.0)
    check("missing camera ids -> default [0,1]", cfg2.video_camera_ids == [0, 1])
    check("missing accounts url -> default",
          cfg2.catalyst_accounts_url == "https://accounts.zoho.com")

    print("\nPlaceholder function URL means not-yet-configured")
    write_env(
        "CATALYST_CLIENT_ID=1000.ABC\n"
        "CATALYST_CLIENT_SECRET=secret\n"
        "CATALYST_REFRESH_TOKEN=1000.refresh\n"
        "CATALYST_FUNCTION_BASE_URL=https://YOUR_FUNCTION_BASE_URL/server/vlm_vision_function\n"
    )
    cfg3 = TraceabilityConfig.load(ENV_PATH)
    check("secrets present but URL is placeholder -> not configured",
          not cfg3.is_cloud_configured())

    print("\nMissing .env file entirely")
    cfg4 = TraceabilityConfig.load(os.path.join(TEST_DIR, "does_not_exist.env"))
    check("loads with defaults when file absent", cfg4.video_fps == 15)
    check("not cloud configured with no secrets", not cfg4.is_cloud_configured())

    print("\n" + "=" * 50)
    print(f"  RESULTS: {_passed} passed, {_failed} failed")
    print("=" * 50)
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    run()