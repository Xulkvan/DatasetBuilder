# [PATCH:STAGE7-postgres]
import os
import sys
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import event as _sa_event

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

log = logging.getLogger("db")

DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").strip().lower()
if DB_ENGINE not in ("mysql", "sqlite", "postgres"):
    log.warning("DB_ENGINE=%r неизвестен, использую 'sqlite' для стабильности", DB_ENGINE)
    DB_ENGINE = "sqlite"

DATA_DIR = os.path.join(os.getenv("DATA_ROOT", "."), "data")

# Переменные вынесены наверх, чтобы app.py мог их импортировать при любом движке
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "root")
DB_HOST = os.getenv("DB_HOST", "localhost")
_default_port = {"mysql": "3306", "postgres": "5432"}.get(DB_ENGINE, "3306")
DB_PORT = os.getenv("DB_PORT", _default_port)
DB_NAME = os.getenv("DB_NAME", "pig_dataset")

if DB_ENGINE == "sqlite":
    DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "dataset.db"))
    DB_PATH = os.path.abspath(DB_PATH)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    DATABASE_URL = f"sqlite:///{DB_PATH}"

    # [STAGE6:staticpool] StaticPool для :memory: — иначе разные
    # соединения видят разные БД (тесты flaky).
    _is_mem = (":memory:" in DATABASE_URL) or DATABASE_URL in ("sqlite://", "sqlite:///")
    if _is_mem:
        from sqlalchemy.pool import StaticPool
        engine = create_engine(
            DATABASE_URL,
            echo=False,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(
            DATABASE_URL,
            echo=False,
            connect_args={"check_same_thread": False, "timeout": 30.0},
            pool_pre_ping=True,
        )


    @_sa_event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):
        try:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA cache_size=-20000")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()
        except Exception:
            log.exception("sqlite pragma setup failed")


    log.info("Хранилище: SQLite — %s", DB_PATH)

elif DB_ENGINE == "postgres":
    DATABASE_URL = (
        f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    try:
        engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True,
                               pool_size=10, max_overflow=20)
        with engine.connect() as conn:
            pass
        log.info("Хранилище: PostgreSQL — %s:%s/%s", DB_HOST, DB_PORT, DB_NAME)
    except Exception as e:
        log.error("=" * 70)
        log.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось подключиться к PostgreSQL!")
        log.error("Причина: %s", str(e).split('\n')[0])
        log.error("Проверьте DB_HOST/DB_PORT/DB_USER/DB_PASSWORD в .env")
        log.error("=" * 70)
        raise RuntimeError("PostgreSQL connection failed.") from e
else:
    DATABASE_URL = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        f"?charset=utf8mb4"
    )

    # Сначала проверяем пароль на безопасность (как было в оригинале)
    if DB_PASSWORD == "root":
        if getattr(sys, 'frozen', False):
            raise RuntimeError(
                "FATAL SECURITY: Default MySQL password 'root' is forbidden in production. "
                "Please set DB_PASSWORD in your .env file."
            )
        log.warning("Используется пароль MySQL по умолчанию 'root'. "
                    "Задай DB_PASSWORD через переменную окружения или .env.")

    # ТЕПЕРЬ ЛОВИМ ОШИБКУ ПОДКЛЮЧЕНИЯ ЗДЕСЬ
    try:
        engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True,
                               pool_size=10, max_overflow=20)

        # Принудительно делаем тестовый коннект. Если пароль неверный - упадем ЗДЕСЬ
        with engine.connect() as conn:
            pass

        log.info("Хранилище: MySQL — %s:%s/%s", DB_HOST, DB_PORT, DB_NAME)
    except Exception as e:
        log.error("=" * 70)
        log.error("КРИТИЧЕСКАЯ ОШИБКА: Не удалось подключиться к MySQL!")
        log.error("Причина: %s", str(e).split('\n')[0])
        log.error("Проверьте настройки в файле .env (DB_USER, DB_PASSWORD).")
        log.error("Если вы хотите работать без MySQL (локально), измените в .env:")
        log.error("  DB_ENGINE=sqlite")
        log.error("=" * 70)
        # Прерываем запуск, чтобы не сыпать ошибками дальше
        raise RuntimeError("Database connection failed. Please check your .env file.") from e

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
