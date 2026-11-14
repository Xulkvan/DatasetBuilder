import os

# Windows + PyInstaller: KMP инициализируется дважды (torch + sklearn) —
# "OMP: Error #15" ломает импорт torch и подвисает при загрузке моделей.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
# ultralytics при import может вызвать pip (subprocess.run) для проверки
# зависимостей. В frozen это = ре-запуск exe без окна (плодит процессы).
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
os.environ.setdefault("YOLO_VERBOSE", "false")

import sys
import time
import socket
import threading
import multiprocessing
import shutil

if __name__ == "__main__":
    multiprocessing.freeze_support()
    import sys
    # PyInstaller + Windows: loky (sklearn n_jobs>1) и ultralytics
    # check_requirements запускают subprocess.Popen([sys.executable, ...]).
    # PyInstaller игнорирует -c/-m, поэтому launcher.py выполняется заново —
    # новый uvicorn + новое webview-окно. freeze_support() ловит только
    # multiprocessing-spawn (--multiprocessing-fork), а loky идёт мимо.
    # Guard: не main-child никогда не открывает окно.
    if getattr(sys, "frozen", False):
        _is_worker = False
        try:
            if multiprocessing.parent_process() is not None:
                _is_worker = True
        except Exception:
            pass
        if (not _is_worker
                and len(sys.argv) > 1
                and sys.argv[1] in ("-c", "-m")):
            _is_worker = True
        if _is_worker:
            sys.exit(0)
    # Перехват запуска обучения из exe
    if len(sys.argv) > 2 and sys.argv[1] == "--train-worker":
        import json
        from ultralytics import YOLO
        try:
            cfg = json.loads(sys.argv[2])
            YOLO(cfg['model']).train(**cfg['kwargs'])
        except Exception as e:
            print(f"Train worker error: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = BASE_DIR

# Куда писать данные (uploads, models, data)
def _pick_data_root():
    """V7.9.0: всегда пишем в системную папку приложения.
    Рабочий стол и папка с exe остаются чистыми; exe можно переносить
    между машинами без потери данных.
    """
    if os.name == "nt":
        base = os.path.join(os.environ.get("LOCALAPPDATA", EXE_DIR), "DatasetBuilder")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support/DatasetBuilder")
    else:
        base = os.path.expanduser("~/.local/share/DatasetBuilder")
    os.makedirs(base, exist_ok=True)

    # Миграция со старой версии: если данные ещё лежат рядом с exe — переносим.
    # Однократно, при первом запуске после обновления.
    for sub in ("data", "models", "uploads", "thumbs", "videos",
                "runs", "backups", "exports", "imports"):
        src = os.path.join(EXE_DIR, sub)
        dst = os.path.join(base, sub)
        if os.path.isdir(src) and not os.path.isdir(dst):
            try:
                shutil.copytree(src, dst)
            except Exception as _e:
                # V10.4.1: не глотаем молча — если миграция данных упала,
                # пользователь должен это увидеть.
                print(f"[launcher] migrate {src} -> {dst} failed: {_e}",
                      file=sys.stderr)
    return base

os.environ["DATA_ROOT"] = _pick_data_root()
# В EXE всегда используем SQLite и локальный режим
os.environ["DB_ENGINE"] = "sqlite"
os.environ["AUTH_MODE"] = "local"
os.environ.setdefault("DEBUG", "0")

import uvicorn
try:
    import webview
except ImportError:
    print("launcher.py требует pywebview.", file=sys.stderr)
    print("Установи: pip install pywebview", file=sys.stderr)
    print("Или запусти сервер напрямую: python run.py", file=sys.stderr)
    sys.exit(1)

from app import app as fastapi_app


# --- Файловые логи (в exe без консоли это единственный способ увидеть ошибки)
import logging as _logging
import logging.handlers as _lh
try:
    _log_dir = os.path.join(os.environ["DATA_ROOT"], "data")
    os.makedirs(_log_dir, exist_ok=True)
    _fh = _lh.RotatingFileHandler(
        os.path.join(_log_dir, "app.log"),
        maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    _fh.setFormatter(_logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    _logging.getLogger().addHandler(_fh)
except Exception:
    pass


def _free_port():
    # V12.4.3: Фиксируем порт, чтобы localStorage (тема, тур) сохранялся между запусками.
    # Если 8000 занят, пробуем следующие 100 портов, и только потом случайный.
    for p in range(8000, 8100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_server(port):
    uvicorn.run(fastapi_app, host="127.0.0.1", port=port,
                log_level="warning", access_log=False)


def _wait(port, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.03) # V11.10.0: ускорено с 0.15 до 0.03
    return False


def _window_extra_kwargs():
    """Best-effort: pywebview 5+ — явно `frameless=False` (native titlebar).

    Patcher 2 (Q2/Q1=B): окно остаётся с нативной рамкой; active-window
    поведение (dimming материалов) реализуется через JS (js/window_chrome.js).
    """
    kw = {}
    try:
        import webview as _wv
        _ver_raw = getattr(_wv, "__version__", "0")
        try:
            _major = int(str(_ver_raw).split(".")[0])
        except (ValueError, TypeError):
            _major = 0
        if _major >= 5:
            kw["frameless"] = False
    except Exception:
        pass
    return kw

def main():
    port = _free_port()
    threading.Thread(target=_run_server, args=(port,), daemon=True).start()

    if not _wait(port):
        # V8.1.0: иконка под ОС (pywebview принимает разные форматы).
        if sys.platform == "darwin":
            _icon_name = "icon.icns"
        elif os.name == "nt":
            _icon_name = "icon.ico"
        else:
            _icon_name = "icon.png"
        _icon_path = os.path.join(BASE_DIR, _icon_name)
        if not os.path.exists(_icon_path):
            _icon_path = os.path.join(BASE_DIR, "icon.ico")
        _window_kwargs = dict(
            width=1440, height=900,
            min_size=(1080, 680),
            background_color="#F5F5F7",
            maximized=True,
        )
        if os.path.exists(_icon_path):
            try:
                _window_kwargs["icon"] = _icon_path
            except Exception:
                pass
        _window_kwargs.update(_window_extra_kwargs())
        webview.create_window("Dataset Builder", f"http://127.0.0.1:{port}", **_window_kwargs)
        webview.start()
        return

    _window_kwargs = dict(
        width=1440, height=900,
        min_size=(1080, 680),
        background_color="#F5F5F7",
        text_select=True,
        maximized=True,
    )
    _window_kwargs.update(_window_extra_kwargs())
    webview.create_window(
        "Dataset Builder",
        f"http://127.0.0.1:{port}",
        **_window_kwargs,
    )
    # V7.9.3: private_mode=False сохраняет localStorage/тему/focus-режим
    # между запусками. storage_path держит их рядом с данными приложения.
    _storage = os.path.join(os.environ["DATA_ROOT"], "webview")
    os.makedirs(_storage, exist_ok=True)
    webview.start(private_mode=False, storage_path=_storage)


if __name__ == "__main__":
    main()