#!/usr/bin/env python3
"""[STAGE1:cli] Headless CLI для DatasetBuilder.

Использование:
    python cli.py run-pipeline --input ./video.mp4 --project my_proj --autolabel --export-yolo
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _boot():
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _cmd_run_pipeline(args: argparse.Namespace) -> int:
    _boot()
    import subprocess
    import uuid
    from database import SessionLocal
    from models import Project, ImageModel, Annotation
    from services.ffmpeg_service import _check_ffmpeg, _probe_video, _extract_frames
    from services.file_service import letterbox
    from PIL import Image

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.name == args.project).first()
        if project is None and args.create_project:
            from logger import utcnow
            project = Project(name=args.project, created_at=utcnow(),
                              is_deleted=False,
                              object_class=args.object_class or "pig",
                              object_class_source="list")
            db.add(project); db.commit(); db.refresh(project)
            print(f"[create] project «{project.name}» (id={project.id})")
        if project is None:
            print(f"[error] project «{args.project}» not found", file=sys.stderr)
            return 2

        input_path = os.path.abspath(args.input)
        if not os.path.exists(input_path):
            print(f"[error] input not found: {input_path}", file=sys.stderr)
            return 3

        # Extract frames if video
        if input_path.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")):
            ok, err = _check_ffmpeg()
            if not ok:
                print(f"[error] ffmpeg: {err}", file=sys.stderr)
                return 4
            info = _probe_video(input_path) or {}
            extract_fps = float(args.fps or 2.0)
            tmp_dir = os.path.join(os.environ.get("DATA_ROOT", "."), "imports",
                                   f"cli_{uuid.uuid4().hex[:8]}")
            frame_paths = _extract_frames(input_path, tmp_dir, extract_fps)
            print(f"[video] {len(frame_paths)} frames @ {extract_fps}fps")
        else:
            frame_paths = [input_path]

        # Import images
        from config import UPLOAD_DIR, FIXED_SIZE, LETTERBOX_FILL
        from logger import utcnow as _now
        from services.image_service import phash_hex
        added = 0
        for fp in frame_paths:
            try:
                pil = Image.open(fp).convert("RGB")
                pil = letterbox(pil, FIXED_SIZE, LETTERBOX_FILL)
                fname = f"{uuid.uuid4().hex}.jpg"
                dest = os.path.join(UPLOAD_DIR, fname)
                pil.save(dest, "JPEG", quality=95)
                try:
                    ph = phash_hex(dest) or ""
                except Exception:
                    ph = ""
                try:
                    fsize = os.path.getsize(dest)
                except OSError:
                    fsize = 0
                im = ImageModel(project_id=project.id,
                                filename=os.path.basename(fp),
                                path=dest, width=FIXED_SIZE[0], height=FIXED_SIZE[1],
                                is_deleted=False, phash=ph or None,
                                is_hard=False, created_at=_now(), file_size=fsize)
                db.add(im); db.commit()
                added += 1
            except Exception as e:
                print(f"[warn] import {fp}: {e}")
        print(f"[import] {added} images")

        # Autolabel
        if args.autolabel:
            from services.ml_service import get_active_model_path, _get_yolo_model, _autolabel_image_with_model
            mp = get_active_model_path(db)
            if not mp:
                print("[warn] no active model — skip autolabel")
            else:
                model = _get_yolo_model(mp)
                imgs = db.query(ImageModel).filter(
                    ImageModel.project_id == project.id,
                    ImageModel.is_deleted.is_(False)).all()
                for im in imgs:
                    try:
                        _autolabel_image_with_model(db, im, model, project, mode="add")
                    except Exception as e:
                        print(f"[warn] autolabel image {im.id}: {e}")
                print(f"[autolabel] done for {len(imgs)} images")

        # Export
        if args.export_yolo:
            from app import export_yolo
            resp = export_yolo(project_id=project.id, naming="numbered",
                               split="none", db=db)
            print(f"[export] yolo archive: {getattr(resp, 'filename', 'ok')}")
        return 0
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(prog="db-builder",
                                description="DatasetBuilder headless CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run-pipeline",
                         help="Импорт видео/папки → авторазметка → экспорт YOLO")
    run.add_argument("--input", required=True,
                     help="Путь к видео или изображению/папке")
    run.add_argument("--project", required=True, help="Имя проекта")
    run.add_argument("--create-project", action="store_true",
                     help="Создать проект, если не существует")
    run.add_argument("--object-class", default="pig")
    run.add_argument("--fps", type=float, default=2.0,
                     help="FPS извлечения кадров (для видео)")
    run.add_argument("--autolabel", action="store_true")
    run.add_argument("--export-yolo", action="store_true")
    run.set_defaults(func=_cmd_run_pipeline)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
