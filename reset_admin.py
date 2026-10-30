# [PATCH:RESET-ADMIN-UTC]
# [PATCH:FIX-setup-cli]
# [PATCH:FIX-setup-cli] Ручное создание/сброс админа.
# Использование:
#   python -m security.reset_admin admin MyPass123
#   python -m security.reset_admin --list
#
# Полезно, если UI Setup Wizard не сработал (старая БД, нет users).

import sys
from datetime import datetime


def _hash(pw: str) -> str:  # [PATCH:STAGE2-ARGON2-ONLY]
    try:
        from argon2 import PasswordHasher
    except ImportError:
        print("ERROR: argon2-cffi not installed. Install: pip install argon2-cffi",
              file=sys.stderr)
        raise SystemExit(2)
    return PasswordHasher().hash(pw)


def main(argv: list[str]) -> int:
    from database import SessionLocal
    from models import User
    from sqlalchemy import func

    db = SessionLocal()
    try:
        if len(argv) == 1 and argv[0] in ("--list", "-l"):
            rows = db.query(User).order_by(User.id).all()
            if not rows:
                print("Нет пользователей.")
                return 0
            for u in rows:
                print(f"  id={u.id}  {u.username:24s}  role={u.role}  "
                      f"active={u.is_active}")
            return 0

        if len(argv) != 2:
            print("usage: python -m security.reset_admin <username> <password>",
                  file=sys.stderr)
            print("       python -m security.reset_admin --list",
                  file=sys.stderr)
            return 2

        username, password = argv
        if len(username) < 3:
            print("username >= 3", file=sys.stderr); return 2
        if len(password) < 8:
            print("password >= 8", file=sys.stderr); return 2

        existing = db.query(User).filter(User.username == username).first()
        ph = _hash(password)
        if existing:
            existing.password_hash = ph
            existing.role = "admin"
            existing.is_active = 1
            db.commit()
            print(f"✓ Обновлён: {username} (role=admin)")
        else:
            u = User(username=username, password_hash=ph,
                     role="admin", is_active=1,
                     created_at=datetime.now())
            db.add(u); db.commit(); db.refresh(u)
            print(f"✓ Создан: {username} (id={u.id}, role=admin)")

        n = int(db.query(func.count(User.id)).scalar() or 0)
        print(f"  Пользователей в БД: {n}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
