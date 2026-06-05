# vlm_vision/local_agent/traceability/sync_runner.py
"""
SyncRunner -- runs CloudSync.sync_pending() on a loop in the background.

sync_pending() does one pass. On the factory PC nobody calls it by hand, so
this runner wakes up every `interval_sec`, runs a pass, and waits again --
forever, until stopped. It is built for unattended operation:

  * a failing cycle never kills the loop (caught + logged, retried next time),
  * stop() returns promptly (it waits on an Event, not a bare sleep, so Ctrl+C
    or shutdown doesn't hang for up to a full interval),
  * run_once() is exposed too, for tests or a manual "sync now" button.

Usage:
    runner = SyncRunner(cloud_sync, interval_sec=60)
    runner.start()
    ...
    runner.stop()
"""
import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SyncRunner:
    def __init__(self, cloud_sync, interval_sec: float = 60.0):
        self.cloud_sync = cloud_sync
        self.interval_sec = interval_sec
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_result: Optional[Dict[str, int]] = None
        self._cycles = 0

    def run_once(self) -> Dict[str, int]:
        """Run a single sync pass. Never raises -- failures are logged and
        returned as a result so the caller (and the loop) keep going."""
        try:
            result = self.cloud_sync.sync_pending()
        except Exception as e:
            logger.error("Sync cycle failed: %s", e)
            result = {"uploaded": 0, "blocked": 0, "failed": 0, "error": str(e)}
        self._last_result = result
        self._cycles += 1
        return result

    def _loop(self) -> None:
        logger.info("SyncRunner started (every %.0fs)", self.interval_sec)
        while not self._stop.is_set():
            self.run_once()
            # Interruptible wait: returns immediately when stop() is called.
            self._stop.wait(timeout=self.interval_sec)
        logger.info("SyncRunner stopped after %d cycle(s)", self._cycles)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("SyncRunner already running")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="cloud-sync")
        self._thread.start()

    def stop(self, join_timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=join_timeout)

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def last_result(self) -> Optional[Dict[str, int]]:
        return self._last_result

    @property
    def cycles(self) -> int:
        return self._cycles