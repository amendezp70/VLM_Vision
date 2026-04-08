"""
Wraps YOLOv8 ONNX inference.

Class names in the model must follow the format  SKU__color
e.g. "STL-P-100-BK__black", "ALUM-P-60-SL__silver"
"""
import numpy as np
from typing import List
from ultralytics import YOLO
from local_agent.models import Detection


class Detector:
    def __init__(self, model_path: str):
        self._model = YOLO(model_path)

    def detect(self, frame: np.ndarray) -> List[Detection]:
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
