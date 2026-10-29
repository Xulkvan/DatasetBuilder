from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey, Boolean, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from database import Base

DEFAULT_OBJECT_CLASS = "pig"

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="0")
    deleted_at = Column(DateTime, nullable=True)
    object_class = Column(String(128), nullable=False, default=DEFAULT_OBJECT_CLASS, server_default=DEFAULT_OBJECT_CLASS)
    object_class_source = Column(String(16), nullable=False, default="list", server_default="list")
    trash_ttl_days_override = Column(Integer, nullable=True)
    data_retention_days = Column(Integer, nullable=False, default=0, server_default="0")  # [PATCH:STAGE1_DATA_RETENTION_MODEL]
    thumbnail_size = Column(Integer, nullable=True)
    default_zoom = Column(Float, nullable=True)
    # [STAGE2:random-seed]
    random_seed = Column(Integer, nullable=False, default=42, server_default="42")
    # [FIX:v1341-backend] auto-blur persons/plates
    auto_blur_enabled = Column(Boolean, nullable=False, default=False, server_default="0")
    auto_blur_classes = Column(Text, nullable=True)
    images = relationship("ImageModel", back_populates="project", cascade="all, delete-orphan")
    tags = relationship("Tag", back_populates="project", cascade="all, delete-orphan")
    __table_args__ = (Index('ix_projects_deleted', 'is_deleted', 'deleted_at'),)

class ImageModel(Base):
    # [STAGE4:image-fields]
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assigned_at = Column(DateTime, nullable=True)
    review_status = Column(String(16), nullable=False, default="unassigned", index=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_comment = Column(Text, nullable=True)
    revision = Column(Integer, nullable=False, default=1)
    # [/STAGE4:image-fields]
    __tablename__ = "images"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    path = Column(String(512), nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="0")
    deleted_at = Column(DateTime, nullable=True)
    phash = Column(String(16), nullable=True)
    is_hard = Column(Boolean, nullable=False, default=False, server_default="0")
    video_id = Column(Integer, nullable=True, index=True)
    frame_index = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=True)
    file_size = Column(Integer, nullable=True)
    timestamp_sec = Column(Float, nullable=True)
    original_width  = Column(Integer, nullable=True)  # [PATCH:STAGE1_IMAGE_ORIG_DIMS]
    original_height = Column(Integer, nullable=True)  # [PATCH:STAGE1_IMAGE_ORIG_DIMS]
    is_stream_frame = Column(Boolean, nullable=False, default=False, server_default="0")  # [STAGE3:stream-flag]
    project = relationship("Project", back_populates="images")
    annotations = relationship("Annotation", back_populates="image", cascade="all, delete-orphan")
    tags = relationship("ImageTag", back_populates="image", cascade="all, delete-orphan")
    __table_args__ = (
        Index('ix_images_proj_deleted', 'project_id', 'is_deleted'),
        Index('ix_images_deleted_at', 'is_deleted', 'deleted_at'),
        Index('ix_images_phash', 'project_id', 'phash'),
    )

class Annotation(Base):
    __tablename__ = "annotations"
    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    w = Column(Float, nullable=False)
    h = Column(Float, nullable=False)
    label = Column(String(64), nullable=False, default=DEFAULT_OBJECT_CLASS)
    confidence = Column(Float, nullable=True)
    is_frozen = Column(Boolean, nullable=False, default=False, server_default="0")
    behavior = Column(String(32), nullable=True)
    behavior_source = Column(String(16), nullable=True)  # [STAGE1-A:behavior-source] heuristic | manual | classifier
    animal_id = Column(Integer, nullable=True)
    image = relationship("ImageModel", back_populates="annotations")

class Keypoint(Base):
    __tablename__ = "keypoints"
    id = Column(Integer, primary_key=True, index=True)
    annotation_id = Column(Integer, ForeignKey("annotations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(32), nullable=False)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    visibility = Column(Float, nullable=False, default=1.0, server_default="1.0")
    __table_args__ = (UniqueConstraint("annotation_id", "name", name="uq_ann_kp_name"),)

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(64), primary_key=True)
    value = Column(String(255), nullable=False)

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    color = Column(String(7), nullable=True)
    __table_args__ = (UniqueConstraint('project_id', 'name', name='uq_project_tag'),)
    project = relationship("Project", back_populates="tags")

class ImageTag(Base):
    __tablename__ = "image_tags"
    image_id = Column(Integer, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True)
    image = relationship("ImageModel", back_populates="tags")

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    path = Column(String(512), nullable=False)
    fps = Column(Float, nullable=True)
    frame_count = Column(Integer, nullable=True)
    duration_sec = Column(Float, nullable=True)
    extract_fps = Column(Float, nullable=True)
    images_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="0")
    deleted_at = Column(DateTime, nullable=True)
    __table_args__ = (Index('ix_videos_project', 'project_id', 'is_deleted'),)

# ============================================================================
# [STAGE1:models-ext] Data Versioning + Webhooks
# ============================================================================
class DatasetVersion(Base):
    # [PATCH:VERSION_KP_BEH_COLUMNS]
    keypoint_count = Column(Integer, default=0)
    behavior_count = Column(Integer, default=0)
    __tablename__ = "dataset_versions"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, nullable=True)
    image_count = Column(Integer, nullable=False, default=0, server_default="0")
    annotation_count = Column(Integer, nullable=False, default=0, server_default="0")


class Webhook(Base):
    __tablename__ = "webhooks"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    url = Column(String(512), nullable=False)
    event_type = Column(String(64), nullable=False)
    secret_key = Column(String(128), nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    created_at = Column(DateTime, nullable=True)

# ============================================================================
# [STAGE2:blur-model] Области размытия
# ============================================================================
class BlurRegion(Base):
    __tablename__ = "blur_regions"
    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("images.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    w = Column(Float, nullable=False)
    h = Column(Float, nullable=False)


# ============================================================================
# [STAGE2:keypoint-schema-model] Кастомная схема скелета для проекта.
# ============================================================================
class ProjectKeypointSchema(Base):
    __tablename__ = "project_keypoint_schemas"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), unique=True)
    schema_json = Column(Text)  # JSON string: [{"name": "nose", "parent": null}, ...]
# [/STAGE2:keypoint-schema-model]


# ============================================================================
# [STAGE3:stream-model] RTSP-потоки (симуляция реального времени).
# ============================================================================
class Stream(Base):
    __tablename__ = "streams"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    url = Column(String(512))   # rtsp://...
    name = Column(String(128))
    is_active = Column(Boolean, default=True)
    capture_fps = Column(Float, nullable=False, default=1.0, server_default="1.0")  # [FIX:v1341-backend]
# [/STAGE3:stream-model]


# ============================================================================
# [STAGE1:AUDIT-LOG-MODEL] Журнал всех POST/PUT/DELETE запросов.
# ============================================================================
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    user_ip = Column(String(64), nullable=True)
    action = Column(String(16), nullable=False)
    details = Column(Text, nullable=True)
# [/STAGE1:AUDIT-LOG-MODEL]

# [PATCH:STAGE2_3:rbac-models]
class User(Base):
    """[PATCH:STAGE2_3] Minimal user model for RBAC."""
    # [STAGE0:user-must-change-password]
    must_change_password = Column(Integer, nullable=False, default=0)
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False, default="")
    role = Column(String(32), nullable=False, default="annotator")
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=True)


class UserProjectAccess(Base):
    """[PATCH:STAGE2_3] Maps users to projects they can access."""
    __tablename__ = "user_project_access"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
# [/PATCH:STAGE2_3:rbac-models]

# [PATCH:STAGE3_1:validation-model]
class BehaviorValidation(Base):
    """[PATCH:STAGE3_1] Expert ground-truth vs auto-label comparisons."""
    __tablename__ = "behavior_validation"
    id = Column(Integer, primary_key=True, autoincrement=True)
    annotation_id = Column(Integer, ForeignKey("annotations.id"),
                           nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"),
                        nullable=False, index=True)
    auto_behavior = Column(String(32), nullable=True)
    true_behavior = Column(String(32), nullable=False)
    is_match = Column(Integer, nullable=False, default=0)
    validated_at = Column(DateTime, nullable=True)
    validated_by = Column(String(64), nullable=True)
# [/PATCH:STAGE3_1:validation-model]


# ============================================================================
# [STAGE0:auth-models] Team Edition: Session & ImageLock
# ============================================================================
# Requires Column, Integer, String, DateTime, ForeignKey (already imported
# in models.py for User/AuditLog/ImageModel definitions).

class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash = Column(String(128), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    user_agent = Column(String(256), nullable=True)
    ip_at_login = Column(String(64), nullable=True)


class ImageLock(Base):
    __tablename__ = "image_locks"
    image_id = Column(Integer, ForeignKey("images.id", ondelete="CASCADE"),
                      primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"),
                        nullable=True) # [PATCH:FIX_LOCK_SESSION_ID_NULLABLE]
    acquired_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
# [/STAGE0:auth-models]
