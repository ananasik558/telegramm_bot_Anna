"""Меню команд бота, разное для пользователей, менеджеров и админов.

Telegram не умеет выдавать меню «списку ID», но умеет задавать команды
для конкретного чата: BotCommandScopeChat. Поэтому менеджерам и админам
меню ставится персонально, а всем остальным остаётся публичный список.
"""

from __future__ import annotations

import json
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat

from .config import Settings
from .db import Database

logger = logging.getLogger(__name__)

SCOPES_KEY = "staff_command_scopes_v1"

PUBLIC_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Начать"),
    BotCommand(command="audit", description="Экспресс-аудит — бесплатно"),
    BotCommand(command="help", description="Как пользоваться ботом"),
    BotCommand(command="reset", description="Очистить историю диалога"),
]

# Менеджерам: публичное + работа с клиентами.
STAFF_COMMANDS: list[BotCommand] = [
    *PUBLIC_COMMANDS,
    BotCommand(command="history", description="История запросов пользователя"),
    BotCommand(command="id", description="Мой Telegram ID для настроек"),
]

# Админам: всё, включая служебные команды.
ADMIN_COMMANDS: list[BotCommand] = [
    *STAFF_COMMANDS,
    BotCommand(command="stats", description="Статистика бота"),
    BotCommand(command="leads", description="Последние заявки"),
    BotCommand(command="knowledge", description="Состояние базы знаний"),
    BotCommand(command="test_notify", description="Проверить уведомления"),
]


def staff_commands_for(chat_id: int, settings: Settings) -> list[BotCommand] | None:
    """Возвращает набор команд для чата или None, если это обычный пользователь."""
    if chat_id in set(settings.admins):
        return ADMIN_COMMANDS
    if chat_id in set(settings.managers):
        return STAFF_COMMANDS
    return None


async def apply_command_scopes(bot: Bot, settings: Settings, db: Database) -> dict[str, int]:
    """Ставит публичное меню всем, а персональные — менеджерам и админам.

    Для чатов, где бот ещё не был запущен, Telegram вернёт ошибку — это
    нормально: меню применится, когда человек нажмёт /start (см. handlers/start.py).
    """
    await bot.set_my_commands(PUBLIC_COMMANDS)

    targets: dict[int, list[BotCommand]] = {}
    for chat_id in settings.managers:
        targets[chat_id] = STAFF_COMMANDS
    for chat_id in settings.admins:
        targets[chat_id] = ADMIN_COMMANDS

    applied = 0
    for chat_id, commands in targets.items():
        try:
            await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
            applied += 1
        except TelegramAPIError as error:
            logger.info("Меню для чата %s отложено до /start: %s", chat_id, error)

    # Убираем персональное меню у тех, кого удалили из .env.
    previous: set[int] = set()
    raw = db.get_setting(SCOPES_KEY)
    if raw:
        try:
            previous = {int(item) for item in json.loads(raw)}
        except (ValueError, TypeError):
            previous = set()

    removed = 0
    for chat_id in previous - set(targets):
        try:
            await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
            removed += 1
        except TelegramAPIError as error:
            logger.debug("Не удалось сбросить меню для %s: %s", chat_id, error)

    db.set_setting(SCOPES_KEY, json.dumps(sorted(targets)))
    return {"applied": applied, "expected": len(targets), "removed": removed}
