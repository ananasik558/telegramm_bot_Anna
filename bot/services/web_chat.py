"""Чат на сайте: ответы RAG без Telegram, ссылок и разметки."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass

from ..config import Settings
from ..db import Database
from ..dialogue import DialogueHistory
from ..formatting import to_plain_text
from ..rag.retriever import RAGService
from ..texts import WEB_FALLBACK_NO_CONTEXT

logger = logging.getLogger(__name__)

_SESSION_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@dataclass(frozen=True, slots=True)
class WebAnswer:
    answer: str
    session_id: str
    degraded: bool = False
    used_context: bool = False


def web_user_id(session_id: str) -> int:
    """Стабильный отрицательный ID для логов (не пересекается с Telegram)."""
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
    return -(int(digest, 16) or 1)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—")
    return f"{cut}…"


class WebChatService:
    def __init__(self, rag: RAGService, db: Database, settings: Settings) -> None:
        self._rag = rag
        self._db = db
        self._settings = settings
        self._history = DialogueHistory(settings.history_turns)

    @property
    def documents(self) -> int:
        return self._rag.documents

    @property
    def vectors(self) -> int:
        return self._rag.vectors

    @property
    def llm_enabled(self) -> bool:
        return self._settings.llm_enabled

    @staticmethod
    def _clean_session(raw: object) -> str | None:
        if isinstance(raw, str):
            candidate = raw.strip()
            if _SESSION_RE.fullmatch(candidate):
                return candidate
        return None

    async def ask(self, question: str, session_id: str | None = None) -> WebAnswer:
        question = " ".join(question.split())
        sid = self._clean_session(session_id) or secrets.token_hex(8)

        degraded = False
        used_context = False
        top_score = 0.0
        try:
            result = await self._rag.answer(question, self._history.get(sid), web=True)
            text = to_plain_text(result.text)
            degraded = result.degraded
            used_context = result.used_context
            top_score = result.top_score
        except Exception:
            logger.exception("Ошибка RAG в чате на сайте")
            text = WEB_FALLBACK_NO_CONTEXT
            degraded = True

        if not text.strip():
            text = WEB_FALLBACK_NO_CONTEXT
        text = _truncate(text.strip(), self._settings.api_max_answer_chars)

        self._history.add(sid, question, text)
        user_id = web_user_id(sid)
        self._db.log_question(user_id, question, text, [], top_score)
        self._db.log_event(user_id, "web_question", {"session_id": sid})

        return WebAnswer(
            answer=text,
            session_id=sid,
            degraded=degraded,
            used_context=used_context,
        )
