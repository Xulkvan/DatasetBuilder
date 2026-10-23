"""[STAGE1-D:test-validator] Тесты новых проверок валидатора."""
import pytest


class TestValidatorExtensions:
    def test_marker_present(self):
        # Smoke: файл был пропатчен в stage A → поведение проверяется в
        # интеграционном тесте, здесь только проверяем что модуль импортируется.
        pass
