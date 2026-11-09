"""[STAGE3:route-permissions] Route → permission table.

Used by `permission_middleware_fn` in `services/auth_service.py`.
Public routes (auth/setup, /api/v2/*, static) are NOT listed here — they
are bypassed by the middleware.

Order matters: first match wins. Rules are (method, path_pattern, permission).
`{name}` in path is converted to `[^/]+`.
"""
import re


_RULES = [
    # --- User management ---
    ("GET",    "/api/users",                          "user.manage"),
    ("POST",   "/api/users",                          "user.manage"),
    ("DELETE", "/api/users/{id}",                     "user.manage"),

    # --- Hard delete & dangerous project ops ---
    ("DELETE", "/api/projects/{id}/permanent",        "project.delete_hard"),
    ("POST",   "/api/projects/trash/empty",           "project.delete_hard"),

    # --- Models ---
    ("POST",   "/api/models/download",                "model.manage"),
    ("POST",   "/api/models/activate",                "model.manage"),
    ("POST",   "/api/models/{name}/rename",           "model.manage"),
    ("POST",   "/api/models/{name}/export_onnx",      "model.manage"),
    ("POST",   "/api/models/{name}/reveal",           "model.manage"),
    ("DELETE", "/api/models/{name}",                  "model.manage"),
    ("GET",    "/api/models/{name}/edge_package",     "model.manage"),

    # --- Training & pipeline ---
    ("POST",   "/api/train/start",                    "model.manage"),
    ("POST",   "/api/train/stop",                     "model.manage"),
    ("POST",   "/api/train/reset",                    "model.manage"),
    ("POST",   "/api/projects/{id}/pipeline/start",   "pipeline.run"),
    ("POST",   "/api/projects/{id}/pipeline/stop",    "pipeline.run"),

    # --- Autolabel / ML ---
    ("POST",   "/api/autolabel/batch/start",          "model.inference"),
    ("POST",   "/api/images/{id}/autolabel",          "model.inference"),
    ("POST",   "/api/images/{id}/autolabel_debug",    "model.inference"),
    ("POST",   "/api/images/{id}/autolabel_pose",     "model.inference"),
    ("POST",   "/api/images/{id}/sam_predict",        "model.inference"),
    ("POST",   "/api/images/{id}/predict_behavior",   "model.inference"),
    ("POST",   "/api/projects/{id}/behavior/train_classifier", "model.manage"),
    ("POST",   "/api/projects/{id}/behavior/calibrate", "model.inference"),

    # --- Export ---
    ("GET",    "/api/projects/{id}/export/yolo",      "dataset.export"),
    ("GET",    "/api/projects/{id}/export/coco",      "dataset.export"),
    ("GET",    "/api/projects/{id}/export/cvat",      "dataset.export"),
    ("GET",    "/api/projects/{id}/export/parquet",   "dataset.export"),
    ("GET",    "/api/projects/{id}/export/sql",       "dataset.export"),
    ("GET",    "/api/projects/{id}/export/agtech_csv", "dataset.export"),
    ("GET",    "/api/projects/{id}/dataset_card",     "dataset.export"),

    # --- Backup / storage ---
    ("POST",   "/api/storage/backup_db",              "dataset.export"),
    ("POST",   "/api/storage/migrate/start",          "project.delete_hard"),  # [STAGE2:route-rules]
    ("POST",   "/api/projects/{id}/backup",           "dataset.export"),

    # --- Webhooks ---
    ("POST",   "/api/projects/{id}/webhooks",         "webhook.manage"),
    ("DELETE", "/api/webhooks/{id}",                  "webhook.manage"),
    ("POST",   "/api/webhooks/{id}/test",             "webhook.manage"),
    ("POST",   "/api/webhooks/{id}/toggle",           "webhook.manage"),

    # --- Tags ---
    ("POST",   "/api/projects/{id}/tags",             "tag.manage"),
    ("PATCH",  "/api/tags/{id}",                      "tag.manage"),
    ("DELETE", "/api/tags/{id}",                      "tag.manage"),
    ("POST",   "/api/images/batch_tags",              "tag.manage"),

    # --- Streams ---
    ("POST",   "/api/projects/{id}/streams",          "stream.manage"),
    ("POST",   "/api/projects/{id}/streams/{sid}/stop", "stream.manage"),

    # --- Annotations (write) ---
    ("POST",   "/api/images/{id}/annotations",        "annotation.write"),
    ("PUT",    "/api/annotations/{id}/keypoints",     "annotation.write"),
    ("DELETE", "/api/annotations/{id}/keypoints",     "annotation.write"),

    # --- Image write ---
    ("POST",   "/api/projects/{id}/images",           "annotation.write"),
    ("POST",   "/api/images/bulk_delete",             "image.delete"),
    ("POST",   "/api/images/batch_delete",            "image.delete"),
    ("POST",   "/api/images/batch_permanent_delete",  "image.delete"),
    ("DELETE", "/api/images/{id}",                    "image.delete"),
    ("DELETE", "/api/images/{id}/permanent",          "image.delete"),
    ("POST",   "/api/images/bulk_rename",             "image.delete"),
    ("POST",   "/api/images/bulk_move_to_project",    "annotation.write"),
    ("POST",   "/api/images/bulk_copy_to_project",    "annotation.write"),

    # --- Audit ---
    ("GET",    "/api/audit",                          "audit.read"),
    ("GET",    "/api/logs",                           "logs.read"),
]


def _compile(pattern: str) -> "re.Pattern":
    parts = re.split(r"(\{[^}]+\})", pattern)
    rx = ""
    for p in parts:
        if p.startswith("{") and p.endswith("}"):
            rx += r"[^/]+"
        else:
            rx += re.escape(p)
    return re.compile("^" + rx + "$")




# [STAGE4:assign-review-rules]
_RULES += [
    ("POST", "/api/projects/{id}/assign",               "project.manage"),
    ("POST", "/api/projects/{id}/assign/round_robin",   "project.manage"),
    ("POST", "/api/images/{id}/submit_for_review",      "annotation.write"),
    ("POST", "/api/images/{id}/approve",                "annotation.review"),
    ("POST", "/api/images/{id}/reject",                 "annotation.review"),
    ("GET",  "/api/projects/{id}/my_tasks",             "annotation.write"),
    ("GET",  "/api/projects/{id}/review_queue",         "annotation.review"),
    ("GET",  "/api/projects/{id}/assignment_stats",     "project.manage"),
]
# [/STAGE4:assign-review-rules]

# [PATCH:STAGE2-F-11-route]
_RULES += [
    ("POST", "/api/projects/{id}/pipeline/rollback",    "pipeline.run"),
]

# [STAGE5:lock-rules]
_RULES += [
    ("POST",   "/api/images/{id}/lock",                 "annotation.write"),
    ("POST",   "/api/images/{id}/lock/heartbeat",       "annotation.write"),
    ("DELETE", "/api/images/{id}/lock",                 "annotation.write"),
    ("GET",    "/api/images/{id}/lock",                 "annotation.write"),
]
# [/STAGE5:lock-rules]


# ============================================================================
# [STAGE2:route-rules] Расширенные правила (Stage 2 — RBAC completeness)
# ============================================================================
_RULES += [
    # --- Projects: create / delete / settings / clear / version / keypoint schema ---
    ("POST",   "/api/projects",                                 "project.manage"),
    ("DELETE", "/api/projects/{id}",                            "project.manage"),
    ("POST",   "/api/projects/{id}/restore",                    "project.manage"),
    ("PATCH",  "/api/projects/{id}/settings",                   "project.manage"),
    ("POST",   "/api/projects/{id}/clear_annotations",          "project.manage"),
    ("POST",   "/api/projects/{id}/version",                    "project.manage"),
    ("GET",    "/api/projects/{id}/versions",                   "project.manage"),
    ("GET",    "/api/projects/{id}/versions/diff",              "project.manage"),
    ("PUT",    "/api/projects/{id}/keypoint_schema",            "project.manage"),
    ("DELETE", "/api/projects/{id}/keypoint_schema",            "project.manage"),
    ("POST",   "/api/projects/{id}/interpolate",                "annotation.write"),

    # --- Images: write operations on annotations ---
    ("POST",   "/api/images/{id}/rename",                       "annotation.write"),
    ("POST",   "/api/images/{id}/toggle_hard",                  "annotation.write"),
    ("POST",   "/api/images/{id}/smart_copy_from/{src}",        "annotation.write"),
    ("POST",   "/api/images/{id}/link_from_prev",               "annotation.write"),
    ("POST",   "/api/images/{id}/behavior_audit",               "model.inference"),
    ("POST",   "/api/images/batch_restore",                     "image.delete"),
    ("POST",   "/api/images/batch_permanent_delete",            "image.delete"),

    # --- Blur regions (privacy) ---
    ("POST",   "/api/images/{id}/blur_regions",                 "blur.manage"),
    ("DELETE", "/api/images/{id}/blur_regions",                 "blur.manage"),

    # --- Behavior calibration (train_classifier covered in base rules) ---
    ("POST",   "/api/projects/{id}/behavior/calibrate",         "model.inference"),
    ("DELETE", "/api/projects/{id}/behavior/calibrate",         "model.inference"),

    # --- Streams: stop ---
    ("POST",   "/api/projects/{id}/streams/{sid}/stop",         "stream.manage"),

    # --- System / ffmpeg / storage reset (start & backup covered in base rules) ---
    ("POST",   "/api/system/ffmpeg/set_path",                   "model.manage"),
    ("POST",   "/api/storage/migrate/reset",                    "project.delete_hard"),

    # --- Video tracking ---
    ("POST",   "/api/videos/{id}/track",                        "model.inference"),
    ("POST",   "/api/videos/{id}/track/stop",                   "model.inference"),
    ("GET",    "/api/videos/{id}/track/metrics",                "model.inference"),
]
# [/STAGE2:route-rules]

# [PATCH:STAGE1-C24] bulk_rename = mass mutation -> image.delete
_RULES += [
    ("POST", "/api/images/bulk_rename", "image.delete"),
]



# ─────────────────────────────────────────────────────────────────────────
# Stage 5.2 — fail-closed RBAC: расширенный whitelist + дополнительные
# правила для ранее не зарегистрированных /api/* роутов.
# ─────────────────────────────────────────────────────────────────────────
_PUBLIC_API_PREFIXES = (
    "/api/auth/", "/api/setup/", "/api/v2/",
)
_PUBLIC_API_EXACT = frozenset({
    "/api/health", "/api/metrics", "/api/version",
})

# READ (GET) routes — требуют annotation.write (доступно всем аутентифицированным)
_READ_ANNOTATION_WRITE = [
    "/api/projects",
    "/api/projects/{id}/images",
    "/api/projects/{id}/info",
    "/api/projects/{id}/stats",
    "/api/projects/{id}/stats.csv",
    "/api/projects/{id}/files.csv",
    "/api/projects/{id}/boxes.csv",
    "/api/projects/{id}/trash",
    "/api/projects/{id}/tracks",
    "/api/projects/{id}/tracks/{aid}/frames",
    "/api/projects/{id}/tracks/export",
    "/api/projects/{id}/tracks/quality",
    "/api/projects/{id}/navigate_with_aid",
    "/api/projects/{id}/duplicates",
    "/api/projects/{id}/similar/{image_id}",
    "/api/projects/{id}/next_animal_id",
    "/api/projects/{id}/validate",
    "/api/projects/{id}/behavior_agreement",
    "/api/projects/{id}/behavior/classifier_meta",
    "/api/projects/{id}/behavior/thresholds",
    "/api/projects/{id}/active_learning",
    "/api/projects/{id}/active_learning_queue",
    "/api/projects/{id}/skeletons_count",
    "/api/projects/{id}/agreement_score",
    "/api/projects/{id}/versions/diff_extended",
    "/api/projects/{id}/videos",
    "/api/projects/{id}/webhooks",
    "/api/projects/{id}/streams",
    "/api/projects/{id}/tags",
    "/api/projects/{id}/backup/download/{filename}",
    "/api/projects/{id}/pipeline/status",
    "/api/projects/{id}/pipeline/events",
    "/api/projects/{id}/keypoint_schema",
    "/api/videos/{id}",
    "/api/videos/{id}/stream",
    "/api/videos/{id}/frame_annotations",
    "/api/videos/{id}/track/status",
    "/api/videos/{id}/track/events",
    "/api/images/{id}/file",
    "/api/images/{id}/thumb",
    "/api/images/{id}/annotations",
    "/api/images/{id}/motion_vectors",
    "/api/images/{id}/similar_with_skeleton",
    "/api/images/{id}/keypoints_by_index",
    "/api/images/{id}/tags",
    "/api/images/{id}/blur_regions",
    "/api/keypoint_schema",
    "/api/object_classes",
    "/api/video/capabilities",
    "/api/import/status",
    "/api/permissions",
    "/api/sam/status",
    "/api/settings/trash_ttl",
    "/api/settings/model_mode",
    "/api/models",
    "/api/models/compatibility",
    "/api/models/bootstrap/status",
    "/api/models/bootstrap/events",
    "/api/train/status",
    "/api/train/events",
    "/api/train/runs",
    "/api/train/runs/{folder}/metrics",
    "/api/train/runs/{folder}/file/{name}",
    "/api/storage/info",
    "/api/storage/paths",
    "/api/storage/migrate/status",
    "/api/system/ffmpeg",
    "/api/autolabel/batch/status",
    "/api/autolabel/batch/events",
    "/api/projects/trash",
]

for _p in _READ_ANNOTATION_WRITE:
    _RULES.append(("GET", _p, "annotation.write"))

# WRITE routes — точечные правила
_WRITE_SPECIFIC = [
    ("DELETE", "/api/logs", "logs.read"),
    ("DELETE", "/api/videos/{id}", "image.delete"),
    ("POST",   "/api/projects/{id}/trash/empty", "image.delete"),
    ("POST",   "/api/images/{id}/restore", "image.delete"),
    ("POST",   "/api/images/{id}/reveal", "annotation.write"),
    ("POST",   "/api/images/{id}/tags", "tag.manage"),
    ("POST",   "/api/images/{id}/predict_behavior", "model.inference"),
    ("POST",   "/api/images/{target_id}/copy_annotations_from/{source_id}", "annotation.write"),
    ("POST",   "/api/projects/{id}/tracks/merge", "annotation.write"),
    ("POST",   "/api/projects/{id}/tracks/reassign", "annotation.write"),
    ("DELETE", "/api/projects/{id}/tracks/{animal_id}", "annotation.write"),
    ("POST",   "/api/projects/{id}/validate_behavior", "annotation.write"),
    ("POST",   "/api/autolabel/batch/stop", "model.inference"),
    ("POST",   "/api/sam/set_model", "model.manage"),
    ("POST",   "/api/settings/trash_ttl", "project.manage"),
    ("POST",   "/api/settings/model_mode", "model.manage"),
    ("POST",   "/api/projects/{id}/videos/upload", "annotation.write"),
    ("POST",   "/api/import/cancel", "annotation.write"),
    ("POST",   "/api/projects/{id}/import", "annotation.write"),
    ("POST",   "/api/projects/{id}/import/roboflow", "annotation.write"),
    ("POST",   "/api/projects/{id}/import/supervisely", "annotation.write"),
    ("POST",   "/api/projects/{id}/import/url", "annotation.write"),
    ("POST",   "/api/projects/{id}/import/local_folder", "annotation.write"),
    ("POST",   "/api/projects/{id}/import/labelbox", "annotation.write"),
    ("POST",   "/api/projects/{id}/import/scale", "annotation.write"),
    ("POST",   "/api/projects/{id}/import/darwin", "annotation.write"),
]

for _m, _p, _perm in _WRITE_SPECIFIC:
    _RULES.append((_m, _p, _perm))

# Full project backup export
_RULES += [
    ("GET", "/api/projects/{id}/export/full", "dataset.export"),
]

# Full project backup import
_RULES += [
    ("POST", "/api/projects/import/full", "project.manage"),
]


# ── Async full backup routes ────────────────────────────────────
# POST/PUT/DELETE — RBAC-проверка; GET status/events — доступ
# только тем, у кого есть права на соответствующий ресурс.
_RULES += [
    ("POST", "/api/projects/{id}/export/full/async",    "dataset.export"),
    ("GET",  "/api/projects/{id}/export/full/download", "dataset.export"),
    ("GET",  "/api/projects/export/full/status",        "dataset.export"),
    ("GET",  "/api/projects/export/full/events",        "dataset.export"),
    ("POST", "/api/projects/import/full/async",         "project.manage"),
    ("POST", "/api/projects/import/full/reset",         "project.manage"),
    ("POST", "/api/projects/import/full/cancel",        "project.manage"),
    ("GET",  "/api/projects/import/full/status",        "project.manage"),
    ("GET",  "/api/projects/import/full/events",        "project.manage"),
]



_RULES += [
    ("GET", "/api/projects/export/full/download", "dataset.export"),
]

_COMPILED = [(m, _compile(p), perm) for (m, p, perm) in _RULES]


def match_permission(method: str, path: str):
    """Return permission string, "__deny__" (fail-closed) or None (public)."""
    method_u = (method or "").upper()
    for m, rx, perm in _COMPILED:
        if m == method_u and rx.match(path):
            return perm
    if path.startswith("/api/"):
        for _pfx in _PUBLIC_API_PREFIXES:
            if path.startswith(_pfx):
                return None
        if path in _PUBLIC_API_EXACT:
            return None
        return "__deny__"
    return None
# [/STAGE3:route-permissions]
