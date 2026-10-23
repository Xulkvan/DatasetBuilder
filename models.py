from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean, DateTime, UniqueConstraint, Index
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
    thumbnail_size = Column(Integer, nullable=True)
    default_zoom = Column(Float, nullable=True)
    images = relationship("ImageModel", back_populates="project", cascade="all, delete-orphan")
    tags = relationship("Tag", back_populates="project", cascade="all, delete-orphan")
    __table_args__ = (Index('ix_projects_deleted', 'is_deleted', 'deleted_at'),)

class ImageModel(Base):
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
