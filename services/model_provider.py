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


# [PATCH:STAGE4_MODEL_PROVIDER_CLEANED]
# UltralyticsDetector / UltralyticsPose / UltralyticsTracker удалены
# (не использовались в продакшене). ABC-интерфейсы оставлены
# как scaffold для будущего Provider Pattern.
# [/PATCH:STAGE4_MODEL_PROVIDER_CLEANED]
