"""Конфигурация бота. Все значения читаются из переменных окружения / .env."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

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
    # Период по умолчанию для админской команды /users.
    n_days: int = Field(default=7, ge=1)

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
    # Дополнительные сайты-источники знаний (через запятую).
    extra_sites: str = "https://ensi.tech"
    seed_urls: str = ""
    # Пути, которые не нужно парсить (через запятую, поддерживается *).
    blocked_paths: str = ""
    # Лимит страниц за один запуск инжеста (можно переопределить --max-pages).
    ingest_max_pages: int = Field(default=200, ge=1)
    db_path: Path = Field(default=Path("data/bot.sqlite3"))
    rag_top_k: int = 5
    rag_min_score: float = 0.15
    history_turns: int = 6
    rate_limit_seconds: float = 1.5

    # --- HTTP API для чата на сайте ---
    api_enabled: bool = True
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8080, ge=1, le=65535)
    api_token: str = ""
    api_cors_origins: str = "*"
    api_rate_limit_per_minute: int = Field(default=20, ge=0)
    api_max_question_chars: int = Field(default=500, ge=10)
    api_max_answer_chars: int = Field(default=1800, ge=50)

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
    def knowledge_sites(self) -> list[str]:
        """Основной сайт + EXTRA_SITES, приведённые к origin (scheme://host).

        Пути, query-параметры и якоря отбрасываются: краулер всё равно ходит
        по всему домену и начинает с sitemap/главной.
        """
        raw = [self.site_base_url, *re.split(r"[,\s]+", self.extra_sites.strip())]
        sites: list[str] = []
        for url in raw:
            url = url.strip()
            if not url:
                continue
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            parsed = urlparse(url)
            if not parsed.netloc:
                continue
            origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
            if origin not in sites:
                sites.append(origin)
        return sites

    @property
    def custom_seeds(self) -> list[str]:
        """SEED_URLS: если заданы, инжест берёт только эти страницы."""
        return [url for url in re.split(r"[,\s]+", self.seed_urls.strip()) if url]

    @property
    def blocked_path_list(self) -> list[str]:
        """BLOCKED_PATHS: пути или шаблоны через запятую/точку с запятой."""
        return [part.strip() for part in re.split(r"[,;\n]+", self.blocked_paths) if part.strip()]

    @property
    def api_cors_list(self) -> list[str]:
        """API_CORS_ORIGINS: список origin'ов или ['*'] по умолчанию."""
        values = [part for part in re.split(r"[,\s]+", self.api_cors_origins.strip()) if part]
        return values or ["*"]
