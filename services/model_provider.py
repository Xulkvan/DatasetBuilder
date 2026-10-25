"""[STAGE1:model_provider] Provider-pattern абстракции для детекторов/pose/трекеров."""
from abc import ABC, abstractmethod
from typing import Any, List


class BaseDetector(ABC):
    @abstractmethod
    def predict(self, image_path: str, conf: float = 0.25) -> List[dict]:
        """[{x, y, w, h, label, confidence}] в нормализованных координатах."""
        ...


class BasePose(ABC):
    @abstractmethod
    def predict_pose(self, image_path: str, conf: float = 0.25) -> List[dict]:
        """[{bbox:{x,y,w,h}, keypoints:[{name,x,y,visibility}]}]"""
        ...


class BaseTracker(ABC):
    @abstractmethod
    def track(self, frames: List[str], **kwargs) -> List[dict]:
        """По-кадровые детекции с track_id."""
        ...


class UltralyticsDetector(BaseDetector):
    def __init__(self, model_path: str):
        from ultralytics import YOLO
        self.model = YOLO(model_path)

    def predict(self, image_path: str, conf: float = 0.25) -> List[dict]:
        results = self.model(image_path, conf=conf, verbose=False)
        out: List[dict] = []
        for r in results:
            try:
                H, W = r.orig_shape[0], r.orig_shape[1]
            except Exception:
                continue
            if r.boxes is None:
                continue
            for box in r.boxes:
                try:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    cls_id = int(box.cls[0])
                    bconf = float(box.conf[0])
                except Exception:
                    continue
                out.append({
                    "x": max(0.0, x1 / W), "y": max(0.0, y1 / H),
                    "w": max(0.0, (x2 - x1) / W), "h": max(0.0, (y2 - y1) / H),
                    "label": str(self.model.names.get(cls_id, "object")),
                    "confidence": bconf,
                })
        return out


class UltralyticsPose(BasePose):
    def __init__(self, model_path: str, kp_names: List[str]):
        from ultralytics import YOLO
        self.model = YOLO(model_path)
        self.kp_names = kp_names

    def predict_pose(self, image_path: str, conf: float = 0.25) -> List[dict]:
        results = self.model(image_path, conf=conf, verbose=False)
        out: List[dict] = []
        n = len(self.kp_names)
        for r in results:
            if getattr(r, "keypoints", None) is None or r.keypoints.xy is None:
                continue
            try:
                xyxy = r.boxes.xyxy.cpu().numpy()
                kp_xy = r.keypoints.xy.cpu().numpy()
                kp_conf = (r.keypoints.conf.cpu().numpy()
                           if r.keypoints.conf is not None else None)
            except Exception:
                continue
            H, W = r.orig_shape[0], r.orig_shape[1]
            for k in range(len(xyxy)):
                x1, y1, x2, y2 = xyxy[k].tolist()
                pts = []
                for i in range(min(n, len(kp_xy[k]))):
                    px, py = kp_xy[k][i].tolist()
                    pc = float(kp_conf[k][i]) if kp_conf is not None else 1.0
                    pts.append({
                        "name": self.kp_names[i],
                        "x": max(0.0, min(1.0, px / W)),
                        "y": max(0.0, min(1.0, py / H)),
                        "visibility": 1.0 if pc >= 0.4 else 0.0,
                    })
                out.append({
                    "bbox": {"x": x1 / W, "y": y1 / H,
                             "w": (x2 - x1) / W, "h": (y2 - y1) / H},
                    "keypoints": pts,
                })
        return out


class UltralyticsTracker(BaseTracker):
    def __init__(self, model_path: str, tracker_cfg: str = "bytetrack.yaml"):
        from ultralytics import YOLO
        self.model = YOLO(model_path)
        self.tracker_cfg = tracker_cfg

    def track(self, frames: List[str], conf: float = 0.25, **kw) -> List[dict]:
        results = self.model.track(
            source=frames, stream=True, persist=True,
            tracker=self.tracker_cfg, conf=conf, verbose=False, **kw,
        )
        out: List[dict] = []
        try:
            for idx, r in enumerate(results):
                frame = {"frame_index": idx, "detections": []}
                if r.boxes is not None and r.boxes.id is not None:
                    try:
                        xyxy = r.boxes.xyxy.cpu().numpy()
                        tids = r.boxes.id.cpu().numpy()
                        H, W = r.orig_shape[0], r.orig_shape[1]
                    except Exception:
                        out.append(frame); continue
                    for k in range(len(xyxy)):
                        x1, y1, x2, y2 = xyxy[k].tolist()
                        frame["detections"].append({
                            "track_id": int(tids[k]),
                            "x": x1 / W, "y": y1 / H,
                            "w": (x2 - x1) / W, "h": (y2 - y1) / H,
                        })
                out.append(frame)
        finally:
            try:
                results.close()
            except Exception:
                pass
        return out
