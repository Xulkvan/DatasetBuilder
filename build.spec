# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = [
    ("index.html", "."),
    ("style.css", "."),
    ("app.js", "."),
]

# метаданные (некоторые библиотеки читают их в рантайме)
for pkg in ("torch", "torchvision", "ultralytics",
            "ultralytics-platform", "ultralytics-thop"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# ГЛАВНОЕ: collect_all вытаскивает ВСЕ .pyd/.dll/.so + данные + скрытые импорты
binaries = []
hiddenimports = []
for pkg in ("torch", "torchvision", "ultralytics",
            "ultralytics-platform", "ultralytics-thop"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec] collect_all({pkg}) skipped: {e}")

# ffmpeg/ffprobe рядом
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
    "torchvision._C",           # якорь, чтобы точно не забыли
    "torchvision.ops",
    "webview",
    "webview.platforms.edgechromium",
    "aiosqlite",
    "pymysql",
    "PIL._tkinter_finder",
    "sqlalchemy.dialects.sqlite",
]

excludes = [
    "IPython", "jupyter", "jupyter_core", "notebook",
    "nbconvert", "nbformat", "ipykernel", "ipywidgets",
    "pytest",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    "matplotlib",
    "webview.platforms.qt",
    "webview.platforms.gtk",
    "webview.platforms.cocoa",
    "torch.utils.tensorboard",
    # V7.9.0: дополнительные исключения для уменьшения веса.
    # Ни один из этих модулей не используется в рантайме Dataset Builder.
    "scipy", "scipy.sparse", "scipy.optimize",
    "pandas", "pandas.io",
    "PIL.ImageQt",
    "matplotlib.pyplot", "matplotlib.backends",
]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,           # ← сюда
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
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="DatasetBuilder",
)