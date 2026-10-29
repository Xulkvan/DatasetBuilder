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
    ("POST",   "/api/storage/migrate/start",          "dataset.export"),
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

# [STAGE5:lock-rules]
_RULES += [
    ("POST",   "/api/images/{id}/lock",                 "annotation.write"),
    ("POST",   "/api/images/{id}/lock/heartbeat",       "annotation.write"),
    ("DELETE", "/api/images/{id}/lock",                 "annotation.write"),
    ("GET",    "/api/images/{id}/lock",                 "annotation.write"),
]
# [/STAGE5:lock-rules]

_COMPILED = [(m, _compile(p), perm) for (m, p, perm) in _RULES]


def match_permission(method: str, path: str):
    """Return permission string or None (public / unprotected)."""
    method_u = (method or "").upper()
    for m, rx, perm in _COMPILED:
        if m == method_u and rx.match(path):
            return perm
    return None
# [/STAGE3:route-permissions]
