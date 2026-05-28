"""
BarcodeReader — reads barcodes two ways:
  1. Camera path: detects barcode region in frame using YOLO, decodes with pyzbar
  2. Scanner path: listens for USB barcode scanner input (HID keyboard emulation)
Both results are passed to EventCorrelator for dual verification.
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
import numpy as np

logger = logging.getLogger(__name__)

# Try to import pyzbar — if not installed, camera barcode reading won't work
try:
    from pyzbar import pyzbar
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False
    logger.warning("pyzbar not installed — camera barcode decoding disabled. Run: pip install pyzbar")


@dataclass
class BarcodeResult:
    """A single barcode read result from either the camera or USB scanner."""
    value: str                    # The decoded barcode string e.g. "SKU-12345"
    source: str                   # "camera" or "scanner"
    timestamp: float              # Unix timestamp of the read
    confidence: float = 1.0       # Confidence score (camera reads may be lower)
    bbox: Optional[list] = None   # Bounding box if from camera [x1, y1, x2, y2]

    def __str__(self):
        return f"BarcodeResult(value={self.value}, source={self.source}, ts={self.timestamp:.2f})"


class CameraBarcodeReader:
    """
    Reads barcodes from camera frames.
    Uses pyzbar to decode barcodes found in the frame.
    Optionally uses YOLO detection to crop the barcode region first
    for better accuracy.
    """

    def __init__(self):
        if not PYZBAR_AVAILABLE:
            logger.error("pyzbar not available — CameraBarcodeReader will not decode")

    def read_frame(self, frame: np.ndarray, timestamp: Optional[float] = None) -> list[BarcodeResult]:
        """
        Attempt to decode all barcodes in a camera frame.
        Returns a list of BarcodeResult objects (usually 0 or 1 results).
        """
        if not PYZBAR_AVAILABLE:
            return []

        if timestamp is None:
            timestamp = time.time()

        results = []
        try:
            decoded = pyzbar.decode(frame)
            for barcode in decoded:
                value = barcode.data.decode("utf-8").strip()
                if not value:
                    continue

                # Get bounding box from pyzbar
                rect = barcode.rect
                bbox = [rect.left, rect.top, rect.left + rect.width, rect.top + rect.height]

                result = BarcodeResult(
                    value=value,
                    source="camera",
                    timestamp=timestamp,
                    confidence=0.95,  # pyzbar is highly reliable when it decodes
                    bbox=bbox,
                )
                results.append(result)
                logger.debug(f"Camera decoded barcode: {value}")

        except Exception as e:
            logger.error(f"Camera barcode decode error: {e}")

        return results

    def read_cropped(self, frame: np.ndarray, bbox: list, timestamp: Optional[float] = None) -> list[BarcodeResult]:
        """
        Decode barcodes from a cropped region of a frame.
        Use this when YOLO has already detected a barcode region
        for better decode accuracy.
        """
        if not PYZBAR_AVAILABLE:
            return []

        try:
            x1, y1, x2, y2 = [int(c) for c in bbox]
            # Add small padding around the crop for better decode
            pad = 10
            h, w = frame.shape[:2]
            x1 = max(0, x1 - pad)
            y1 = max(0, y1 - pad)
            x2 = min(w, x2 + pad)
            y2 = min(h, y2 + pad)
            cropped = frame[y1:y2, x1:x2]
            return self.read_frame(cropped, timestamp)
        except Exception as e:
            logger.error(f"Cropped barcode read error: {e}")
            return []


class ScannerBarcodeReader:
    """
    Listens for USB barcode scanner input.
    USB scanners in HID mode act like a keyboard — they type the barcode
    value followed by Enter. We capture this input in a background thread
    and call the callback when a barcode is scanned.
    """

    def __init__(self, on_scan: Callable[[BarcodeResult], None]):
        """
        on_scan: callback function called every time the scanner reads a barcode.
        """
        self.on_scan = on_scan
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._buffer = ""

    def start(self):
        """Start listening for scanner input in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True, name="scanner-reader")
        self._thread.start()
        logger.info("USB scanner listener started")

    def stop(self):
        """Stop the scanner listener."""
        self._running = False
        logger.info("USB scanner listener stopped")

    def _listen(self):
        """
        Background thread that reads scanner input.
        USB scanners send characters like a keyboard then press Enter.
        We buffer characters and fire the callback on Enter.
        """
        logger.info("Scanner listener running — waiting for barcode scans...")
        while self._running:
            try:
                # Read one character at a time from stdin
                # In production this reads from the USB HID device
                import sys
                char = sys.stdin.read(1)
                if char == "\n" or char == "\r":
                    # Enter pressed — barcode complete
                    if self._buffer.strip():
                        result = BarcodeResult(
                            value=self._buffer.strip(),
                            source="scanner",
                            timestamp=time.time(),
                            confidence=1.0,  # Scanner reads are always reliable
                        )
                        logger.info(f"Scanner read: {result.value}")
                        self.on_scan(result)
                    self._buffer = ""
                else:
                    self._buffer += char
            except Exception as e:
                logger.error(f"Scanner read error: {e}")
                time.sleep(0.1)

    def simulate_scan(self, barcode_value: str) -> BarcodeResult:
        """
        Simulate a scanner scan — used for testing without physical hardware.
        Calls the on_scan callback directly.
        """
        result = BarcodeResult(
            value=barcode_value,
            source="scanner",
            timestamp=time.time(),
            confidence=1.0,
        )
        self.on_scan(result)
        return result


class BarcodeReader:
    """
    Main barcode reader that combines camera and scanner paths.
    This is the class used by the Traceability Agent.
    """

    def __init__(self, on_scan: Optional[Callable[[BarcodeResult], None]] = None):
        self.camera_reader = CameraBarcodeReader()
        self.scanner_reader = ScannerBarcodeReader(
            on_scan=on_scan or self._default_scan_handler
        )
        self._scan_log: list[BarcodeResult] = []

    def _default_scan_handler(self, result: BarcodeResult):
        """Default handler — just logs the scan."""
        logger.info(f"Barcode scanned: {result}")
        self._scan_log.append(result)

    def read_from_frame(self, frame: np.ndarray, timestamp: Optional[float] = None) -> list[BarcodeResult]:
        """Read barcodes from a camera frame."""
        return self.camera_reader.read_frame(frame, timestamp)

    def read_from_frame_cropped(self, frame: np.ndarray, bbox: list, timestamp: Optional[float] = None) -> list[BarcodeResult]:
        """Read barcode from a cropped region — use when YOLO found a barcode bbox."""
        return self.camera_reader.read_cropped(frame, bbox, timestamp)

    def start_scanner_listener(self):
        """Start the USB scanner background listener."""
        self.scanner_reader.start()

    def stop_scanner_listener(self):
        """Stop the USB scanner background listener."""
        self.scanner_reader.stop()

    def simulate_scanner_scan(self, barcode_value: str) -> BarcodeResult:
        """Simulate a scanner scan for testing."""
        return self.scanner_reader.simulate_scan(barcode_value)

    def get_scan_log(self) -> list[BarcodeResult]:
        """Return all scans captured by the default handler."""
        return self._scan_log.copy()