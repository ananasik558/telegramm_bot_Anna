"""Уведомления менеджерам.

Здесь ничего не захардкожено: список получателей берётся из MANAGER_CHAT_IDS
(и опционально MANAGER_TOPIC_ID). Пока список пустой, все события пишутся в
таблицу events — ничего не теряется.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from .config import Settings
from .db import Database, TelegramUser
from .formatting import MSK, escape, format_user, shorten
from .texts import NOTIFY_NO_MANAGERS

logger = logging.getLogger(__name__)

MAX_VALUE_CHARS = 700


def _now_label() -> str:
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M MSK")


class ManagerNotifier:
    def __init__(self, bot: Bot, settings: Settings, db: Database) -> None:
        self._bot = bot
        self._settings = settings
        self._db = db
        self._warned_empty = False

    @property
    def chat_ids(self) -> list[int]:
        return self._settings.managers

    async def notify(
        self,
        *,
        kind: str,
        user: TelegramUser | None,
        title: str,
        details: Sequence[tuple[str, str]] = (),
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> int:
        """Отправляет уведомление всем менеджерам. Возвращает число доставок."""
        chat_ids = self.chat_ids
        if not chat_ids:
            if not self._warned_empty:
                logger.warning(NOTIFY_NO_MANAGERS)
                self._warned_empty = True
            self._db.log_event(
                user.id if user else None,
                "notify_skipped",
                {"kind": kind, "reason": "MANAGER_CHAT_IDS пуст", "title": title},
            )
            return 0

        text = self._render(title=title, user=user, details=details)
        if reply_markup is None:
            reply_markup = self._default_keyboard(user)

        sent = 0
        for chat_id in chat_ids:
            try:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    message_thread_id=self._settings.manager_topic_id,
                    reply_markup=reply_markup,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
                sent += 1
            except TelegramAPIError as error:
                logger.warning("Не удалось отправить уведомление в %s: %s", chat_id, error)
                self._db.log_event(
                    user.id if user else None,
                    "notify_failed",
                    {"kind": kind, "chat_id": chat_id, "error": str(error)[:300]},
                )
        return sent

    async def send_text(self, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> bool:
        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                message_thread_id=self._settings.manager_topic_id,
                reply_markup=reply_markup,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            return True
        except TelegramAPIError as error:
            logger.warning("Не удалось отправить сообщение в %s: %s", chat_id, error)
            return False

    def _default_keyboard(self, user: TelegramUser | None) -> InlineKeyboardMarkup | None:
        """Кнопки под уведомлением: написать пользователю и открыть его историю."""
        if user is None:
            return None
        row: list[InlineKeyboardButton] = []
        if user.username:
            row.append(InlineKeyboardButton(text="✍️ Написать", url=f"https://t.me/{user.username}"))
        row.append(InlineKeyboardButton(text="📜 История запросов", callback_data=f"hist:{user.id}:0"))
        return InlineKeyboardMarkup(inline_keyboard=[row])

    def _render(
        self,
        *,
        title: str,
        user: TelegramUser | None,
        details: Sequence[tuple[str, str]],
    ) -> str:
        lines: list[str] = [f"<b>{escape(title)}</b>", ""]
        if user is not None:
            lines.append(f"👤 <b>Кто:</b> {format_user(user)}")
        for label, value in details:
            if value is None or str(value).strip() == "":
                continue
            lines.append(f"{escape(label)}: {escape(shorten(str(value), MAX_VALUE_CHARS))}")
        lines.append("")
        lines.append(f"🕒 {_now_label()}")
        return "\n".join(lines)
