from __future__ import annotations

from bot.config import Settings
from bot.services.access import is_staff


def _settings(**kwargs) -> Settings:
    values = {"manager_chat_ids": "", "admin_ids": ""}
    values.update(kwargs)
    return Settings(**values)


def test_empty_lists_deny_everyone() -> None:
    settings = _settings()
    assert is_staff(user_id=1, chat_id=1, settings=settings) is False


def test_manager_by_personal_id() -> None:
    settings = _settings(manager_chat_ids="111,222")
    assert is_staff(user_id=111, chat_id=111, settings=settings) is True
    assert is_staff(user_id=333, chat_id=333, settings=settings) is False


def test_admin_has_access() -> None:
    settings = _settings(admin_ids="999")
    assert is_staff(user_id=999, chat_id=999, settings=settings) is True


def test_manager_group_chat_has_access() -> None:
    settings = _settings(manager_chat_ids="-1001234567890")
    assert is_staff(user_id=42, chat_id=-1001234567890, settings=settings) is True
    assert is_staff(user_id=42, chat_id=42, settings=settings) is False
