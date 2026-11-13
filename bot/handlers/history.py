"""История запросов пользователя для менеджеров.

Доступна двумя способами:
- кнопка «📜 История запросов» под уведомлением;
- команда /history <id|@username>.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message

from ..config import Settings
from ..db import Database, TelegramUser, utc_now
from ..formatting import escape, format_datetime, format_user, shorten
from ..services.access import is_staff
from ..texts import (
    HISTORY_EMPTY,
    HISTORY_NOT_FOUND,
    HISTORY_TITLE,
    HISTORY_USAGE,
    STAFF_ONLY,
)

logger = logging.getLogger(__name__)
router = Router(name="history")

PAGE_SIZE = 10
MAX_QUESTION_CHARS = 220


def _known_message(message: Message | None) -> int | None:
    return message.chat.id if message is not None else None


def _user_from_row(row: dict) -> TelegramUser:
    return TelegramUser(
        id=int(row["id"]),
        username=row.get("username"),
        first_name=row.get("first_name"),
        last_name=row.get("last_name"),
        language_code=row.get("language_code"),
    )


def _render_history(
    db: Database,
    user_row: dict,
    offset: int,
) -> tuple[str, InlineKeyboardMarkup | None]:
    user = _user_from_row(user_row)
    offset = max(0, offset)
    total = db.questions_count(user.id)
    if total and offset >= total:
        offset = ((total - 1) // PAGE_SIZE) * PAGE_SIZE
    today = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    questions_today = db.questions_count(user.id, since=today)
    items = db.question_history(user.id, limit=PAGE_SIZE, offset=offset)
    leads_total = db.leads_count(user_id=user.id)
    last_leads = db.list_leads(limit=1, user_id=user.id)

    lines: list[str] = [
        f"<b>{HISTORY_TITLE}</b>",
        "",
        format_user(user),
        f"Первый визит: {format_datetime(user_row['created_at'])}",
        f"Последняя активность: {format_datetime(user_row['last_seen_at'])}",
        f"Вопросов: <b>{total}</b> (сегодня {questions_today})",
    ]
    if leads_total and last_leads:
        lead = last_leads[0]
        lines.append(
            f"Заявок: <b>{leads_total}</b> "
            f"(последняя #{lead['id']} · {escape(lead['status'])} · "
            f"{format_datetime(lead['created_at'], '%d.%m.%y')})"
        )

    lines.append("")
    if not items:
        lines.append(HISTORY_EMPTY)
    else:
        lines.append("<b>Последние запросы</b>")
        for index, item in enumerate(items, start=offset + 1):
            stamp = format_datetime(item["created_at"], "%d.%m %H:%M")
            question = escape(shorten(item["question"], MAX_QUESTION_CHARS))
            lines.append(f"{index}. <code>{stamp}</code> — {question}")

    if total > PAGE_SIZE:
        first = offset + 1
        last = offset + len(items)
        lines.append("")
        lines.append(f"<i>Строки {first}–{last} из {total}</i>")

    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"hist:{user.id}:{max(0, offset - PAGE_SIZE)}",
            )
        )
    if offset + PAGE_SIZE < total:
        nav.append(
            InlineKeyboardButton(
                text="Вперёд ▶️",
                callback_data=f"hist:{user.id}:{offset + PAGE_SIZE}",
            )
        )
    if nav:
        rows.append(nav)
    if user.username:
        rows.append([InlineKeyboardButton(text="✍️ Написать", url=f"https://t.me/{user.username}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    return "\n".join(lines), keyboard


@router.message(Command("history"))
async def cmd_history(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
) -> None:
    if not is_staff(
        user_id=message.from_user.id if message.from_user else None,
        chat_id=message.chat.id,
        settings=settings,
    ):
        await message.answer(STAFF_ONLY)
        return

    raw = (command.args or "").strip()
    if not raw:
        await message.answer(HISTORY_USAGE)
        return

    token = raw.split()[0]
    if token.startswith("@"):
        user_id = db.find_user_by_username(token)
        if user_id is None:
            await message.answer(HISTORY_NOT_FOUND)
            return
    else:
        try:
            user_id = int(token)
        except ValueError:
            await message.answer(HISTORY_USAGE)
            return

    user_row = db.get_user(user_id)
    if user_row is None:
        await message.answer(HISTORY_NOT_FOUND)
        return

    text, keyboard = _render_history(db, user_row, offset=0)
    await message.answer(
        text,
        reply_markup=keyboard,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.callback_query(F.data.startswith("hist:"))
async def cb_history(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
) -> None:
    if not is_staff(
        user_id=callback.from_user.id,
        chat_id=_known_message(callback.message),
        settings=settings,
    ):
        await callback.answer(STAFF_ONLY, show_alert=True)
        return

    parts = (callback.data or "").split(":")
    try:
        user_id = int(parts[1])
        offset = max(0, int(parts[2])) if len(parts) > 2 else 0
    except (IndexError, ValueError):
        await callback.answer("Некорректная ссылка", show_alert=True)
        return

    user_row = db.get_user(user_id)
    if user_row is None:
        await callback.answer(HISTORY_NOT_FOUND, show_alert=True)
        return

    text, keyboard = _render_history(db, user_row, offset=offset)
    if callback.message is not None:
        try:
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except TelegramBadRequest:
            # Например, нажали «Вперёд» на уже удалённом сообщении.
            logger.debug("Не удалось обновить историю запросов", exc_info=True)
    await callback.answer()
