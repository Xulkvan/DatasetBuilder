"""FFmpeg integration: resolve, probe, extract frames."""
import os
import sys
import json
import shutil
import subprocess
import threading
import logging
from config import SETTING_FFMPEG_PATH, MAX_VIDEO_FRAMES

log = logging.getLogger("db")

_SUBPROC_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

_FFMPEG_PATHS = {"ok": False, "ffmpeg": "ffmpeg", "ffprobe": "ffprobe", "source": ""}
_FFMPEG_LOCK = threading.Lock()

def _resolve_ffmpeg():
    from database import SessionLocal
    from services.settings_service import get_setting
    try:
        db = SessionLocal()
        try:
            custom = get_setting(db, SETTING_FFMPEG_PATH, "")
        finally:
            db.close()
        if custom and os.path.isfile(custom):
            ff_dir = os.path.dirname(custom)
            fp_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
            ffprobe = os.path.join(ff_dir, fp_name)
            return True, custom, (ffprobe if os.path.isfile(ffprobe) else ""), "setting"
    except Exception:
        log.exception("resolve ffmpeg: settings check failed")

    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    if ff and fp:
        return True, ff, fp, "path"
    if ff:
        return True, ff, "", "path"

    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
        candidates = [
            os.path.join(local_appdata, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe"),
        ]
        try:
            pkg_root = os.path.join(local_appdata, "Microsoft", "WinGet", "Packages")
            if os.path.isdir(pkg_root):
                for name in os.listdir(pkg_root):
                    if name.lower().startswith("gyan.ffmpeg"):
                        inner = os.path.join(pkg_root, name)
                        try:
                            for sub in os.listdir(inner):
                                cand = os.path.join(inner, sub, "bin", "ffmpeg.exe")
                                if os.path.isfile(cand):
                                    candidates.insert(0, cand)
                        except OSError:
                            continue
        except OSError:
            pass
    else:
        candidates = [
            "/usr/local/bin/ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
            "/usr/bin/ffmpeg",
            "/snap/bin/ffmpeg",
            os.path.expanduser("~/.local/bin/ffmpeg"),
        ]
    for c in candidates:
        if os.path.isfile(c):
            fp_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
            ffprobe = os.path.join(os.path.dirname(c), fp_name)
            return True, c, (ffprobe if os.path.isfile(ffprobe) else ""), "common"

    return False, "", "", ""

def _check_ffmpeg() -> tuple:
    ok, ff, fp, src = _resolve_ffmpeg()
    with _FFMPEG_LOCK:
        _FFMPEG_PATHS["ok"] = bool(ok and ff and fp)
        _FFMPEG_PATHS["ffmpeg"] = ff or "ffmpeg"
        _FFMPEG_PATHS["ffprobe"] = fp or "ffprobe"
        _FFMPEG_PATHS["source"] = src
    if not ok or not ff:
        return False, "ffmpeg не найден"
    if not fp:
        return False, "ffprobe не найден рядом с ffmpeg"
    return True, ""

def _probe_video(path: str):
    try:
        with _FFMPEG_LOCK:
            ffprobe = _FFMPEG_PATHS["ffprobe"]
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate,nb_frames,duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=120,  # [STAGE1-A:probe-timeout] 30 → 120
            creationflags=_SUBPROC_FLAGS,
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return None
        s = streams[0]
        fps_str = str(s.get("r_frame_rate") or "0/1")
        if "/" in fps_str:
            num, den = fps_str.split("/", 1)
            try:
                fps = (float(num) / float(den)) if float(den) else 0.0
            except (TypeError, ValueError):
                fps = 0.0
        else:
            try:
                fps = float(fps_str)
            except ValueError:
                fps = 0.0
        try:
            duration = float(s.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        try:
            frame_count = int(s.get("nb_frames") or 0)
        except (TypeError, ValueError):
            frame_count = 0
        if not frame_count and fps and duration:
            frame_count = int(round(fps * duration))
        return {"fps": fps, "duration": duration, "frame_count": frame_count}
    except Exception:
        log.exception("probe video failed")
        return None

def _extract_frames(video_path: str, out_dir: str, fps: float) -> list:
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "frame_%06d.jpg")
    with _FFMPEG_LOCK:
        ffmpeg = _FFMPEG_PATHS["ffmpeg"]
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "3",
        pattern,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, creationflags=_SUBPROC_FLAGS)
        if r.returncode != 0:
            return []
    except subprocess.TimeoutExpired:
        return []
    except Exception:
        log.exception("extract frames failed")
        return []
    files = sorted(
        os.path.join(out_dir, f)
        for f in os.listdir(out_dir)
        if f.startswith("frame_") and f.endswith(".jpg")
    )
    return files[:MAX_VIDEO_FRAMES]

def _ffmpeg_os_info():
    plat = sys.platform
    if plat.startswith("darwin"):
        return {"os": "mac", "cmd": "brew install ffmpeg",
                "cmd_alt": "Скачай установщик с ffmpeg.org и перетащи ffmpeg в /usr/local/bin/"}
    if plat.startswith("win"):
        return {"os": "win", "cmd": "winget install Gyan.FFmpeg",
                "cmd_alt": "Скачай сборку с gyan.dev/ffmpeg/builds/, распакуй в C:\\ffmpeg"}
    return {"os": "linux", "cmd": "sudo apt install ffmpeg",
            "cmd_alt": "Для Fedora: sudo dnf install ffmpeg ; для Arch: sudo pacman -S ffmpeg"}
