from __future__ import annotations

import asyncio

from bot.config import Settings
from bot.db import Database
from bot.rag.retriever import RagAnswer, Source
from bot.services.web_chat import WebChatService


class FakeRAG:
    def __init__(self) -> None:
        self.histories: list[list[tuple[str, str]]] = []

    @property
    def documents(self) -> int:
        return 12

    @property
    def vectors(self) -> int:
        return 3

    async def answer(self, question, history=(), *, web: bool = False) -> RagAnswer:
        assert web is True
        self.histories.append(list(history))
        return RagAnswer(
            text=("<b>PIM</b> — управление товарами. Подробнее: https://ensi.tech/solutions/pim и t.me/ensi."),
            sources=[Source(url="https://ensi.tech/solutions/pim", title="PIM")],
            used_context=True,
            degraded=False,
            top_score=0.9,
        )


def _settings(**kwargs) -> Settings:
    values = {"api_max_answer_chars": 1000}
    values.update(kwargs)
    return Settings(_env_file=None, **values)


def test_web_answer_has_no_links_and_is_logged(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "web.sqlite3")
        db.migrate()
        rag = FakeRAG()
        service = WebChatService(rag, db, _settings())

        first = await service.ask("Что такое PIM?")
        assert first.answer
        assert "PIM" in first.answer
        assert "http" not in first.answer
        assert "t.me" not in first.answer
        assert "<b>" not in first.answer
        assert first.session_id
        assert first.used_context is True
        assert db.stats()["questions"] == 1

        second = await service.ask("А подробнее?", first.session_id)
        assert second.session_id == first.session_id
        assert rag.histories[1], "история диалога не передана в RAG"

        long_session = "x" * 200
        third = await service.ask("Ещё вопрос", long_session)
        assert third.session_id != long_session
        assert len(third.session_id) <= 64

        db.close()

    asyncio.run(scenario())


class LongFakeRAG(FakeRAG):
    async def answer(self, question, history=(), *, web: bool = False) -> RagAnswer:
        return RagAnswer(
            text="Очень длинный ответ про платформу Ensi и её сервисы. " * 5,
            used_context=True,
        )


def test_web_answer_is_truncated(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "web_truncate.sqlite3")
        db.migrate()
        service = WebChatService(LongFakeRAG(), db, _settings(api_max_answer_chars=50))

        result = await service.ask("Что такое PIM?")
        assert len(result.answer) <= 51
        assert result.answer.endswith("…")

        db.close()

    asyncio.run(scenario())
