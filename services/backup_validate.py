"""[BACKUP] Validation of full backup archive."""
from __future__ import annotations
import json, os, urllib.parse
from schemas_backup import (
    BACKUP_FORMAT, BACKUP_FORMAT_VERSION, Manifest,
    ProjectEntry, ImageEntry, AnnotationEntry, KeypointEntry,
    VideoEntry, TagEntry, ImageTagEntry, VersionEntry,
    BlurRegionEntry, BehaviorValidationEntry, StreamEntry, WebhookEntry,
)
from config import BEHAVIORS, MAX_ANIMAL_ID

REQUIRED_JSON = {
    "manifest.json", "project.json", "videos.json", "images.json",
    "annotations.json", "keypoints.json", "tags.json", "image_tags.json",
}


class BackupValidationError(Exception):
    pass


def _url_has_credentials(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False
    return bool(p.username or p.password)


def validate_archive(tmp_dir: str) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    for name in REQUIRED_JSON:
        if not os.path.exists(os.path.join(tmp_dir, name)):
            errors.append(f"missing required file: {name}")
    if errors:
        return {"errors": errors, "warnings": warnings, "parsed": {}}

    try:
        with open(os.path.join(tmp_dir, "manifest.json"), encoding="utf-8") as f:
            raw = json.load(f)
        manifest = Manifest(**raw)
    except Exception as e:
        errors.append(f"invalid manifest.json: {e}")
        return {"errors": errors, "warnings": warnings, "parsed": {}}

    if manifest.format != BACKUP_FORMAT:
        errors.append(f"wrong format: {manifest.format!r}")
        return {"errors": errors, "warnings": warnings, "parsed": {}}
    if manifest.format_version > BACKUP_FORMAT_VERSION:
        errors.append(
            f"archive format_version={manifest.format_version} > supported "
            f"{BACKUP_FORMAT_VERSION}")
        return {"errors": errors, "warnings": warnings, "parsed": {}}

    def _load(name):
        p = os.path.join(tmp_dir, name)
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            errors.append(f"invalid {name}: {e}")
            return None

    project_raw = _load("project.json")
    videos_raw = _load("videos.json") or []
    images_raw = _load("images.json") or []
    anns_raw = _load("annotations.json") or []
    kps_raw = _load("keypoints.json") or []
    tags_raw = _load("tags.json") or []
    itags_raw = _load("image_tags.json") or []
    versions_raw = _load("versions.json") or []
    blur_raw = _load("blur_regions.json") or []
    bvals_raw = _load("behavior_validations.json") or []
    streams_raw = _load("streams.json") or []
    webhooks_raw = _load("webhooks.json") or []

    # Секреты не должны попадать в архив. Если кто-то вручную дописал
    # secret_key в webhooks.json — это утечка; отказываем.
    for w in webhooks_raw:
        if isinstance(w, dict) and "secret_key" in w:
            errors.append(
                "webhooks.json contains secret_key field — refusing to import "
                "(secrets must never be transferred via archive)")
    if errors:
        return {"errors": errors, "warnings": warnings, "parsed": {}}

    try:
        project = ProjectEntry(**project_raw)
        videos = [VideoEntry(**v) for v in videos_raw]
        images = [ImageEntry(**i) for i in images_raw]
        annotations = [AnnotationEntry(**a) for a in anns_raw]
        keypoints = [KeypointEntry(**k) for k in kps_raw]
        tags = [TagEntry(**t) for t in tags_raw]
        itags = [ImageTagEntry(**x) for x in itags_raw]
        versions = [VersionEntry(**v) for v in versions_raw]
        blur = [BlurRegionEntry(**b) for b in blur_raw]
        bvals = [BehaviorValidationEntry(**b) for b in bvals_raw]
        streams = [StreamEntry(**s) for s in streams_raw]
        webhooks = [WebhookEntry(**w) for w in webhooks_raw]
    except Exception as e:
        errors.append(f"schema validation failed: {e}")
        return {"errors": errors, "warnings": warnings, "parsed": {}}

    for s in streams:
        if _url_has_credentials(s.url):
            errors.append(
                f"stream {s.old_id}: URL contains credentials — refusing "
                f"(re-enter manually without user:pass)")
    if errors:
        return {"errors": errors, "warnings": warnings, "parsed": {}}

    checks = [
        ("videos", manifest.counts.videos, len(videos)),
        ("images", manifest.counts.images, len(images)),
        ("annotations", manifest.counts.annotations, len(annotations)),
        ("keypoints", manifest.counts.keypoints, len(keypoints)),
        ("tags", manifest.counts.tags, len(tags)),
        ("versions", manifest.counts.versions, len(versions)),
        ("blur_regions", manifest.counts.blur_regions, len(blur)),
        ("behavior_validations", manifest.counts.behavior_validations, len(bvals)),
        ("streams", manifest.counts.streams, len(streams)),
        ("webhooks", manifest.counts.webhooks, len(webhooks)),
    ]
    for name, expected, actual in checks:
        if expected != actual:
            warnings.append(f"manifest.counts.{name}={expected} but actual={actual}")

    video_ids = {v.old_id for v in videos}
    image_ids = {i.old_id for i in images}
    ann_ids = {a.old_id for a in annotations}
    tag_ids = {t.old_id for t in tags}

    for img in images:
        fpath = os.path.join(tmp_dir, "files", "images",
                             f"{img.old_id}{img.file_ext}")
        if not os.path.exists(fpath):
            errors.append(
                f"missing image file: files/images/{img.old_id}{img.file_ext}")
        if img.old_video_id is not None and img.old_video_id not in video_ids:
            warnings.append(
                f"image {img.old_id} references unknown video {img.old_video_id}")
        if img.width <= 0 or img.height <= 0:
            warnings.append(
                f"image {img.old_id} has invalid size {img.width}x{img.height}")

    for v in videos:
        base = os.path.join(tmp_dir, "files", "videos")
        candidates = []
        if os.path.isdir(base):
            candidates = [f for f in os.listdir(base)
                          if f.startswith(f"{v.old_id}.")]
        if not candidates:
            warnings.append(f"missing video file for video {v.old_id}")

    for a in annotations:
        if a.old_image_id not in image_ids:
            errors.append(
                f"annotation {a.old_id} references unknown image {a.old_image_id}")
        if not (0 <= a.x <= 1 and 0 <= a.y <= 1 and 0 < a.w <= 1 and 0 < a.h <= 1):
            warnings.append(f"annotation {a.old_id} has out-of-range bbox")
        if a.behavior is not None and a.behavior not in BEHAVIORS:
            warnings.append(
                f"annotation {a.old_id} has unknown behavior {a.behavior!r}")
        if a.animal_id is not None and not (1 <= a.animal_id <= MAX_ANIMAL_ID):
            warnings.append(
                f"annotation {a.old_id} has invalid animal_id {a.animal_id}")
        if a.confidence is not None and not (0 <= a.confidence <= 1):
            warnings.append(
                f"annotation {a.old_id} has invalid confidence {a.confidence}")

    for kp in keypoints:
        if kp.old_annotation_id not in ann_ids:
            errors.append(
                f"keypoint references unknown annotation {kp.old_annotation_id}")

    for it in itags:
        if it.old_image_id not in image_ids:
            warnings.append(
                f"image_tag references unknown image {it.old_image_id}")
        if it.old_tag_id not in tag_ids:
            warnings.append(
                f"image_tag references unknown tag {it.old_tag_id}")

    for b in blur:
        if b.old_image_id not in image_ids:
            warnings.append(
                f"blur_region references unknown image {b.old_image_id}")

    for bv in bvals:
        if bv.old_annotation_id not in ann_ids:
            warnings.append(
                f"behavior_validation references unknown annotation "
                f"{bv.old_annotation_id}")

    return {
        "errors": errors,
        "warnings": warnings,
        "parsed": {
            "manifest": manifest, "project": project,
            "videos": videos, "images": images, "annotations": annotations,
            "keypoints": keypoints, "tags": tags, "image_tags": itags,
            "versions": versions, "blur": blur, "bvals": bvals,
            "streams": streams, "webhooks": webhooks,
        },
    }
