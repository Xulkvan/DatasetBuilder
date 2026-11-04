"""[STAGE0-1-artifacts] Артефакты сборки: requirements.lock + Dockerfile."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_requirements_lock_exists():
    """requirements.lock отсутствует → Docker build упадёт."""
    path = ROOT / "requirements.lock"
    assert path.is_file(), (
        f"requirements.lock отсутствует в {ROOT} — Docker build упадёт.\n"
        "Сгенерируйте: pip freeze > requirements.lock"
    )
    assert path.stat().st_size > 0, "requirements.lock пуст"


def test_requirements_lock_contains_core_deps():
    """Lock должен содержать хотя бы ключевые пакеты."""
    content = (ROOT / "requirements.lock").read_text(encoding="utf-8").lower()
    for pkg in ("fastapi", "uvicorn", "sqlalchemy", "pillow", "pydantic"):
        assert pkg in content, f"{pkg} отсутствует в requirements.lock"


def test_dockerfile_references_lock():
    """Dockerfile должен устанавливать зависимости из lock."""
    src = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "requirements.lock" in src, (
        "Dockerfile не ссылается на requirements.lock"
    )


def test_dockerignore_allows_lock():
    """.dockerignore не должен исключать requirements.lock."""
    path = ROOT / ".dockerignore"
    if not path.exists():
        return
    lines = [
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert "!requirements.lock" in lines or "requirements.lock" not in lines, (
        ".dockerignore исключает requirements.lock"
    )
