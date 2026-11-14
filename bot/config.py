"""Конфигурация бота. Все значения читаются из переменных окружения / .env."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Стартовые страницы, если SEED_URLS не задан. Дальше ingest доберёт sitemap.xml.
DEFAULT_SEED_PATHS: tuple[str, ...] = (
    "/",
    "/search",
    "/visual-search",
    "/adviser",
    "/productgenerator",
    "/sort",
    "/ab-test",
    "/ai",
    "/custom-ai",
    "/express-audit",
    "/tariffs",
    "/cases",
    "/faq",
    "/company",
    "/partners",
    "/articles",
)


def _parse_ids(raw: str) -> list[int]:
    """Разбирает строку вида '111, 222;333' в список int."""
    ids: list[int] = []
    for chunk in re.split(r"[,\s;]+", raw.strip()):
        if not chunk:
            continue
        try:
            ids.append(int(chunk))
        except ValueError:
            # Не роняем бота из-за опечатки в .env — просто пропускаем.
            continue
    return ids


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---
    bot_token: str = ""
    manager_chat_ids: str = ""
    manager_topic_id: int | None = None
    admin_ids: str = ""

    notify_on_signup: bool = True
    notify_on_view: bool = True
    # Уведомление «изучает бота»: больше N вопросов или N минут тишины.
    n_questions: int = Field(default=5, ge=0)
    view_notify_idle_minutes: float = Field(default=5.0, ge=0)

    # --- LLM (OpenAI-совместимый API) ---
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 700
    llm_timeout_seconds: float = 45.0

    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embeddings_enabled: bool = True

    # --- RAG / сайт ---
    site_base_url: str = "https://ensi.cloud"
    seed_urls: str = ""
    db_path: Path = Field(default=Path("data/bot.sqlite3"))
    rag_top_k: int = 5
    rag_min_score: float = 0.15
    history_turns: int = 6
    rate_limit_seconds: float = 1.5

    # --- Реквизиты ---
    contact_telegram: str = "@Greensight_telegram"
    contact_phone: str = "+7 499 391-66-69"

    log_level: str = "INFO"

    @field_validator("llm_base_url", "site_base_url")
    @classmethod
    def _strip_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @property
    def admins(self) -> list[int]:
        return _parse_ids(self.admin_ids)

    @property
    def managers(self) -> list[int]:
        return _parse_ids(self.manager_chat_ids)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key.strip())

    @property
    def embeddings_ready(self) -> bool:
        return self.embeddings_enabled and self.llm_enabled

    @property
    def seeds(self) -> list[str]:
        if self.seed_urls.strip():
            return [url for url in re.split(r"[,\s]+", self.seed_urls.strip()) if url]
        base = self.site_base_url.rstrip("/")
        return [f"{base}{path}" for path in DEFAULT_SEED_PATHS]
