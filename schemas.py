from pydantic import BaseModel, Field, field_validator
from typing import Optional
from config import _norm_behavior, _norm_animal_id

DEFAULT_OBJECT_CLASS = "pig"
MAX_OBJECT_CLASS_LEN = 128

# [STAGE2:schemas-examples]
_EXAMPLE_ANNOTATION = {
    "x": 0.12, "y": 0.20, "w": 0.25, "h": 0.31,
    "label": "pig", "confidence": 0.92, "frozen": False,
    "behavior": "eat", "animal_id": 7,
    "keypoints": [
        {"name": "nose", "x": 0.15, "y": 0.22, "visibility": 1.0},
        {"name": "withers", "x": 0.30, "y": 0.30, "visibility": 1.0},
    ],
}


class AnnotationIn(BaseModel):
    model_config = {"json_schema_extra": {"examples": [_EXAMPLE_ANNOTATION]}}
    x: float = Field(..., examples=[0.12])
    y: float = Field(..., examples=[0.20])
    w: float = Field(..., examples=[0.25])
    h: float = Field(..., examples=[0.31])
    label: str = Field(DEFAULT_OBJECT_CLASS, examples=["pig"])
    confidence: Optional[float] = Field(None, examples=[0.92])
    frozen: bool = False
    behavior: Optional[str] = Field(None, examples=["eat"])
    behavior_source: Optional[str] = None
    animal_id: Optional[int] = Field(None, examples=[7])
    keypoints: list[dict] = Field(default_factory=list)

    @field_validator('x', 'y', 'w', 'h')
    @classmethod
    def _clamp(cls, v):
        return max(0.0, min(1.0, float(v)))

    @field_validator('confidence')
    @classmethod
    def _clamp_conf(cls, v):
        if v is None: return None
        return max(0.0, min(1.0, float(v)))

    @field_validator('label')
    @classmethod
    def _label_len(cls, v):
        v = (v or DEFAULT_OBJECT_CLASS)[:64]
        return v or DEFAULT_OBJECT_CLASS

    @field_validator('behavior')
    @classmethod
    def _behavior_valid(cls, v):
        return _norm_behavior(v)

    @field_validator('animal_id')
    @classmethod
    def _animal_id_valid(cls, v):
        return _norm_animal_id(v)

    @field_validator('behavior_source')  # [STAGE1-A:behavior-source]
    @classmethod
    def _behavior_source_valid(cls, v):
        if v is None: return None
        s = str(v).strip().lower()
        return s if s in ('heuristic', 'manual', 'classifier') else None

class KeypointIn(BaseModel):
    name: str
    x: float
    y: float
    visibility: float = 1.0

class KeypointsBulkIn(BaseModel):
    points: list[KeypointIn] = Field(default_factory=list)

class BatchAutolabelIn(BaseModel):
    image_ids: list[int] = Field(default_factory=list)
    project_id: Optional[int] = None
    tta: bool = False
    mode: str = "add"

class AutolabelIn(BaseModel):
    tta: bool = False
    mode: str = "add"

class DownloadModelIn(BaseModel):
    size: str = "n"
    pretrain: str = "oiv7"
    custom_name: str = ""
    family: str = "v8"
    task: str = "detect"

class BatchTagsIn(BaseModel):
    image_ids: list[int] = Field(default_factory=list)
    add: list[int] = Field(default_factory=list)
    remove: list[int] = Field(default_factory=list)

class ProjectSettingsIn(BaseModel):
    name: Optional[str] = None
    object_class: Optional[str] = None
    object_class_source: Optional[str] = None
    trash_ttl_days_override: Optional[int] = None
    data_retention_days: Optional[int] = None  # [PATCH:STAGE1_DATA_RETENTION_SCHEMA]
    thumbnail_size: Optional[int] = None
    default_zoom: Optional[float] = None
    clear_ttl_override: bool = False
    clear_thumbnail_size: bool = False
    clear_default_zoom: bool = False
    # [FIX:v1341-backend] Auto-blur
    auto_blur_enabled: Optional[bool] = None
    auto_blur_classes: Optional[list[str]] = None

class SamPoint(BaseModel):
    x: float
    y: float
    positive: bool = True

class SamPredictIn(BaseModel):
    points: list[SamPoint] = Field(default_factory=list)

class MigrateIn(BaseModel):
    target_path: Optional[str] = None
    overwrite: bool = False

class ImportRoboflowIn(BaseModel):
    api_key: str
    workspace: str
    project: str
    version: int

class ImportSuperviselyIn(BaseModel):
    api_token: str
    project_id: int
    dataset_id: Optional[int] = None

class ImportUrlIn(BaseModel):
    url: str
    filename: Optional[str] = None

class ImportLocalFolderIn(BaseModel):
    path: str
    recursive: bool = True

class ImportLabelboxIn(BaseModel):
    api_key: str
    project_id: str

class ImportScaleIn(BaseModel):
    api_key: str
    dataset_id: str

class ImportDarwinIn(BaseModel):
    api_key: str
    team_slug: str
    dataset_slug: str
    version_name: Optional[str] = None

class BulkRenameIn(BaseModel):
    image_ids: list[int]
    pattern: str = "image_{n:04d}"
    start: int = 1

class BulkMoveCopyIn(BaseModel):
    image_ids: list[int]
    target_project_id: int
    copy_files: bool = False

class FfmpegPathIn(BaseModel):
    path: str = ""

class PoseAutolabelIn(BaseModel):
    only_empty: bool = True
    iou_threshold: float = 0.30
    conf: float = 0.25

class SmartCopyIn(BaseModel):
    mode: str = "clone_all"

class PredictBehaviorIn(BaseModel):
    keypoints: list[dict] = Field(default_factory=list)
    animal_id: Optional[int] = None
    bbox: Optional[dict] = None  # [STAGE1-A:behavior-bbox-relative] {x,y,w,h} in normalized coords
