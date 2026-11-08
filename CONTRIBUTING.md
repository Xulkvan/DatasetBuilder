# Contributing

## Setup

~~~bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
~~~

## Adding a new route

1. Создайте роутер в `routers/<feature>.py` (`APIRouter(tags=["<feature>"])`).
2. Бизнес-логику — в `services/<feature>_service.py`.
3. Зарегистрируйте роутер в `app.py` (`app.include_router(...)`).
4. **Обязательно** добавьте RBAC-правило в `services/route_permissions.py::_RULES`:

   ~~~python
   _RULES.append(("POST", "/api/<feature>/{id}/do", "annotation.write"))
   ~~~

   С 5.2 (fail-closed) роут без правила → 403 для всех.
5. Проверьте whitelist (`_PUBLIC_API_PREFIXES`, `_PUBLIC_API_EXACT`) —
   если роут публичный, добавьте туда с явным комментарием.
6. Тесты — в `tests/test_<feature>.py` (TestClient).

## Testing

- `pytest -q`
- `pytest -q -m "not slow and not ml"`
- `pytest --cov=app --cov=services --cov=routers`

## Code style

- `ruff check .` (обязательно перед PR)
- `mypy .` (baseline — не ухудшать)
- Без `print()` — используйте `logging.getLogger("db")`.
- Все новые UI-строки — в `i18n.js` (ru + en).
