"""Аналитика поведения: уведомление о регистрации и краткий пересказ запросов."""

from __future__ import annotations

import logging

from ..config import Settings
from ..db import Database, TelegramUser
from ..notifications import ManagerNotifier
from ..texts import NOTIFY_SIGNUP_TITLE

logger = logging.getLogger(__name__)


def questions_summary(questions: list[str], limit: int = 3) -> str:
    unique: list[str] = []
    for question in questions:
        question = " ".join(question.split())
        if question and question not in unique:
            unique.append(question)
        if len(unique) >= limit:
            break
    if not unique:
        return "—"
    return "\n".join(f"• {question[:160]}" for question in unique)


async def announce_signup(
    db: Database,
    notifier: ManagerNotifier,
    settings: Settings,
    user: TelegramUser,
    source: str,
) -> None:
    if not settings.notify_on_signup:
        return
    await notifier.notify(
        kind="signup",
        user=user,
        title=NOTIFY_SIGNUP_TITLE,
        details=[
            ("Источник", source),
            ("Язык", user.language_code or "—"),
            ("Всего пользователей", str(db.stats()["users"])),
        ],
    )
