# vlm_vision/local_agent/traceability/recording_correlator.py
"""
RecordingEventCorrelator -- an EventCorrelator that also writes every event
to an EventStore.

It SUBCLASSES the tested EventCorrelator and only extends one method
(_save_event), which is the single point every event passes through (match,
mismatch, and partial). Nothing in the original correlator is changed, so
behavior is identical with the store removed -- this is purely additive.

Use it anywhere you'd use EventCorrelator:

    store = EventStore("data/traceability.db")
    correlator = RecordingEventCorrelator.from_env(store)
"""
import logging

from local_agent.traceability.event_correlator import EventCorrelator
from local_agent.traceability.event_store import EventStore

logger = logging.getLogger(__name__)


class RecordingEventCorrelator(EventCorrelator):
    def __init__(self, store: EventStore, match_window_sec: float = 5.0, zone_id: int = 2):
        super().__init__(match_window_sec=match_window_sec, zone_id=zone_id)
        self._store = store

    def _save_event(self, event):
        # Keep the original behavior first (append to internal log + log line),
        super()._save_event(event)
        # then persist to the store. A store failure must never break the
        # detection pipeline, so it is caught and logged.
        try:
            self._store.record_event(event)
        except Exception as e:
            logger.error("EventStore.record_event failed: %s", e)

    @classmethod
    def from_env(cls, store: EventStore) -> "RecordingEventCorrelator":
        import os
        return cls(
            store,
            match_window_sec=float(os.environ.get("BARCODE_MATCH_WINDOW_SEC", "5.0")),
            zone_id=2,
        )