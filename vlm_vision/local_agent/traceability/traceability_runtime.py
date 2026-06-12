# vlm_vision/local_agent/traceability/traceability_runtime.py
"""
TraceabilityRuntime -- assembles and runs the "memory + cloud" layer of the
traceability system, so the main agent (main.py) can wire it in with a few
lines instead of constructing six objects by hand.

What it owns:
  * TraceabilityConfig   -- all settings/secrets from .env
  * EventStore           -- local SQLite memory + offline buffer
  * RecordingEventCorrelator -- a drop-in EventCorrelator that also records
                                every event to the store
  * ClipRequestProcessor -- turns evidence-request JSON into actual clips
                            (runs on a background loop)
  * CloudSync + SyncRunner -- pushes clips to the cloud (background loop),
                              STARTED ONLY IF the cloud is configured

Design goals:
  * Graceful degrade: if the cloud isn't configured yet (e.g. Dhar's function
    URL not in .env), the runtime still starts and does everything locally --
    it just logs that cloud sync is disabled. Nothing crashes.
  * Non-invasive: main.py keeps all its camera/zone/frame logic. It only uses
    runtime.correlator in place of EventCorrelator, and calls start()/stop().
  * Safe loops: the clip-processor and sync loops never raise out; errors are
    logged and the loop continues.

Usage in main.py:
    runtime = TraceabilityRuntime.build()
    event_correlator = runtime.correlator      # use instead of EventCorrelator
    ...
    runtime.start()
    try:
        ...                                     # main loop
    finally:
        runtime.stop()
"""
import logging
import threading
import time
from typing import Optional

from local_agent.traceability.traceability_config import TraceabilityConfig
from local_agent.traceability.event_store import EventStore
from local_agent.traceability.recording_correlator import RecordingEventCorrelator
from local_agent.traceability.clip_request_processor import ClipRequestProcessor
from local_agent.traceability.cloud_sync import CloudSync
from local_agent.traceability.sync_runner import SyncRunner

logger = logging.getLogger(__name__)


class TraceabilityRuntime:
    def __init__(
        self,
        config: TraceabilityConfig,
        store: EventStore,
        correlator: RecordingEventCorrelator,
        clip_processor: ClipRequestProcessor,
        cloud_sync: Optional[CloudSync],
        sync_runner: Optional[SyncRunner],
        clip_poll_sec: float = 5.0,
    ):
        self.config = config
        self.store = store
        self.correlator = correlator
        self.clip_processor = clip_processor
        self.cloud_sync = cloud_sync
        self.sync_runner = sync_runner
        self.clip_poll_sec = clip_poll_sec

        self._stop = threading.Event()
        self._clip_thread: Optional[threading.Thread] = None

    # ---- construction -----------------------------------------------------

    @classmethod
    def build(cls, env_path: Optional[str] = None, enable_file_upload: bool = False) -> "TraceabilityRuntime":
        """Load config and assemble every component. Does not start any loops."""
        cfg = TraceabilityConfig.load(env_path)

        logger.info("Traceability runtime configuration:")
        for k, v in cfg.safe_summary().items():
            logger.info("    %s = %s", k, v)

        store = EventStore(db_path=cfg.traceability_db_path)
        correlator = RecordingEventCorrelator(
            store,
            match_window_sec=cfg.barcode_match_window_sec,
            zone_id=2,
        )
        clip_processor = ClipRequestProcessor(
            requests_dir=cfg.clip_requests_dir,
            video_dir=cfg.video_output_dir,
            output_dir=cfg.video_clip_dir,
            segment_seconds=cfg.video_segment_minutes * 60,
            event_store=store,
        )

        cloud_sync = None
        sync_runner = None
        if cfg.is_cloud_configured():
            cloud_sync = CloudSync.from_config(cfg, store, enable_file_upload=enable_file_upload)
            sync_runner = SyncRunner.from_config(cfg, cloud_sync)
            logger.info("Cloud sync ENABLED (function URL + credentials present)")
        else:
            logger.warning(
                "Cloud sync DISABLED -- cloud not fully configured "
                "(function URL still a placeholder or credentials missing). "
                "Running locally; clips are buffered and will upload once configured."
            )

        return cls(cfg, store, correlator, clip_processor, cloud_sync, sync_runner)

    # ---- background loops -------------------------------------------------

    def _clip_loop(self) -> None:
        """Poll the clip-requests folder and turn requests into clips."""
        logger.info("Clip processor loop started (every %.0fs)", self.clip_poll_sec)
        while not self._stop.is_set():
            try:
                results = self.clip_processor.process_all()
                made = [r for r in results if r.status in ("extracted", "stitched")]
                if made:
                    logger.info("Clip processor: produced %d clip(s)", len(made))
            except Exception as e:
                logger.error("Clip processor cycle failed: %s", e)
            self._stop.wait(timeout=self.clip_poll_sec)
        logger.info("Clip processor loop stopped")

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Start the clip-processor loop and (if configured) the cloud sync."""
        self._stop.clear()
        self._clip_thread = threading.Thread(
            target=self._clip_loop, daemon=True, name="clip-processor")
        self._clip_thread.start()

        if self.sync_runner is not None:
            self.sync_runner.start()
            logger.info("Cloud sync runner started")

    def stop(self, join_timeout: float = 5.0) -> None:
        """Stop all background loops cleanly."""
        self._stop.set()
        if self.sync_runner is not None:
            try:
                self.sync_runner.stop()
            except Exception as e:
                logger.error("Error stopping sync runner: %s", e)
        if self._clip_thread is not None:
            self._clip_thread.join(timeout=join_timeout)
        # EventStore opens a fresh connection per operation (each closes itself),
        # so there is no persistent handle to close here.
        logger.info("Traceability runtime stopped")

    # ---- convenience ------------------------------------------------------

    def stats(self) -> dict:
        """Quick snapshot for heartbeat logging."""
        try:
            return self.store.stats()
        except Exception as e:
            logger.error("stats() failed: %s", e)
            return {}