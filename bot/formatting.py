"""Форматирование текста для Telegram и уведомлений."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

from .db import TelegramUser

MSK = timezone(timedelta(hours=3))


def escape(value: object) -> str:
    return html.escape(str(value), quote=False)


def format_datetime(value: datetime | str, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Показывает время в МСК независимо от того, как оно хранится."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MSK).strftime(fmt)


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


_TAG_RE = re.compile(r"<[^>]+>")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_TG_LINK_RE = re.compile(r"\b(?:t|telegram)\.me/\S+", re.IGNORECASE)
_DOMAIN_RE = re.compile(
    r"(?<![@\w.-])(?:[a-z0-9-]+\.)+(?:ru|com|net|org|io|dev|tech|cloud|site|shop|store)\b",
    re.IGNORECASE,
)
_HANDLE_RE = re.compile(r"(?<![\w@])@[A-Za-z][A-Za-z0-9_]{2,31}\b")


def to_plain_text(text: str) -> str:
    """HTML/markdown → обычный текст и полное удаление ссылок.

    Нужно для ответов на сайте: там нельзя показывать URL и разметку.
    """
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    text = text.replace("`", "")
    text = _URL_RE.sub("", text)
    text = _TG_LINK_RE.sub("", text)
    text = _DOMAIN_RE.sub("", text)
    text = _HANDLE_RE.sub("", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
