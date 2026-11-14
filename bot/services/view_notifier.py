"""Уведомление «пользователь изучает бота» с накоплением серии вопросов.

Менеджер получает сообщение, когда выполнено одно из условий:
- пользователь задал больше N_QUESTIONS вопросов (сразу), или
- с момента последнего вопроса прошло VIEW_NOTIFY_IDLE_MINUTES минут тишины.

Каждый новый вопрос сдвигает таймер. После отправки серия считается закрытой:
следующий вопрос начнёт новую.
"""

from __future__ import annotations

import asyncio
import logging

from ..config import Settings
from ..db import Database, TelegramUser, utc_now
from ..notifications import ManagerNotifier
from ..texts import (
    NOTIFY_VIEW_IDLE_TITLE,
    NOTIFY_VIEW_THRESHOLD_TITLE,
)
from .analytics import questions_summary

logger = logging.getLogger(__name__)


class ViewNotifier:
    def __init__(
        self,
        notifier: ManagerNotifier,
        db: Database,
        settings: Settings,
    ) -> None:
        self._notifier = notifier
        self._db = db
        self._settings = settings
        self._counts: dict[int, int] = {}
        self._generations: dict[int, int] = {}
        self._notified: set[int] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def idle_seconds(self) -> float:
        return max(0.0, self._settings.view_notify_idle_minutes * 60)

    async def track(self, user: TelegramUser) -> None:
        """Вызывается после каждого вопроса пользователя."""
        if not self._settings.notify_on_view:
            return

        user_id = user.id
        self._generations[user_id] = self._generations.get(user_id, 0) + 1
        generation = self._generations[user_id]

        # Предыдущая серия уже была отправлена — начинаем новую.
        if user_id in self._notified:
            self._notified.discard(user_id)
            self._counts[user_id] = 0

        count = self._counts.get(user_id, 0) + 1
        self._counts[user_id] = count

        if count > self._settings.n_questions:
            await self._flush(user, generation, reason="threshold")
            return

        task = asyncio.create_task(self._delayed_flush(user, generation))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _delayed_flush(self, user: TelegramUser, generation: int) -> None:
        try:
            await asyncio.sleep(self.idle_seconds)
        except asyncio.CancelledError:
            raise
        if self._generations.get(user.id) != generation:
            return  # пришёл новый вопрос, таймер устарел
        await self._flush(user, generation, reason="idle")

    async def _flush(self, user: TelegramUser, generation: int, *, reason: str) -> None:
        if self._generations.get(user.id) != generation:
            return
        if user.id in self._notified:
            return

        self._notified.add(user.id)
        count = self._counts.get(user.id, 0)
        self._counts[user.id] = 0

        now = utc_now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        questions = self._db.recent_questions(user.id, limit=min(max(count, 1), 5))

        if reason == "threshold":
            title = NOTIFY_VIEW_THRESHOLD_TITLE
            reason_text = f"задал(а) больше {self._settings.n_questions} вопросов"
        else:
            title = NOTIFY_VIEW_IDLE_TITLE
            minutes = self._settings.view_notify_idle_minutes
            reason_text = f"{minutes:g} мин без новых вопросов"

        self._db.log_event(user.id, "view", {"reason": reason, "count": count})

        try:
            await self._notifier.notify(
                kind="view",
                user=user,
                title=title,
                details=[
                    ("Причина", reason_text),
                    ("Вопросов в серии", str(count)),
                    ("Последние запросы", questions_summary(questions)),
                    ("Вопросов сегодня", str(self._db.questions_count(user.id, since=start_of_day))),
                ],
            )
        except Exception:
            logger.exception("Не удалось отправить уведомление о вопросах пользователя %s", user.id)

    async def shutdown(self) -> None:
        """Отменяет отложенные уведомления при остановке бота."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
