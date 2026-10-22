"""Settings service: get_setting, set_setting, get_trash_ttl_days."""
import logging
from models import Setting
from config import DEFAULT_TRASH_TTL_DAYS, SETTING_TRASH_TTL

log = logging.getLogger("db")

def get_setting(db, key, default):
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else default

def set_setting(db, key, value):
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = str(value)
    else:
        db.add(Setting(key=key, value=str(value)))
    db.commit()

def get_trash_ttl_days(db) -> int:
    try:
        return int(get_setting(db, SETTING_TRASH_TTL, DEFAULT_TRASH_TTL_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_TRASH_TTL_DAYS
