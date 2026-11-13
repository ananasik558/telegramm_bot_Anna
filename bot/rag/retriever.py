"""RAG-сервис: поиск по базе знаний + генерация ответа."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from ..config import Settings
from ..db import Database
from ..formatting import escape, shorten, to_telegram_html
from ..llm import EmbeddingClient, LLMClient, LLMError
from ..prompts import ANSWER_INSTRUCTIONS, NO_CONTEXT_INSTRUCTIONS, SYSTEM_PROMPT
from ..texts import FALLBACK_NO_CONTEXT, LLM_DISABLED_NOTE, LLM_ERROR_NOTE
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
    ) -> RagAnswer:
        question = question.strip()
        hits = await self._search(question)

        if not hits:
            return await self._answer_without_context(question)

        sources = self._sources(hits)
        if not self._llm.enabled:
            return RagAnswer(
                text=self._extractive_answer(hits) + LLM_DISABLED_NOTE,
                sources=sources,
                used_context=True,
                degraded=True,
            )

        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for role, text in history:
            messages.append({"role": role, "content": text})
        messages.append(
            {
                "role": "user",
                "content": ANSWER_INSTRUCTIONS.format(
                    context=self._format_context(hits),
                    question=question,
                ),
            }
        )

        try:
            raw = await self._llm.chat(messages)
            text = to_telegram_html(raw)
            if len(text) > MAX_ANSWER_CHARS:
                text = shorten(text, MAX_ANSWER_CHARS)
            return RagAnswer(
                text=text,
                sources=sources,
                used_context=True,
                top_score=hits[0].score,
            )
        except LLMError as error:
            logger.warning("LLM недоступна, отдаю выдержки: %s", error)
            return RagAnswer(
                text=self._extractive_answer(hits) + LLM_ERROR_NOTE,
                sources=sources,
                used_context=True,
                degraded=True,
                top_score=hits[0].score,
            )

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

    async def _answer_without_context(self, question: str) -> RagAnswer:
        if not self._llm.enabled:
            return RagAnswer(text=FALLBACK_NO_CONTEXT, used_context=False)
        try:
            raw = await self._llm.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": NO_CONTEXT_INSTRUCTIONS.format(question=question)},
                ]
            )
            return RagAnswer(text=to_telegram_html(raw), used_context=False)
        except LLMError as error:
            logger.warning("LLM недоступна: %s", error)
            return RagAnswer(text=FALLBACK_NO_CONTEXT, used_context=False, degraded=True)

    def _format_context(self, hits: Sequence[Hit]) -> str:
        blocks: list[str] = []
        for index, hit in enumerate(hits, start=1):
            text = shorten(hit.doc.text, 1800)
            blocks.append(f"[{index}] {hit.doc.title} — {hit.doc.url}\n{text}")
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

    def _extractive_answer(self, hits: Sequence[Hit]) -> str:
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
