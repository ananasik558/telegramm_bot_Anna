"""Клиенты для OpenAI-совместимого API: чат и эмбеддинги.

Провайдера можно поменять через LLM_BASE_URL (OpenAI, DeepSeek, OpenRouter,
vLLM, Ollama и т.п.). Бот не зависит от конкретного вендора.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import aiohttp

from .config import Settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Ошибка обращения к LLM/эмбеддингам."""


class LLMClient:
    def __init__(self, session: aiohttp.ClientSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.llm_enabled

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> str:
        if not self.enabled:
            raise LLMError("LLM_API_KEY не задан")

        payload = {
            "model": model or self._settings.llm_model,
            "messages": list(messages),
            "temperature": self._settings.llm_temperature if temperature is None else temperature,
            "max_tokens": self._settings.llm_max_tokens if max_tokens is None else max_tokens,
        }
        data = await self.post("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError(f"Неожиданный ответ LLM: {str(data)[:300]}") from error
        if not content or not str(content).strip():
            raise LLMError("LLM вернул пустой ответ")
        return str(content).strip()

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._settings.llm_base_url}{path}"
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key}"
        timeout = aiohttp.ClientTimeout(total=self._settings.llm_timeout_seconds)
        try:
            async with self._session.post(url, json=payload, headers=headers, timeout=timeout) as response:
                body = await response.text()
                if response.status >= 400:
                    raise LLMError(f"HTTP {response.status} от {url}: {body[:500]}")
                try:
                    return await response.json(content_type=None)
                except ValueError as error:
                    raise LLMError(f"Не JSON в ответе {url}: {body[:300]}") from error
        except TimeoutError as error:
            raise LLMError(f"Таймаут запроса к {url}") from error
        except aiohttp.ClientError as error:
            raise LLMError(f"Сетевая ошибка при запросе к {url}: {error}") from error


class EmbeddingClient:
    def __init__(self, session: aiohttp.ClientSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._llm = LLMClient(session, settings)

    @property
    def enabled(self) -> bool:
        return self._settings.embeddings_ready

    async def embed_one(self, text: str) -> list[float] | None:
        if not self.enabled:
            return None
        vectors = await self.embed([text])
        return vectors[0] if vectors else None

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.enabled:
            raise LLMError("Эмбеддинги отключены (нет ключа или EMBEDDINGS_ENABLED=false)")

        data = await self._llm.post(
            "/embeddings",
            {"model": self._settings.embedding_model, "input": list(texts)},
        )
        try:
            items = sorted(data["data"], key=lambda item: item.get("index", 0))
            vectors = [item["embedding"] for item in items]
        except (KeyError, TypeError) as error:
            raise LLMError(f"Неожиданный ответ embeddings: {str(data)[:300]}") from error
        if len(vectors) != len(texts):
            raise LLMError(f"Пришло {len(vectors)} векторов вместо {len(texts)}")
        actual_dim = len(vectors[0]) if vectors else 0
        if actual_dim and self._settings.embedding_dim and actual_dim != self._settings.embedding_dim:
            logger.warning(
                "Размерность эмбеддингов %s не совпадает с EMBEDDING_DIM=%s. "
                "Проверьте EMBEDDING_MODEL в .env и переиндексируйте сайт.",
                actual_dim,
                self._settings.embedding_dim,
            )
        return vectors

    async def embed_many(
        self,
        texts: Sequence[str],
        *,
        batch_size: int = 64,
        on_progress: Any = None,
    ) -> list[list[float]]:
        """Эмбеддинги пачками — чтобы не упираться в лимиты провайдера."""
        result: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            result.extend(await self.embed(batch))
            if on_progress is not None:
                on_progress(len(result), len(texts))
        return result
