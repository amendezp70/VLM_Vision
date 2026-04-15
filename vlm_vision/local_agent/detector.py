"""
Wraps YOLOv8 ONNX inference.

Two backends are supported (chosen automatically):
  1. ultralytics + torch  — used when both are installed (dev / Docker)
  2. onnxruntime only     — used in the standalone macOS .app bundle

Class names in the model must follow the format  SKU__color
e.g. "STL-P-100-BK__black", "ALUM-P-60-SL__silver"
"""
import json
import os
from typing import Dict, List, Optional

import cv2
import numpy as np

from local_agent.models import Detection

# Confidence threshold for detections
_CONF_THRESHOLD = 0.25
_IOU_THRESHOLD = 0.45
_INPUT_SIZE = 640


def _load_class_names(model_path: str) -> Dict[int, str]:
    """Load class names from a metadata JSON sidecar (same dir as .onnx).

    Expected file: <model_name>_classes.json  — a dict {index: "name"}
    Falls back to the ONNX model's metadata if available.
    """
    base = os.path.splitext(model_path)[0]
    json_path = base + "_classes.json"
    if os.path.exists(json_path):
        with open(json_path) as f:
            raw = json.load(f)
        return {int(k): v for k, v in raw.items()}

    # Try reading from ONNX metadata (ultralytics embeds names there)
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(model_path)
        meta = sess.get_modelmeta().custom_metadata_map
        if "names" in meta:
            # ultralytics stores as Python dict literal: {0: 'cls0', 1: 'cls1'}
            names_raw = meta["names"]
            # Safe parse: replace single quotes with double for JSON
            names_raw = names_raw.replace("'", '"')
            parsed = json.loads(names_raw)
            return {int(k): v for k, v in parsed.items()}
    except Exception:
        pass

    return {}


def _xywh2xyxy(x: np.ndarray) -> np.ndarray:
    """Convert [cx, cy, w, h] to [x1, y1, x2, y2]."""
    y = np.copy(x)
    y[:, 0] = x[:, 0] - x[:, 2] / 2
    y[:, 1] = x[:, 1] - x[:, 3] / 2
    y[:, 2] = x[:, 0] + x[:, 2] / 2
    y[:, 3] = x[:, 1] + x[:, 3] / 2
    return y


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> List[int]:
    """Non-maximum suppression."""
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: List[int] = []

    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]

    return keep


class Detector:
    """YOLOv8 detector with automatic backend selection."""

    def __init__(self, model_path: str):
        self._backend: str = ""
        self._model = None  # ultralytics YOLO or None
        self._session = None  # onnxruntime session or None
        self._names: Dict[int, str] = {}

        self._init_backend(model_path)

    def _init_backend(self, model_path: str) -> None:
        # Try ultralytics first (available in full dev/Docker installs)
        try:
            from ultralytics import YOLO
            self._model = YOLO(model_path)
            self._backend = "ultralytics"
            return
        except ImportError:
            pass

        # Fallback: pure onnxruntime (standalone .app bundle)
        import onnxruntime as ort
        self._session = ort.InferenceSession(model_path)
        self._names = _load_class_names(model_path)
        self._backend = "onnxruntime"

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if self._backend == "ultralytics":
            return self._detect_ultralytics(frame)
        return self._detect_onnx(frame)

    # ── ultralytics backend ───────────────────────────────────────────
    def _detect_ultralytics(self, frame: np.ndarray) -> List[Detection]:
        results = self._model(frame, verbose=False)
        detections: List[Detection] = []

        for result in results:
            boxes = result.boxes
            names = result.names
            for i, xyxy in enumerate(boxes.xyxy):
                if i >= len(boxes.conf):
                    break
                cls_idx = int(boxes.cls[i])
                raw_name = names.get(cls_idx, "__")
                parts = raw_name.split("__", 1)
                sku = parts[0]
                color = parts[1] if len(parts) > 1 else "unknown"

                x1, y1, x2, y2 = (int(v) for v in xyxy)
                detections.append(Detection(
                    sku=sku,
                    color=color,
                    confidence=float(boxes.conf[i]),
                    bbox=(x1, y1, x2, y2),
                ))

        return detections

    # ── onnxruntime backend ───────────────────────────────────────────
    def _detect_onnx(self, frame: np.ndarray) -> List[Detection]:
        img_h, img_w = frame.shape[:2]

        # Preprocess: resize, normalize, NCHW, batch dim
        img = cv2.resize(frame, (_INPUT_SIZE, _INPUT_SIZE))
        img = img.astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))  # HWC -> CHW
        img = np.expand_dims(img, axis=0)    # add batch

        input_name = self._session.get_inputs()[0].name
        outputs = self._session.run(None, {input_name: img})

        # YOLOv8 output shape: (1, 4+num_classes, num_boxes)
        output = outputs[0]
        predictions = np.squeeze(output, axis=0).T  # (num_boxes, 4+num_classes)

        # Split boxes and class scores
        boxes_xywh = predictions[:, :4]
        class_scores = predictions[:, 4:]

        # Best class per box
        class_ids = np.argmax(class_scores, axis=1)
        confidences = class_scores[np.arange(len(class_ids)), class_ids]

        # Filter by confidence
        mask = confidences >= _CONF_THRESHOLD
        boxes_xywh = boxes_xywh[mask]
        confidences = confidences[mask]
        class_ids = class_ids[mask]

        if len(boxes_xywh) == 0:
            return []

        # Convert to xyxy and scale to original image
        boxes_xyxy = _xywh2xyxy(boxes_xywh)
        boxes_xyxy[:, [0, 2]] *= img_w / _INPUT_SIZE
        boxes_xyxy[:, [1, 3]] *= img_h / _INPUT_SIZE

        # NMS
        keep = _nms(boxes_xyxy, confidences, _IOU_THRESHOLD)

        detections: List[Detection] = []
        for i in keep:
            cls_idx = int(class_ids[i])
            raw_name = self._names.get(cls_idx, "__")
            parts = raw_name.split("__", 1)
            sku = parts[0]
            color = parts[1] if len(parts) > 1 else "unknown"

            x1, y1, x2, y2 = (int(v) for v in boxes_xyxy[i])
            detections.append(Detection(
                sku=sku,
                color=color,
                confidence=float(confidences[i]),
                bbox=(x1, y1, x2, y2),
            ))

        return detections
