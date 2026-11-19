from __future__ import annotations

import asyncio

from bot.config import Settings
from bot.db import Database, TelegramUser
from bot.services.view_notifier import ViewNotifier


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def notify(self, **kwargs) -> int:
        self.calls.append(kwargs)
        return 1


def _settings(**kwargs) -> Settings:
    values = {
        "bot_token": "",
        "manager_chat_ids": "1",
        "admin_ids": "",
        "notify_on_view": True,
        "n_questions": 5,
        "view_notify_idle_minutes": 0.003,  # ~0.18 c
    }
    values.update(kwargs)
    return Settings(_env_file=None, **values)


def _user() -> TelegramUser:
    return TelegramUser(id=1, username="ivan", first_name="Иван")


def test_threshold_notifies_immediately_and_once(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "threshold.sqlite3")
        db.migrate()
        notifier = FakeNotifier()
        service = ViewNotifier(notifier, db, _settings(n_questions=2))
        user = _user()

        for index in range(3):
            db.log_question(user.id, f"вопрос {index}")
            await service.track(user)

        assert len(notifier.calls) == 1
        details = dict(notifier.calls[0]["details"])
        assert "больше 2" in details["Причина"]
        assert details["Вопросов в серии"] == "3"

        # Устаревшие таймеры не должны прислать дубль.
        await asyncio.sleep(0.4)
        assert len(notifier.calls) == 1

        await service.shutdown()
        db.close()

    asyncio.run(scenario())


def test_idle_notifies_after_pause_and_starts_new_burst(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "idle.sqlite3")
        db.migrate()
        notifier = FakeNotifier()
        service = ViewNotifier(notifier, db, _settings(n_questions=10))
        user = _user()

        for index in range(2):
            db.log_question(user.id, f"вопрос {index}")
            await service.track(user)

        await asyncio.sleep(0.4)
        assert len(notifier.calls) == 1
        details = dict(notifier.calls[0]["details"])
        assert "без новых вопросов" in details["Причина"]
        assert details["Вопросов в серии"] == "2"

        # Следующий вопрос открывает новую серию.
        db.log_question(user.id, "новый вопрос")
        await service.track(user)
        await asyncio.sleep(0.4)
        assert len(notifier.calls) == 2

        await service.shutdown()
        db.close()

    asyncio.run(scenario())


def test_new_question_resets_idle_timer(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "debounce.sqlite3")
        db.migrate()
        notifier = FakeNotifier()
        service = ViewNotifier(notifier, db, _settings(n_questions=10))
        user = _user()

        db.log_question(user.id, "первый")
        await service.track(user)
        await asyncio.sleep(0.08)
        assert notifier.calls == []

        db.log_question(user.id, "второй")
        await service.track(user)
        await asyncio.sleep(0.4)

        assert len(notifier.calls) == 1
        assert dict(notifier.calls[0]["details"])["Вопросов в серии"] == "2"

        await service.shutdown()
        db.close()

    asyncio.run(scenario())


def test_disabled_view_notifications_do_nothing(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "disabled.sqlite3")
        db.migrate()
        notifier = FakeNotifier()
        service = ViewNotifier(notifier, db, _settings(n_questions=0, notify_on_view=False))
        user = _user()

        db.log_question(user.id, "вопрос")
        await service.track(user)
        await asyncio.sleep(0.3)

        assert notifier.calls == []
        await service.shutdown()
        db.close()

    asyncio.run(scenario())


def test_shutdown_cancels_pending_notification(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "shutdown.sqlite3")
        db.migrate()
        notifier = FakeNotifier()
        service = ViewNotifier(notifier, db, _settings(n_questions=10, view_notify_idle_minutes=0.01))
        user = _user()

        db.log_question(user.id, "вопрос")
        await service.track(user)
        await service.shutdown()
        await asyncio.sleep(0.7)

        assert notifier.calls == []
        db.close()

    asyncio.run(scenario())
