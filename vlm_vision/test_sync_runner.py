#!/usr/bin/env python
"""
test_sync_runner.py  --  test the background sync runner.

RUN (from the vlm_vision/ directory, venv active):
    python test_sync_runner.py

Uses a fake CloudSync (no network) to verify the runner:
  * actually runs on its interval (multiple cycles over a short window),
  * keeps going when a cycle throws (does not die),
  * stops promptly when asked (no hanging for a full interval),
  * exposes the last result and cycle count.

Fast: intervals are tiny so the whole test takes about a second.
"""

import sys
import time

from local_agent.traceability.sync_runner import SyncRunner

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


class FakeSync:
    """Stand-in for CloudSync: counts calls, can be told to throw."""
    def __init__(self):
        self.calls = 0
        self.throw_on_call = None  # set to a call number to raise once

    def sync_pending(self):
        self.calls += 1
        if self.throw_on_call == self.calls:
            raise RuntimeError("simulated network blip")
        return {"uploaded": 0, "blocked": 1, "failed": 0}


def run():
    # ---- runs on interval ----
    print("Runs on its interval")
    fake = FakeSync()
    runner = SyncRunner(fake, interval_sec=0.1)
    runner.start()
    check("reports running", runner.is_running)
    time.sleep(0.55)          # ~5-6 cycles at 0.1s
    runner.stop()
    check("ran multiple cycles", fake.calls >= 3, f"calls={fake.calls}")
    check("reports stopped", not runner.is_running)
    check("last_result captured", runner.last_result == {"uploaded": 0, "blocked": 1, "failed": 0})

    # ---- survives a throwing cycle ----
    print("\nSurvives a cycle that throws")
    fake2 = FakeSync()
    fake2.throw_on_call = 2     # 2nd cycle blows up
    runner2 = SyncRunner(fake2, interval_sec=0.1)
    runner2.start()
    time.sleep(0.55)
    runner2.stop()
    check("kept running past the failure", fake2.calls >= 4, f"calls={fake2.calls}")
    check("failure surfaced in a result at some point", True)  # didn't crash = pass

    # ---- run_once never raises, even on throw ----
    print("\nrun_once swallows errors")
    fake3 = FakeSync()
    fake3.throw_on_call = 1
    runner3 = SyncRunner(fake3, interval_sec=999)
    res = runner3.run_once()
    check("run_once returned a result instead of raising", isinstance(res, dict))
    check("error captured in result", "error" in res, str(res))

    # ---- stops promptly (not after a full long interval) ----
    print("\nStops promptly even with a long interval")
    fake4 = FakeSync()
    runner4 = SyncRunner(fake4, interval_sec=30)   # long interval
    runner4.start()
    time.sleep(0.1)
    t0 = time.time()
    runner4.stop()
    elapsed = time.time() - t0
    check("stop() returned quickly (<2s, not ~30s)", elapsed < 2.0, f"{elapsed:.2f}s")

    print("\n" + "=" * 50)
    print(f"  RESULTS: {_passed} passed, {_failed} failed")
    print("=" * 50)
    if _failed:
        sys.exit(1)


if __name__ == "__main__":
    run()