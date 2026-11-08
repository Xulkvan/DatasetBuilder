"""routers/settings.py — Stage 3.11 (moved from app.py)."""
from fastapi import APIRouter, Depends, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.settings_service import get_trash_ttl_days, set_setting
from services.ml_service import _is_single_model_mode
from config import SETTING_TRASH_TTL, SETTING_USE_SINGLE_MODEL
from logger import log_status

router = APIRouter()


@router.get("/api/settings/trash_ttl")
def get_trash_ttl(db: Session = Depends(get_db)):
    return {"days": get_trash_ttl_days(db)}


class ModelModeIn(BaseModel):
    use_single: bool = True


@router.get("/api/settings/model_mode")
def get_model_mode(db: Session = Depends(get_db)):
    return {"use_single": _is_single_model_mode(db)}


@router.post("/api/settings/model_mode")
def set_model_mode(payload: ModelModeIn, db: Session = Depends(get_db)):
    set_setting(db, SETTING_USE_SINGLE_MODEL,
                "1" if payload.use_single else "0")
    log_status("info", "settings",
               f"Режим моделей: {'одна' if payload.use_single else 'раздельные'}")
    return {"use_single": payload.use_single}


@router.post("/api/settings/trash_ttl")
def update_trash_ttl(days: int = Form(...), db: Session = Depends(get_db)):
    days = max(0, min(3650, int(days)))
    set_setting(db, SETTING_TRASH_TTL, days)
    log_status("info", "settings", f"Корзина: автоочистка через {days} дн.")
    return {"days": days}
