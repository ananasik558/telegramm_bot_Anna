"""RAG-сервис: поиск по базе знаний + генерация ответа."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from ..config import Settings
from ..db import Database
from ..formatting import escape, shorten, to_plain_text, to_telegram_html
from ..llm import EmbeddingClient, LLMClient, LLMError
from ..prompts import (
    ANSWER_INSTRUCTIONS,
    NO_CONTEXT_INSTRUCTIONS,
    SYSTEM_PROMPT,
    WEB_ANSWER_INSTRUCTIONS,
    WEB_NO_CONTEXT_INSTRUCTIONS,
    WEB_SYSTEM_PROMPT,
)
from ..texts import FALLBACK_NO_CONTEXT, LLM_DISABLED_NOTE, LLM_ERROR_NOTE, WEB_FALLBACK_NO_CONTEXT
from .store import Hit, KnowledgeDoc, SearchIndex

logger = logging.getLogger(__name__)

MAX_ANSWER_CHARS = 3500
MAX_SOURCE_BUTTON_TITLE = 48


@dataclass(slots=True)
class Source:
    url: str
    title: str


@dataclass(slots=True)
class RagAnswer:
    text: str
    sources: list[Source] = field(default_factory=list)
    used_context: bool = False
    degraded: bool = False
    top_score: float = 0.0


class RAGService:
    def __init__(
        self,
        db: Database,
        llm: LLMClient,
        embedder: EmbeddingClient,
        settings: Settings,
    ) -> None:
        self._db = db
        self._llm = llm
        self._embedder = embedder
        self._settings = settings
        self._index = SearchIndex([])

    @property
    def ready(self) -> bool:
        return len(self._index) > 0

    @property
    def documents(self) -> int:
        return len(self._index)

    @property
    def vectors(self) -> int:
        return self._index.vector_count

    def load(self) -> None:
        rows = self._db.fetch_chunks(self._settings.embedding_model)
        docs = [
            KnowledgeDoc(id=row.id, url=row.url, title=row.title, text=row.text, vector=row.embedding) for row in rows
        ]
        self._index = SearchIndex(docs)
        logger.info(
            "RAG: загружено %s чанков, из них с векторами %s",
            len(self._index),
            self._index.vector_count,
        )

    async def answer(
        self,
        question: str,
        history: Sequence[tuple[str, str]] = (),
        *,
        web: bool = False,
    ) -> RagAnswer:
        """web=True — ответ для чата на сайте: обычный текст без ссылок и разметки."""
        question = question.strip()
        hits = await self._search(question)

        if not hits:
            return await self._answer_without_context(question, web=web)

        sources = self._sources(hits)
        if not self._llm.enabled:
            return RagAnswer(
                text=self._extractive_answer(hits, web=web) + ("" if web else LLM_DISABLED_NOTE),
                sources=sources,
                used_context=True,
                degraded=True,
            )

        system_prompt = WEB_SYSTEM_PROMPT if web else SYSTEM_PROMPT
        instructions = WEB_ANSWER_INSTRUCTIONS if web else ANSWER_INSTRUCTIONS
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for role, text in history:
            messages.append({"role": role, "content": text})
        messages.append(
            {
                "role": "user",
                "content": instructions.format(
                    context=self._format_context(hits, include_urls=not web),
                    question=question,
                ),
            }
        )

        try:
            raw = await self._llm.chat(messages)
            text = to_plain_text(raw) if web else to_telegram_html(raw)
            if len(text) > MAX_ANSWER_CHARS:
                text = self._truncate(text, MAX_ANSWER_CHARS)
            return RagAnswer(
                text=text,
                sources=sources,
                used_context=True,
                top_score=hits[0].score,
            )
        except LLMError as error:
            logger.warning("LLM недоступна, отдаю выдержки: %s", error)
            note = "" if web else LLM_ERROR_NOTE
            return RagAnswer(
                text=self._extractive_answer(hits, web=web) + note,
                sources=sources,
                used_context=True,
                degraded=True,
                top_score=hits[0].score,
            )

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—")
        return f"{cut}…"

    async def _search(self, question: str) -> list[Hit]:
        if not self.ready:
            return []
        query_vector = None
        if self._embedder.enabled and self._index.vector_count:
            try:
                query_vector = await self._embedder.embed_one(question)
            except LLMError as error:
                logger.warning("Эмбеддинг запроса не удался: %s", error)
        return self._index.search(
            question,
            query_vector=query_vector,
            top_k=self._settings.rag_top_k,
            min_score=self._settings.rag_min_score,
        )

    async def _answer_without_context(self, question: str, *, web: bool = False) -> RagAnswer:
        if not self._llm.enabled:
            return RagAnswer(
                text=WEB_FALLBACK_NO_CONTEXT if web else FALLBACK_NO_CONTEXT,
                used_context=False,
            )
        system_prompt = WEB_SYSTEM_PROMPT if web else SYSTEM_PROMPT
        instructions = WEB_NO_CONTEXT_INSTRUCTIONS if web else NO_CONTEXT_INSTRUCTIONS
        try:
            raw = await self._llm.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": instructions.format(question=question)},
                ]
            )
            text = to_plain_text(raw) if web else to_telegram_html(raw)
            if len(text) > MAX_ANSWER_CHARS:
                text = self._truncate(text, MAX_ANSWER_CHARS)
            return RagAnswer(text=text, used_context=False)
        except LLMError as error:
            logger.warning("LLM недоступна: %s", error)
            fallback = WEB_FALLBACK_NO_CONTEXT if web else FALLBACK_NO_CONTEXT
            return RagAnswer(text=fallback, used_context=False, degraded=True)

    def _format_context(self, hits: Sequence[Hit], *, include_urls: bool = True) -> str:
        blocks: list[str] = []
        for index, hit in enumerate(hits, start=1):
            text = shorten(hit.doc.text, 1800)
            header = f"[{index}] {hit.doc.title}"
            if include_urls:
                header = f"{header} — {hit.doc.url}"
            blocks.append(f"{header}\n{text}")
        return "\n\n".join(blocks)

    def _sources(self, hits: Sequence[Hit]) -> list[Source]:
        sources: list[Source] = []
        seen: set[str] = set()
        for hit in hits:
            if hit.doc.url in seen:
                continue
            seen.add(hit.doc.url)
            sources.append(Source(url=hit.doc.url, title=hit.doc.title))
            if len(sources) >= 4:
                break
        return sources

    def _extractive_answer(self, hits: Sequence[Hit], *, web: bool = False) -> str:
        if web:
            lines = ["По материалам Ensi:", ""]
            for hit in hits[:3]:
                lines.append(f"• {shorten(to_plain_text(hit.doc.text), 450)}")
            lines.append("")
            lines.append("Если нужен разбор вашего магазина, оставьте заявку на экспресс-аудит на сайте.")
            return "\n".join(lines)

        lines = ["<b>Нашёл в материалах Ensi Cloud:</b>", ""]
        for hit in hits[:3]:
            lines.append(f"• {escape(shorten(hit.doc.text, 450))}")
        lines.append("")
        lines.append(
            "Хотите разобрать именно ваш магазин? Бесплатный экспресс-аудит поиска и каталога занимает 1 день."
        )
        return "\n".join(lines)


def source_button_title(source: Source) -> str:
    title = source.title.strip() or source.url
    return shorten(title, MAX_SOURCE_BUTTON_TITLE)
