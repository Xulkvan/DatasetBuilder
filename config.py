"""config.py — Единый источник констант для всего проекта."""
import os
import re

# === Paths ===
import sys

if getattr(sys, 'frozen', False):
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_ROOT = os.getenv("DATA_ROOT", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_ROOT, exist_ok=True)

UPLOAD_DIR = os.path.join(DATA_ROOT, "uploads")
EXPORT_DIR = os.path.join(DATA_ROOT, "exports")
IMPORT_DIR = os.path.join(DATA_ROOT, "imports")
MODEL_DIR  = os.path.join(DATA_ROOT, "models")
RUNS_DIR   = os.path.join(DATA_ROOT, "runs")
THUMB_DIR  = os.path.join(DATA_ROOT, "thumbs")
BACKUP_DIR = os.path.join(DATA_ROOT, "backups")
VIDEO_DIR  = os.path.join(DATA_ROOT, "videos")
DATA_DIR   = os.path.join(DATA_ROOT, "data")

for d in (UPLOAD_DIR, EXPORT_DIR, MODEL_DIR, IMPORT_DIR, RUNS_DIR, THUMB_DIR, BACKUP_DIR, VIDEO_DIR, DATA_DIR):
    os.makedirs(d, exist_ok=True)


# === Object class ===
DEFAULT_OBJECT_CLASS = "pig"
MAX_OBJECT_CLASS_LEN = 128

# === Behavior ===
BEHAVIORS = ("eat", "walk", "lie", "drink", "stand", "active")
MAX_ANIMAL_ID = 999999

def _norm_behavior(b):
    if b is None: return None
    s = str(b).strip().lower()
    return s if s in BEHAVIORS else None

def _norm_animal_id(v):
    if v is None or v == "": return None
    try: n = int(v)
    except (TypeError, ValueError): return None
    if n <= 0 or n > MAX_ANIMAL_ID: return None
    return n

# === Keypoints ===
KEYPOINT_SCHEMA = [
    ("nose",         "Нос",       "Nose",       None),
    ("head_top",     "Макушка",   "Head top",   "nose"),
    ("ear_L",        "Ухо Л",     "Ear L",      "head_top"),
    ("ear_R",        "Ухо П",     "Ear R",      "head_top"),
    ("neck",         "Шея",       "Neck",       "head_top"),
    ("withers",      "Холка",     "Withers",    "neck"),
    ("mid_spine",    "Спина",     "Mid spine",  "withers"),
    ("hip",          "Таз",       "Hip",        "mid_spine"),
    ("tail_base",    "Хвост",     "Tail base",  "hip"),
    ("knee_FL",      "Колено ПЛ", "Knee FL",    "withers"),
    ("hoof_FL",      "Копыто ПЛ", "Hoof FL",    "knee_FL"),
    ("knee_FR",      "Колено ПП", "Knee FR",    "withers"),
    ("hoof_FR",      "Копыто ПП", "Hoof FR",    "knee_FR"),
    ("hock_RL",      "Скак. ЗЛ",  "Hock RL",    "hip"),
    ("hoof_RL",      "Копыто ЗЛ", "Hoof RL",    "hock_RL"),
    ("hock_RR",      "Скак. ЗП",  "Hock RR",    "hip"),
    ("hoof_RR",      "Копыто ЗП", "Hoof RR",    "hock_RR"),
]
KEYPOINT_NAMES = tuple(k[0] for k in KEYPOINT_SCHEMA)
KEYPOINT_VALID = frozenset(KEYPOINT_NAMES)

KEYPOINT_FLIP_IDX = [0, 1, 3, 2, 4, 5, 6, 7, 8, 11, 12, 9, 10, 15, 16, 13, 14]

# === SAM ===
DEFAULT_SAM_MODEL = "mobile_sam.pt"
VALID_SAM_MODELS = ("mobile_sam.pt", "sam2_t.pt", "sam2_s.pt", "sam2_b.pt", "FastSAM-s.pt")
SAM_MIN_POINTS = 1
SAM_MAX_POINTS = 8

# === Settings keys ===
SETTING_TRASH_TTL = "trash_ttl_days"
SETTING_ACTIVE_MODEL = "active_model"
SETTING_ACTIVE_POSE_MODEL = "active_pose_model"
SETTING_USE_SINGLE_MODEL = "use_single_model"
SETTING_SAM_MODEL = "sam_model_name"
SETTING_DEFAULT_EXTRACT_FPS = "default_extract_fps"
SETTING_BACKFILL_DONE = "backfill_v760_done"
SETTING_FFMPEG_PATH = "ffmpeg_path"

DEFAULT_TRASH_TTL_DAYS = 30
ACTIVE_LEARNING_NEW_THRESHOLD = 30

# === ML thresholds ===
CONF_THRESHOLD = 0.25
DEDUP_IOU_THRESHOLD = 0.5
PHASH_DUPLICATE_THRESHOLD = 6
# [STAGE6:config-aligned] было 14 (dead), теперь 12 — как в runtime app.py
SIMILAR_DEFAULT_THRESHOLD = 12

YOLO_RELEASE_TAG = "v8.3.0"
YOLO_URL_TEMPLATE = "https://github.com/ultralytics/assets/releases/download/{tag}/{name}"

# === Behavior thresholds ===
BEHAVIOR_DRINK_NOSE_Y = 0.80
BEHAVIOR_EAT_HEAD_TILT = 0.20
BEHAVIOR_EAT_MID_OFFSET = 0.05
BEHAVIOR_EAT_HEAD_BELOW_SPINE = 0.05
BEHAVIOR_HOOF_OFFSET_STAND = 0.30
BEHAVIOR_BODY_H_STAND = 0.45
BEHAVIOR_WALK_DELTA = 0.06  # [STAGE1-FIX:walk] 0.02 → 0.06
BEHAVIOR_ACTIVE_DELTA_PER_FRAME = 0.04  # [V13.1.0] нормализованная скорость
BEHAVIOR_ACTIVE_BBOX_RATIO = 0.20       # [V13.1.0] сдвиг bbox относительно размера

BEHAVIOR_ACTIVE_DELTA = 0.20  # [STAGE1-FIX:active] 0.06 → 0.20

# === Image ===
FIXED_SIZE = (640, 640)
LETTERBOX_FILL = (114, 114, 114)
THUMB_SIZE = (64, 64)

# [STAGE6:config-aligned] добавлен 96 — routers/projects.py его разрешает
VALID_THUMB_SIZES = (32, 48, 64, 96)
VALID_DEFAULT_ZOOMS = (None, 1.0, 1.5, 2.0, 3.0, 4.0)

# === Video ===
VIDEO_EXTS = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"})
VALID_EXTRACT_FPS = (0.5, 1.0, 2.0, 5.0, 10.0)
DEFAULT_EXTRACT_FPS = 2.0

# === Limits ===
MAX_VIDEO_MB = int(os.getenv("MAX_VIDEO_MB", "2048"))
MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024
MAX_VIDEO_FRAMES = int(os.getenv("MAX_VIDEO_FRAMES", "3000"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_IMPORT_MB = int(os.getenv("MAX_IMPORT_MB", "2048"))
MAX_IMPORT_BYTES = MAX_IMPORT_MB * 1024 * 1024
MAX_EXTRACTED_MB = int(os.getenv("MAX_EXTRACTED_MB", "10240"))
MAX_EXTRACTED_BYTES = MAX_EXTRACTED_MB * 1024 * 1024

# === Training ===
MAX_EPOCHS = 500
MAX_EPOCH_PLAUSIBLE = 10000
MAX_TRAIN_LOG_LINES = 300
MAX_FREEZE_LAYERS = 9

# === Batch ===
BATCH_IMPORT_CHUNK = 100
BATCH_AUTOLABEL_COMMIT_EVERY = 20

# === Validation ===
MIN_BOX_AREA = 0.005
MAX_OVERLAP_IOU = 0.9
NESTED_RATIO = 0.9
MAX_ASPECT = 5.0

# === Regexes ===
INVALID_CHARS_RE = re.compile(r'[\\/:*?"<>|]')
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
_EPOCH_RE = re.compile(r'^\s*(\d+)/(\d+)\s+\d+(?:\.\d+)?G\s')
# [STAGE3:ONNX-MODEL-RE] разрешаем .pt и .onnx
_MODEL_NAME_RE = re.compile(r'^[A-Za-z0-9_\-\.\(\) ]+\.(pt|onnx)$')
# [/STAGE3:ONNX-MODEL-RE]
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

# === Image extensions ===
IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".webp",
    ".tif", ".tiff", ".avif", ".heic", ".heif", ".gif",
})


# ============================================================================
# [STAGE2:keypoint-schema-helper] Схема скелета для конкретного проекта.
# ============================================================================
def get_keypoint_schema_for_project(db, project_id):
    """Возвращает список кортежей (name, label_ru, label_en, parent).

    Если для проекта есть кастомная схема в project_keypoint_schemas —
    возвращает её (в формате KEYPOINT_SCHEMA). Иначе — дефолтную 17-точечную.
    """
    if db is None or project_id is None:
        return list(KEYPOINT_SCHEMA)
    try:
        from models import ProjectKeypointSchema
        import json as _json
        row = (db.query(ProjectKeypointSchema)
                 .filter(ProjectKeypointSchema.project_id == project_id).first())
        if not row or not row.schema_json:
            return list(KEYPOINT_SCHEMA)
        raw = _json.loads(row.schema_json)
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            out.append((
                name,
                item.get("label_ru") or name,
                item.get("label_en") or name,
                item.get("parent") or None,
            ))
        return out or list(KEYPOINT_SCHEMA)
    except Exception:
        return list(KEYPOINT_SCHEMA)
# [/STAGE2:keypoint-schema-helper]

# [FIX:v1341-backend]
# COCO class ids для auto-blur (модель yolov8n.pt).
AUTO_BLUR_COCO_MAP = {
    "person": 0, "bicycle": 1, "car": 2, "motorcycle": 3,
    "bus": 5, "truck": 7,
}
AUTO_BLUR_DEFAULT_CLASSES = ["person"]

# ============================================================================
# [STAGE0:auth-config] Team Edition: auth, sessions, roles, permissions
# ============================================================================
import os as _os  # in case config.py doesn't import os at this point

AUTH_MODE = _os.getenv("AUTH_MODE", "auto").strip().lower()  # local | team | auto

SESSION_COOKIE_NAME       = "pdb_session"
SESSION_TTL_DAYS          = int(_os.getenv("SESSION_TTL_DAYS", "7"))
SESSION_COOKIE_SECURE     = _os.getenv("SESSION_COOKIE_SECURE", "auto")  # auto|1|0
SESSION_COOKIE_SAMESITE   = _os.getenv("SESSION_COOKIE_SAMESITE", "strict")
SESSION_REFRESH_INTERVAL  = int(_os.getenv("SESSION_REFRESH_INTERVAL", "300"))

LOCK_TTL_SECONDS          = int(_os.getenv("LOCK_TTL_SECONDS", "300"))
LOCK_HEARTBEAT_INTERVAL   = int(_os.getenv("LOCK_HEARTBEAT_INTERVAL", "60"))

ROLE_ADMIN      = "admin"
ROLE_MANAGER    = "manager"
ROLE_ANNOTATOR  = "annotator"
ROLE_REVIEWER   = "reviewer"

VALID_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_ANNOTATOR, ROLE_REVIEWER)

ROLE_PERMISSIONS = {
    ROLE_ADMIN: frozenset({
        "user.manage", "project.delete_hard", "project.manage",
        "dataset.export", "model.manage", "model.inference",
        "annotation.write", "annotation.review", "image.delete",
        "tag.manage", "blur.manage", "stream.manage", "pipeline.run",
        "webhook.manage", "audit.read", "logs.read",
    }),
    ROLE_MANAGER: frozenset({
        "project.manage", "dataset.export", "model.manage",
        "model.inference", "annotation.write", "annotation.review",
        "image.delete", "tag.manage", "stream.manage", "pipeline.run",
        "webhook.manage", "logs.read",
    }),
    ROLE_ANNOTATOR: frozenset({
        "annotation.write", "model.inference", "tag.manage",
    }),
    ROLE_REVIEWER: frozenset({
        "annotation.write", "annotation.review", "model.inference",
        "logs.read",
    }),
}


def resolve_auth_mode(db_engine: str) -> str:
    """auto -> local for sqlite, team for postgres/mysql.

    [STAGE6:resolve-auth-mode-dynamic] Читает AUTH_MODE из env на
    каждом вызове. Раньше использовалась глобальная AUTH_MODE,
    зафиксированная при импорте. Из-за этого:
      * `from config import resolve_auth_mode` в routers/auth.py
        держит ссылку на функцию, которая видит старый AUTH_MODE;
      * тест-фикстуры с monkeypatch.setenv + reload(config) не
        переключали режим, хотя env обновлён;
      * team-тесты ловили 401, потому что /api/auth/status
        возвращал mode=local.

    В проде env не меняется после старта — поведение идентично.
    """
    _auth = (os.getenv("AUTH_MODE", "auto") or "auto").strip().lower()
    if _auth in ("local", "team"):
        return _auth
    return "local" if (db_engine or "").lower() == "sqlite" else "team"

# [/STAGE0:auth-config]
