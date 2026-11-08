"""[BACKUP] Pydantic-схемы для full backup. Контракт между export и import.

Контракт иммутабелен между этапами. Имена полей — точно как ниже.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

BACKUP_FORMAT = "datasetbuilder_full_backup"
BACKUP_FORMAT_VERSION = 1


class ManifestCounts(BaseModel):
    videos: int = 0
    images: int = 0
    annotations: int = 0
    keypoints: int = 0
    tags: int = 0
    versions: int = 0
    blur_regions: int = 0
    behavior_validations: int = 0
    streams: int = 0
    webhooks: int = 0


class ManifestOptions(BaseModel):
    include_videos: bool = True
    include_versions: bool = True
    include_blur_regions: bool = True
    include_behavior_validations: bool = True
    # По умолчанию выключены: URL стримов могут содержать credentials,
    # webhook'и не переносят secret_key — перенос по умолчанию создал бы
    # ложное впечатление «всё восстановлено».
    include_streams: bool = False
    include_webhooks: bool = False


class Manifest(BaseModel):
    format: str = BACKUP_FORMAT
    format_version: int = BACKUP_FORMAT_VERSION
    app_version: str
    created_at: str
    project: dict
    counts: ManifestCounts
    options: ManifestOptions
    warnings: list[str] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    name: str
    object_class: str
    object_class_source: str
    data_retention_days: int = 0
    trash_ttl_days_override: Optional[int] = None
    thumbnail_size: Optional[int] = None
    default_zoom: Optional[float] = None
    random_seed: int = 42
    auto_blur_enabled: bool = False
    auto_blur_classes: Optional[str] = None


class KeypointSchemaEntry(BaseModel):
    schema_list: list[dict]


class VideoEntry(BaseModel):
    old_id: int
    filename: str
    fps: Optional[float] = None
    frame_count: Optional[int] = None
    duration_sec: Optional[float] = None
    extract_fps: Optional[float] = None
    images_count: Optional[int] = None
    created_at: Optional[str] = None


class ImageEntry(BaseModel):
    old_id: int
    old_video_id: Optional[int] = None
    filename: str
    frame_index: Optional[int] = None
    timestamp_sec: Optional[float] = None
    width: int
    height: int
    original_width: Optional[int] = None
    original_height: Optional[int] = None
    is_hard: bool = False
    is_stream_frame: bool = False
    phash: Optional[str] = None
    created_at: Optional[str] = None
    file_size: Optional[int] = None
    revision: int = 1
    review_status: str = "unassigned"
    assigned_to_username: Optional[str] = None
    reviewed_by_username: Optional[str] = None
    review_comment: Optional[str] = None
    reviewed_at: Optional[str] = None
    file_ext: str


class AnnotationEntry(BaseModel):
    old_id: int
    old_image_id: int
    x: float
    y: float
    w: float
    h: float
    label: str
    confidence: Optional[float] = None
    is_frozen: bool = False
    behavior: Optional[str] = None
    behavior_source: Optional[str] = None
    animal_id: Optional[int] = None


class KeypointEntry(BaseModel):
    old_annotation_id: int
    name: str
    x: float
    y: float
    visibility: float = 1.0


class TagEntry(BaseModel):
    old_id: int
    name: str
    color: Optional[str] = None


class ImageTagEntry(BaseModel):
    old_image_id: int
    old_tag_id: int


class VersionEntry(BaseModel):
    hash: str
    created_at: Optional[str] = None
    image_count: int = 0
    annotation_count: int = 0
    keypoint_count: int = 0
    behavior_count: int = 0


class BlurRegionEntry(BaseModel):
    old_image_id: int
    x: float
    y: float
    w: float
    h: float


class BehaviorValidationEntry(BaseModel):
    old_annotation_id: int
    auto_behavior: Optional[str] = None
    true_behavior: str
    is_match: int = 0
    validated_at: Optional[str] = None
    validated_by: Optional[str] = None


class StreamEntry(BaseModel):
    old_id: int
    url: str
    name: Optional[str] = None
    capture_fps: float = 1.0
    is_active: bool = False


class WebhookEntry(BaseModel):
    # secret_key намеренно отсутствует: секреты не переносятся через архив.
    # При импорте secret_key=None; пользователь задаёт заново.
    old_id: int
    url: str
    event_type: str
    active: bool = True
