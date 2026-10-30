import os
import re
import io
from typing import Optional
from PIL import Image
from fastapi import HTTPException
from config import MODEL_DIR, _MODEL_NAME_RE

INVALID_CHARS_RE = re.compile(r'[\\/:*?"<>|]')
_MAGIC_JPEG = b'\xff\xd8\xff'
_MAGIC_PNG = b'\x89PNG\r\n\x1a\n'
_MAGIC_GIF87 = b'GIF87a'
_MAGIC_GIF89 = b'GIF89a'
_MAGIC_BMP = b'BM'
_MAGIC_TIFF_LE = b'II*\x00'
_MAGIC_TIFF_BE = b'MM\x00*'

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".avif", ".heic", ".heif", ".gif"})

def _split_name_ext(name: str):
    m = re.match(r'^(.*?)(\.[^.]*)?$', name)
    base = m.group(1) if m and m.group(1) else name
    ext = m.group(2) if m and m.group(2) else ''
    return base, ext

def sanitize_display_name(name: str, fallback: str = "image") -> str:
    if not name: return fallback
    base, ext = _split_name_ext(name)
    base = INVALID_CHARS_RE.sub('_', base).strip().rstrip('.')
    ext = INVALID_CHARS_RE.sub('', ext).strip()
    if not base: base = fallback
    return base + ext

def validate_user_filename(name: str):
    if not name: raise HTTPException(400, "Имя не может быть пустым")
    if len(name) > 200: raise HTTPException(400, {"key": "error.nameTooLong", "fallback": "Слишком длинное имя"})
    if INVALID_CHARS_RE.search(name): raise HTTPException(400, 'Недопустимые символы: \\ / : * ? " < > |')
    if name in ('.', '..'): raise HTTPException(400, "Недопустимое имя")
    if name != name.strip(): raise HTTPException(400, "Имя не может начинаться или заканчиваться пробелом")
    if name.endswith('.'): raise HTTPException(400, "Имя не может заканчиваться точкой")

# [PATCH:STAGE3_UNIQUE_FILENAME]
def make_unique_filename(db, project_id: int, filename: str, exclude_id: int = None) -> str:
    """O(1) проверка + инкрементальный поиск суффикса без загрузки всех имён проекта."""
    from models import ImageModel

    def _exists(name: str) -> bool:
        q = db.query(ImageModel.id).filter(
            ImageModel.project_id == project_id,
            ImageModel.is_deleted.is_(False),
            ImageModel.filename == name,
        )
        if exclude_id is not None:
            q = q.filter(ImageModel.id != exclude_id)
        return q.first() is not None

    if not _exists(filename):
        return filename

    base, ext = _split_name_ext(filename)
    m = re.match(r'^(.*) \((\d+)\)$', base)
    base_root = m.group(1) if m else base
    n = 1
    while _exists(f"{base_root} ({n}){ext}"):
        n += 1
        if n > 100000:
            break
    return f"{base_root} ({n}){ext}"
# [/PATCH:STAGE3_UNIQUE_FILENAME]

def _unique_name_mem(name: str, used: set) -> str:
    if name not in used:
        used.add(name); return name
    base, ext = _split_name_ext(name)
    m = re.match(r'^(.*) \((\d+)\)$', base)
    base_root = m.group(1) if m else base
    n = 1
    while f"{base_root} ({n}){ext}" in used: n += 1
    result = f"{base_root} ({n}){ext}"
    used.add(result); return result

def _is_image_ext(name: str) -> bool:
    _, ext = _split_name_ext(name)
    return ext.lower() in IMAGE_EXTS

def _detect_image_format(data: bytes) -> Optional[str]:
    if len(data) < 16: return None
    if data.startswith(_MAGIC_JPEG): return "JPEG"
    if data.startswith(_MAGIC_PNG): return "PNG"
    if data.startswith(_MAGIC_GIF87) or data.startswith(_MAGIC_GIF89): return "GIF"
    if data.startswith(_MAGIC_BMP): return "BMP"
    if data.startswith(_MAGIC_TIFF_LE) or data.startswith(_MAGIC_TIFF_BE): return "TIFF"
    if data[0:4] == b'RIFF' and data[8:12] == b'WEBP': return "WEBP"
    if data[4:8] == b'ftyp':
        brand = data[8:12]
        if brand in (b'avif', b'avis'): return "AVIF"
        if brand in (b'heic', b'heix', b'hevc', b'hevx', b'mif1', b'msf1'): return "HEIF"
    return None

def _open_image_safe(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except Image.DecompressionBombError: raise HTTPException(413, "Изображение слишком большое")
    except Image.DecompressionBombWarning: raise HTTPException(413, "Изображение слишком большое")
    except HTTPException: raise
    except Exception as e:
        msg = str(e).lower()
        if "avif" in msg or "heif" in msg or "heic" in msg or "decoder" in msg:
            raise HTTPException(415, "Формат требует плагина Pillow. Установи: pip install pillow-avif-plugin pillow-heif")
        raise HTTPException(400, "Invalid image")

def letterbox(img: Image.Image, target_size=(640, 640), fill=(114, 114, 114)) -> Image.Image:
    tw, th = target_size
    w, h = img.size
    if w == 0 or h == 0: return Image.new("RGB", (tw, th), fill)
    scale = min(tw / w, th / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (tw, th), fill)
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return canvas


# === Model path helpers ===
def _is_simple_filename(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    if "\x00" in name:
        return False
    return True


def _safe_model_path(name: str) -> str:
    from fastapi import HTTPException
    if not _is_simple_filename(name):
        raise HTTPException(400, {"key": "error.invalidModelName", "fallback": "Некорректное имя модели"})
    if not _MODEL_NAME_RE.match(name):
        raise HTTPException(400, {"key": "error.invalidModelName", "fallback": "Некорректное имя модели"})
    p = os.path.join(MODEL_DIR, name)
    if os.path.islink(p):
        raise HTTPException(400, "Символические ссылки не поддерживаются")
    real = os.path.realpath(p)
    root = os.path.realpath(MODEL_DIR)
    if not (real == root or real.startswith(root + os.sep)):
        raise HTTPException(400, "Некорректный путь к модели")
    return real


def _sanitize_model_name(name: str) -> str:
    if not name:
        return ""
    base = re.sub(r'[^A-Za-z0-9_\-\. ]', '_', name.strip())
    base = base.strip('._-')
    if not base:
        return ""
    if not base.lower().endswith((".pt", ".onnx")):
        base += ".pt"
    if len(base) > 200:
        base = base[:196] + ".pt"
    if not _is_simple_filename(base):
        return ""
    if not _MODEL_NAME_RE.match(base):
        return ""
    return base


def _unique_model_name_from_disk(name: str) -> str:
    existing = set()
    if os.path.isdir(MODEL_DIR):
        existing = {f for f in os.listdir(MODEL_DIR)
                    if f.lower().endswith((".pt", ".onnx"))}

    if name not in existing:
        return name

    # [STAGE3:FIX-ONNX-EXT] Корректная обработка расширений
    if name.lower().endswith(".onnx"):
        stem = name[:-5]
        ext = ".onnx"
    elif name.lower().endswith(".pt"):
        stem = name[:-3]
        ext = ".pt"
    else:
        stem = name
        ext = ".pt"

    n = 1
    while f"{stem} ({n}){ext}" in existing:
        n += 1
    return f"{stem} ({n}){ext}"

# [STAGE3:ONNX-FILE-SERVICE-END]
