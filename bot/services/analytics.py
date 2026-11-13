"""Аналитика поведения: уведомления о заходе и краткий пересказ запросов."""

from __future__ import annotations

import logging
from datetime import timedelta

from ..config import Settings
from ..db import Database, TelegramUser, utc_now
from ..notifications import ManagerNotifier
from ..texts import NOTIFY_SIGNUP_TITLE, NOTIFY_VIEW_TITLE

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


async def maybe_notify_view(
    db: Database,
    notifier: ManagerNotifier,
    settings: Settings,
    user: TelegramUser,
    question: str,
) -> None:
    """Пишет менеджерам, что человек задал вопрос, но не чаще cooldown-а."""
    if not settings.notify_on_view:
        return

    now = utc_now()
    last = db.last_event_at(user.id, "view")
    cooldown = timedelta(hours=settings.view_notify_cooldown_hours)
    if last is not None and now - last < cooldown:
        return

    db.log_event(user.id, "view", {"question": question})
    recent = db.recent_questions(user.id, 5)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    await notifier.notify(
        kind="view",
        user=user,
        title=NOTIFY_VIEW_TITLE,
        details=[
            ("Сейчас спрашивает", question),
            ("Последние запросы", questions_summary(recent)),
            ("Вопросов сегодня", str(db.questions_count(user.id, since=start_of_day))),
        ],
    )
