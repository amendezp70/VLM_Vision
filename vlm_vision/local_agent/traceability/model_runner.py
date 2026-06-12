# vlm_vision/local_agent/traceability/model_runner.py
"""
ONNXModelRunner -- loads a YOLOv8n model exported to ONNX and runs detection
on a single camera frame, returning results in the exact shape the
ZoneManager expects from a "detector":

    detector(frame) -> List[dict], each dict:
        {"label": str, "confidence": float, "bbox": [x1, y1, x2, y2]}

ZoneManager.process_frame(..., detector=runner) then turns those dicts into
Detection objects. So a runner instance is callable and drops straight in.

Design notes / why it's built this way:
  * CPU only via ONNX Runtime -- matches the factory-PC plan (no GPU).
  * Graceful absence: NONE of the models (barcode/box_state/pallet) exist yet.
    If the .onnx file is missing, the runner logs once and every call returns
    [] -- so the whole pipeline runs today and each zone "lights up" the moment
    its model file is dropped in. Nothing crashes waiting on models.
  * YOLOv8 output decoding: YOLOv8 ONNX outputs one tensor shaped
    (1, 4 + num_classes, num_boxes). Rows 0..3 are box center x,y,w,h (in the
    640-input space); the remaining rows are per-class scores. We pick the best
    class per box, threshold by confidence, scale boxes back to the original
    frame size, and run Non-Max Suppression to drop overlapping duplicates.

Usage:
    runner = ONNXModelRunner("models/barcode.onnx",
                             class_names=["barcode", "qr", "label"])
    zone_frame = zone_manager.process_frame(2, frame, ts, detector=runner)
"""
import logging
import os
from typing import Callable, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_INPUT_SIZE = 640  # YOLOv8 default square input


class ONNXModelRunner:
    def __init__(
        self,
        model_path: str,
        class_names: List[str],
        conf_threshold: float = 0.35,
        iou_threshold: float = 0.45,
    ):
        self.model_path = model_path
        self.class_names = class_names
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self._session = None
        self._input_name: Optional[str] = None
        self._warned_missing = False
        self._load()

    # ---- loading ----------------------------------------------------------

    def _load(self) -> None:
        """Load the ONNX session. Missing file is not fatal -- the runner just
        returns no detections until the model arrives."""
        if not os.path.isfile(self.model_path):
            logger.warning(
                "Model file not found: %s -- detector will return no detections "
                "until it is provided.", self.model_path)
            return
        try:
            import onnxruntime as ort
            self._session = ort.InferenceSession(
                self.model_path, providers=["CPUExecutionProvider"])
            self._input_name = self._session.get_inputs()[0].name
            logger.info("Loaded ONNX model %s (classes: %s)",
                        self.model_path, ", ".join(self.class_names))
        except Exception as e:
            logger.error("Failed to load ONNX model %s: %s", self.model_path, e)
            self._session = None

    @property
    def is_loaded(self) -> bool:
        return self._session is not None

    # ---- inference --------------------------------------------------------

    def __call__(self, frame: np.ndarray) -> List[dict]:
        """Run detection on one BGR frame. Returns a list of detection dicts.
        Never raises -- detection problems are logged and yield []."""
        if self._session is None:
            if not self._warned_missing:
                logger.warning("Detector for %s called but model not loaded; "
                               "returning no detections.", self.model_path)
                self._warned_missing = True
            return []
        try:
            tensor, scale, pad = self._preprocess(frame)
            outputs = self._session.run(None, {self._input_name: tensor})
            return self._postprocess(outputs[0], scale, pad, frame.shape[:2])
        except Exception as e:
            logger.error("Inference failed on %s: %s", self.model_path, e)
            return []

    # ---- pre / post processing -------------------------------------------

    def _preprocess(self, frame: np.ndarray):
        """Letterbox-resize a BGR frame to 640x640, normalize, and shape it
        into the (1,3,640,640) tensor YOLOv8 expects. Returns the tensor plus
        the scale and padding so boxes can be mapped back to the original."""
        h, w = frame.shape[:2]
        scale = min(_INPUT_SIZE / w, _INPUT_SIZE / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))

        import cv2
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((_INPUT_SIZE, _INPUT_SIZE, 3), 114, dtype=np.uint8)
        pad_x = (_INPUT_SIZE - nw) // 2
        pad_y = (_INPUT_SIZE - nh) // 2
        canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized

        # BGR->RGB, HWC->CHW, 0..1, add batch dim
        img = canvas[:, :, ::-1].astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))[np.newaxis, :]
        return np.ascontiguousarray(img), scale, (pad_x, pad_y)

    def _postprocess(self, output: np.ndarray, scale, pad, orig_hw) -> List[dict]:
        """Decode YOLOv8 output (1, 4+C, N) into detection dicts in original
        frame pixels, after confidence threshold and NMS."""
        pad_x, pad_y = pad
        orig_h, orig_w = orig_hw

        preds = np.squeeze(output, 0)          # (4+C, N)
        if preds.shape[0] < preds.shape[1]:    # ensure (N, 4+C)
            preds = preds.T
        if preds.shape[1] < 4 + len(self.class_names):
            return []

        boxes_xywh = preds[:, :4]
        scores_all = preds[:, 4:4 + len(self.class_names)]
        class_ids = np.argmax(scores_all, axis=1)
        confidences = scores_all[np.arange(scores_all.shape[0]), class_ids]

        keep = confidences >= self.conf_threshold
        if not np.any(keep):
            return []
        boxes_xywh = boxes_xywh[keep]
        confidences = confidences[keep]
        class_ids = class_ids[keep]

        # xywh (center) in 640 space -> xyxy in original frame space
        cx, cy, bw, bh = boxes_xywh[:, 0], boxes_xywh[:, 1], boxes_xywh[:, 2], boxes_xywh[:, 3]
        x1 = (cx - bw / 2 - pad_x) / scale
        y1 = (cy - bh / 2 - pad_y) / scale
        x2 = (cx + bw / 2 - pad_x) / scale
        y2 = (cy + bh / 2 - pad_y) / scale
        x1 = np.clip(x1, 0, orig_w); x2 = np.clip(x2, 0, orig_w)
        y1 = np.clip(y1, 0, orig_h); y2 = np.clip(y2, 0, orig_h)
        boxes_xyxy = np.stack([x1, y1, x2, y2], axis=1)

        keep_idx = self._nms(boxes_xyxy, confidences, self.iou_threshold)

        results = []
        for i in keep_idx:
            cid = int(class_ids[i])
            label = self.class_names[cid] if 0 <= cid < len(self.class_names) else str(cid)
            results.append({
                "label": label,
                "confidence": float(confidences[i]),
                "bbox": [float(boxes_xyxy[i][0]), float(boxes_xyxy[i][1]),
                         float(boxes_xyxy[i][2]), float(boxes_xyxy[i][3])],
            })
        return results

    @staticmethod
    def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> List[int]:
        """Plain NumPy non-max suppression. Returns indices to keep."""
        if len(boxes) == 0:
            return []
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(int(i))
            if order.size == 1:
                break
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
            iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
            order = order[1:][iou < iou_thr]
        return keep


# Convenience factory: the four project models, with their class names and the
# default models/ location. Returns a runner even if the file is absent yet.
_MODEL_CLASSES = {
    "metwall":   None,  # 150 SKUs -- class list comes from Poncho's training
    "barcode":   ["barcode", "qr_code", "label"],
    "box_state": ["box_open", "box_sealed", "box_taped", "box_labeled"],
    "pallet":    ["pallet_empty", "pallet_partial", "pallet_full",
                  "box_on_pallet", "forklift", "truck_bay"],
}


def build_runner(model_name: str, models_dir: str = "models",
                 class_names: Optional[List[str]] = None,
                 conf_threshold: float = 0.35) -> ONNXModelRunner:
    """Build a runner for one of the project models by short name
    (barcode, box_state, pallet, metwall). class_names defaults to the known
    list for that model; pass your own to override."""
    if class_names is None:
        class_names = _MODEL_CLASSES.get(model_name) or ["object"]
    path = os.path.join(models_dir, f"{model_name}.onnx")
    return ONNXModelRunner(path, class_names, conf_threshold=conf_threshold)