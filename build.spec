# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all, copy_metadata, collect_data_files

datas = [
    ("index.html", "."),
    ("style.css", "."),
    ("i18n.js", "."),
    ("js", "js"),  # Фронтенд (модули)
    ("icon.ico", "."),
    ("icon.png", "."),
]

# Метаданные для правильной инициализации библиотек
for pkg in ("torch", "torchvision", "ultralytics", "ultralytics-thop", "ultralytics-platform", "scikit-learn"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

binaries = []
hiddenimports = []

# КРИТИЧНО ДЛЯ YOLO: collect_all собирает все .dll, .pyd и yaml-конфиги
for pkg in ("torch", "torchvision", "ultralytics", "sklearn"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec] collect_all({pkg}) skipped: {e}")

# Явно копируем конфиги Ultralytics (bytetrack.yaml, шрифты)
try:
    datas += collect_data_files("ultralytics")
except Exception:
    pass

# ffmpeg/ffprobe рядом (если лежат в папке vendor)
for name in ("ffmpeg.exe", "ffprobe.exe"):
    p = os.path.join("vendor", name)
    if os.path.exists(p):
        datas.append((p, "."))

hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "torchvision._C",
    "torchvision.ops",
    "webview",
    "webview.platforms.edgechromium",
    "aiosqlite",
    "pymysql",
    "PIL._tkinter_finder",
    "sqlalchemy.dialects.sqlite",
    "cv2",  # Критично для RTSP-стримов
    "sklearn.ensemble",
    "sklearn.tree",
    
    # --- РОУТЕРЫ ---
    "routers", "routers.system", "routers.projects", "routers.tags", 
    "routers.images", "routers.ml", "routers.pipeline", 
    "routers.api_v2", "routers.webhooks",
    
    # --- СЕРВИСЫ ---
    "services", "services.settings_service", "services.behavior_service", 
    "services.ffmpeg_service", "services.bootstrap_service", "services.trash_service", 
    "services.train_service", "services.file_service", "services.image_service", 
    "services.rate_limiter", "services.ml_service", "services.sam_service",
    "services.auto_blur_service", "services.stream_service", 
    "services.versioning_service", "services.webhook_service",
    "services.model_provider", "services.reid_service",
]

excludes = [
    # Убираем только то, что 100% не нужно для работы YOLO и БД
    "IPython", "jupyter", "jupyter_core", "notebook",
    "nbconvert", "nbformat", "ipykernel", "ipywidgets", "pytest",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cocoa",
    "PIL.ImageQt",
    "pandas", "pandas.io",
    
    # Чистим только тяжелый распределенный трейнинг (для инференса он не нужен)
    "torch.distributed", "torch.distributed.rpc",
    "torch.testing", 
    "torch.utils.tensorboard", "torch.utils.benchmark",
    
    # ВАЖНО: НЕ ИСКЛЮЧАЕМ scipy, matplotlib, torchvision.models, torchvision.io, torch.onnx!
    # Иначе авторазметка упадет.
]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DatasetBuilder",
    debug=False,
    strip=False,
    upx=False,           # <--- ОБЯЗАТЕЛЬНО FALSE (UPX ломает PyTorch DLL)
    console=False,
    icon="icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,           # <--- ОБЯЗАТЕЛЬНО FALSE
    name="DatasetBuilder",
)