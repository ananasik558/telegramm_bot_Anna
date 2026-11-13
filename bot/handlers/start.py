"""Команды /start, /help, /reset, /id."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..config import Settings
from ..db import Database, TelegramUser
from ..dialogue import DialogueHistory
from ..formatting import escape
from ..keyboards import main_menu
from ..notifications import ManagerNotifier
from ..services.analytics import announce_signup
from ..texts import HELP_TEXT, RESET_DONE, START_TEXT
from .audit import begin_audit

logger = logging.getLogger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    notifier: ManagerNotifier,
) -> None:
    await state.clear()
    user = TelegramUser.from_aiogram(message.from_user)
    is_new = db.upsert_user(user)

    payload = (message.text or "").partition(" ")[2].strip()
    db.log_event(user.id, "signup" if is_new else "start", {"payload": payload or None})
    if is_new:
        await announce_signup(db, notifier, settings, user, source=payload or "прямой вход")

    await message.answer(
        START_TEXT.format(name=escape(user.first_name or "друг")),
        reply_markup=main_menu(settings.site_base_url),
    )

    if payload.lower().startswith("audit"):
        await begin_audit(message, state)


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu(settings.site_base_url))


@router.message(Command("reset"))
async def cmd_reset(message: Message, history: DialogueHistory, settings: Settings) -> None:
    history.clear(message.from_user.id)  # type: ignore[union-attr]
    await message.answer(RESET_DONE, reply_markup=main_menu(settings.site_base_url))


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    user = message.from_user
    await message.answer(
        "🆔 <b>Ваши ID для настроек</b>\n\n"
        f"Telegram ID: <code>{user.id}</code>\n"  # type: ignore[union-attr]
        f"ID этого чата: <code>{message.chat.id}</code>\n\n"
        "Менеджеру достаточно отправить это число администратору бота, "
        "чтобы получать уведомления."
    )
