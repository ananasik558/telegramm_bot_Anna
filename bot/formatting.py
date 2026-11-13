"""Форматирование текста для Telegram и уведомлений."""

from __future__ import annotations

import html
import re

from .db import TelegramUser


def escape(value: object) -> str:
    return html.escape(str(value), quote=False)


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def to_telegram_html(text: str) -> str:
    """Аккуратно переносит простой markdown от LLM в HTML Telegram.

    Сначала экранируем HTML, потом включаем только безопасные теги.
    """
    escaped = html.escape(text.strip(), quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped, flags=re.S)
    escaped = re.sub(r"(?m)^\s*#{1,6}\s*(.+?)\s*$", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?m)^\s*[-*•]\s+", "• ", escaped)
    escaped = escaped.replace("`", "")
    return escaped.strip()


def format_user(user: TelegramUser | None) -> str:
    if user is None:
        return "—"
    parts = [f"<b>{escape(user.full_name)}</b>"]
    if user.username:
        parts.append(f"@{escape(user.username)}")
    else:
        parts.append("без username")
    parts.append(f"id <code>{user.id}</code>")
    return " · ".join(parts)
