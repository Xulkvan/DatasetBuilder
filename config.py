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
BEHAVIOR_WALK_DELTA = 0.02
BEHAVIOR_ACTIVE_DELTA = 0.06

# === Image ===
FIXED_SIZE = (640, 640)
LETTERBOX_FILL = (114, 114, 114)
THUMB_SIZE = (64, 64)

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
_MODEL_NAME_RE = re.compile(r'^[A-Za-z0-9_\-\.\(\) ]+\.pt$')
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

# === Image extensions ===
IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".webp",
    ".tif", ".tiff", ".avif", ".heic", ".heif", ".gif",
})
