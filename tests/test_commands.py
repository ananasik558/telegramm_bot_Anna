from __future__ import annotations

from bot.commands import ADMIN_COMMANDS, PUBLIC_COMMANDS, STAFF_COMMANDS, staff_commands_for
from bot.config import Settings


def _settings(**kwargs) -> Settings:
    values = {"manager_chat_ids": "", "admin_ids": ""}
    values.update(kwargs)
    return Settings(_env_file=None, **values)


def _names(commands) -> set[str]:
    return {command.command for command in commands}


def test_public_menu_has_no_staff_commands() -> None:
    names = _names(PUBLIC_COMMANDS)
    assert names == {"start", "audit", "help", "reset"}
    assert "history" not in names
    assert "stats" not in names
    assert "id" not in names


def test_manager_gets_staff_menu_without_admin_commands() -> None:
    settings = _settings(manager_chat_ids="111")
    commands = staff_commands_for(111, settings)
    assert commands is STAFF_COMMANDS
    assert {"history", "id"} <= _names(commands)
    assert "stats" not in _names(commands)
    assert "users" not in _names(commands)
    assert "test_notify" not in _names(commands)


def test_admin_gets_full_menu() -> None:
    settings = _settings(admin_ids="999")
    commands = staff_commands_for(999, settings)
    assert commands is ADMIN_COMMANDS
    assert {"history", "id", "stats", "users", "leads", "knowledge", "test_notify"} <= _names(commands)


def test_admin_menu_wins_over_manager() -> None:
    settings = _settings(manager_chat_ids="111", admin_ids="111")
    assert staff_commands_for(111, settings) is ADMIN_COMMANDS


def test_regular_user_has_no_staff_menu() -> None:
    settings = _settings(manager_chat_ids="111")
    assert staff_commands_for(222, settings) is None
    assert staff_commands_for(111, _settings()) is None
