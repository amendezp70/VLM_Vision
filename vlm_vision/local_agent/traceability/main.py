"""
Traceability Agent — Process 2
Entry point for the traceability module. Wires together all components:
- ZoneManager (5 camera zones)
- BarcodeReader (camera + USB scanner)
- EventCorrelator (dual barcode verification)
- PalletTracker (pallet assembly tracking)
- EvidenceGenerator (clip requests on bad events)
- TraceabilityRuntime (local memory + cloud sync layer)

Runs as a separate process alongside the VLM Bay Agent (Process 1)
and Video Recorder (Process 3). Does NOT modify any existing code.
"""
import logging
import os
import sys
import threading
import time
from queue import Queue, Empty
from typing import Optional

import cv2
import numpy as np

# Make stdout UTF-8 so special characters (arrows, em-dashes) don't crash
# logging on Windows (default console is cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from local_agent.traceability.zone_manager import ZoneManager, ZoneFrame
from local_agent.traceability.barcode_reader import BarcodeReader, BarcodeResult
from local_agent.traceability.event_correlator import EventCorrelator
from local_agent.traceability.pallet_tracker import PalletTracker
from local_agent.traceability.evidence_generator import EvidenceGenerator
from local_agent.traceability.traceability_runtime import TraceabilityRuntime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/traceability.log", mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

FRAME_QUEUE_SIZE = 5
CAMERA_RECONNECT_DELAY = 5.0  # seconds before retrying a failed camera


def run_zone_camera(
    zone_id: int,
    camera_id: int,
    frame_queue: Queue,
    running: threading.Event,
    fps: int = 10,
):
    """
    Background thread that captures frames from one zone camera
    and puts them into the shared frame queue.
    Reconnects automatically if camera disconnects.
    """
    logger.info(f"Zone {zone_id} camera thread started - camera_id={camera_id}")
    frame_interval = 1.0 / fps

    while running.is_set():
        cap = cv2.VideoCapture(camera_id)
        if not cap.isOpened():
            logger.warning(f"Zone {zone_id} camera {camera_id} not available - retrying in {CAMERA_RECONNECT_DELAY}s")
            time.sleep(CAMERA_RECONNECT_DELAY)
            continue

        logger.info(f"Zone {zone_id} camera {camera_id} connected")

        while running.is_set():
            ret, frame = cap.read()
            if not ret:
                logger.warning(f"Zone {zone_id} camera {camera_id} lost - reconnecting")
                break

            # Don't block if queue is full - drop frame and continue
            if not frame_queue.full():
                frame_queue.put((zone_id, frame, time.time()))

            time.sleep(frame_interval)

        cap.release()

    logger.info(f"Zone {zone_id} camera thread stopped")


def run_frame_processor(
    zone_manager: ZoneManager,
    barcode_reader: BarcodeReader,
    event_correlator: EventCorrelator,
    pallet_tracker: PalletTracker,
    frame_queue: Queue,
    running: threading.Event,
):
    """
    Main processing loop - reads frames from the queue and
    routes them to the correct handler based on zone type.
    """
    logger.info("Frame processor started")
    from local_agent.traceability.zone_manager import ZoneType

    while running.is_set():
        try:
            zone_id, frame, timestamp = frame_queue.get(timeout=1.0)
        except Empty:
            continue

        # Process the frame through the zone manager
        zone_frame = zone_manager.process_frame(zone_id, frame, timestamp)
        if zone_frame is None:
            continue

        # Route to correct handler based on zone type
        try:
            if zone_frame.zone_type == ZoneType.BARCODE_SCAN:
                _handle_barcode_zone(zone_frame, barcode_reader, event_correlator)

            elif zone_frame.zone_type == ZoneType.PACKING:
                _handle_packing_zone(zone_frame)

            elif zone_frame.zone_type == ZoneType.SEALING:
                _handle_sealing_zone(zone_frame)

            elif zone_frame.zone_type == ZoneType.PALLET_ASSEMBLY:
                _handle_pallet_zone(zone_frame, pallet_tracker)

            elif zone_frame.zone_type == ZoneType.TRUCK_LOADING:
                _handle_truck_zone(zone_frame, pallet_tracker)

        except Exception as e:
            logger.error(f"Frame processing error on zone {zone_id}: {e}")

    logger.info("Frame processor stopped")


def _handle_barcode_zone(
    zone_frame: ZoneFrame,
    barcode_reader: BarcodeReader,
    event_correlator: EventCorrelator,
):
    """Zone 2 - read barcode from camera frame and send to correlator."""
    camera_reads = barcode_reader.read_from_frame(zone_frame.frame, zone_frame.timestamp)
    for read in camera_reads:
        logger.info(f"Zone 2 camera barcode: {read.value}")
        event_correlator.add_camera_read(read)


def _handle_packing_zone(zone_frame: ZoneFrame):
    """Zone 1 - SKU detection handled by existing metwall.onnx detector."""
    if zone_frame.detections:
        top = max(zone_frame.detections, key=lambda d: d.confidence)
        logger.debug(f"Zone 1 detected: {top.label} ({top.confidence:.2f})")


def _handle_sealing_zone(zone_frame: ZoneFrame):
    """Zone 3 - check if box is sealed."""
    for det in zone_frame.detections:
        if det.label in ("box_sealed", "box_taped"):
            logger.info(f"Zone 3 box sealed confirmed - confidence {det.confidence:.2f}")
        elif det.label == "box_open":
            logger.warning(f"Zone 3 box NOT sealed - confidence {det.confidence:.2f}")


def _handle_pallet_zone(zone_frame: ZoneFrame, pallet_tracker: PalletTracker):
    """Zone 4 - track box placement on pallet."""
    active = pallet_tracker.get_active_pallet()
    if active is None:
        active = pallet_tracker.start_pallet()

    for det in zone_frame.detections:
        if det.label == "box_on_pallet":
            logger.info(f"Zone 4 box placed on pallet {active.pallet_id}")


def _handle_truck_zone(zone_frame: ZoneFrame, pallet_tracker: PalletTracker):
    """Zone 5 - confirm pallet loaded onto truck."""
    for det in zone_frame.detections:
        if det.label in ("truck_bay", "pallet_full"):
            active = pallet_tracker.get_active_pallet()
            if active:
                pallet_tracker.complete_pallet(active.pallet_id)
                pallet_tracker.mark_pallet_loaded(active.pallet_id)
                logger.info(f"Zone 5 pallet {active.pallet_id} loaded onto truck")


def main():
    """
    Main entry point for the Traceability Agent.
    Initializes all components and starts all threads.
    """
    logger.info("=" * 60)
    logger.info("VLM Vision - Traceability Agent starting")
    logger.info("=" * 60)

    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/clip_requests", exist_ok=True)

    # Build the memory + cloud layer (store, recording correlator, clip
    # processor, cloud sync). Degrades gracefully if cloud isn't configured.
    runtime = TraceabilityRuntime.build()

    # Initialize all components
    zone_manager = ZoneManager.from_env()
    barcode_reader = BarcodeReader()
    event_correlator = runtime.correlator   # records every event to the store
    pallet_tracker = PalletTracker()
    evidence_generator = EvidenceGenerator.from_env()

    # Wire up alert pipeline:
    # mismatch -> evidence_generator -> writes JSON -> Video Recorder cuts clip
    event_correlator.on_alert(evidence_generator.on_correlation_event)
    logger.info("Alert pipeline wired: EventCorrelator -> EvidenceGenerator")

    # Shared frame queue between camera threads and processor
    frame_queue: Queue = Queue(maxsize=FRAME_QUEUE_SIZE)

    # Running flag - set to False to stop all threads cleanly
    running = threading.Event()
    running.set()

    threads = []

    # Start one camera thread per enabled zone
    for zone in zone_manager.get_enabled_zones():
        t = threading.Thread(
            target=run_zone_camera,
            args=(zone.zone_id, zone.camera_id, frame_queue, running),
            kwargs={"fps": int(os.environ.get("DETECTION_FPS", "10"))},
            daemon=True,
            name=f"camera-zone-{zone.zone_id}",
        )
        t.start()
        threads.append(t)
        logger.info(f"Camera thread started for zone {zone.zone_id}")

    # Start frame processor thread
    processor_thread = threading.Thread(
        target=run_frame_processor,
        args=(zone_manager, barcode_reader, event_correlator, pallet_tracker, frame_queue, running),
        daemon=True,
        name="frame-processor",
    )
    processor_thread.start()
    threads.append(processor_thread)

    # Start USB scanner listener
    barcode_reader.start_scanner_listener()
    runtime.start()   # starts clip-processor loop + cloud sync (if configured)

    logger.info(f"Traceability Agent running - {len(zone_manager.get_enabled_zones())} zones active")
    logger.info("Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(10)
            # Log a heartbeat every 10 seconds
            summary = pallet_tracker.summary()
            mismatches = len(event_correlator.get_mismatches())
            store_stats = runtime.stats()
            logger.info(
                f"Heartbeat - pallets: {summary['active_pallets']} active / "
                f"{summary['completed_pallets']} completed - "
                f"mismatches: {mismatches} - "
                f"stored events: {store_stats.get('events', 0)}, clips: {store_stats.get('clips', 0)}"
            )

    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
    finally:
        running.clear()
        barcode_reader.stop_scanner_listener()
        runtime.stop()
        logger.info("Traceability Agent stopped cleanly")


if __name__ == "__main__":
    main()