"""Точка входа: aiogram 3 + RAG + HTTP API для чата на сайте."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .api import start_api
from .commands import apply_command_scopes
from .config import Settings
from .db import Database
from .dialogue import DialogueHistory
from .handlers import admin, audit, chat, menu, start
from .handlers import history as history_handlers
from .llm import EmbeddingClient, LLMClient
from .notifications import ManagerNotifier
from .rag.retriever import RAGService
from .services.view_notifier import ViewNotifier
from .services.web_chat import WebChatService

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    telegram_enabled = bool(settings.bot_token.strip())
    if not telegram_enabled and not settings.api_enabled:
        raise SystemExit(
            "BOT_TOKEN не задан, а API_ENABLED=false. Нечего запускать.\n"
            "Заполните BOT_TOKEN и/или включите API_ENABLED=true."
        )

    db = Database(settings.db_path)
    db.migrate()

    http = aiohttp.ClientSession()

    llm = LLMClient(http, settings)
    embedder = EmbeddingClient(http, settings)
    rag = RAGService(db, llm, embedder, settings)
    rag.load()

    if not rag.ready:
        logger.warning("База знаний пуста. Выполните: python -m bot.rag.ingest")
    logger.info(
        "RAG: %s чанков (%s с векторами), LLM: %s",
        rag.documents,
        rag.vectors,
        "да" if settings.llm_enabled else "нет",
    )

    web_service = WebChatService(rag, db, settings) if settings.api_enabled else None
    api_runner = None
    if web_service is not None:
        try:
            api_runner = await start_api(web_service, settings)
            logger.info(
                "HTTP API: http://%s:%s/api/chat (health: /health)",
                settings.api_host,
                settings.api_port,
            )
            if not settings.api_token and settings.api_host not in ("127.0.0.1", "localhost", "::1"):
                logger.warning("HTTP API доступен по сети без API_TOKEN. Задайте токен и CORS-домены.")
        except OSError as error:
            logger.error("HTTP API не запустился: %s", error)
            if not telegram_enabled:
                await http.close()
                db.close()
                raise SystemExit(f"Не удалось занять {settings.api_host}:{settings.api_port} для HTTP API.") from error

    bot: Bot | None = None
    dispatcher: Dispatcher | None = None
    view_notifier: ViewNotifier | None = None

    try:
        if telegram_enabled:
            bot = Bot(
                token=settings.bot_token.strip(),
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            notifier = ManagerNotifier(bot, settings, db)
            history = DialogueHistory(settings.history_turns)
            view_notifier = ViewNotifier(notifier, db, settings)

            dispatcher = Dispatcher(storage=MemoryStorage())
            dispatcher.include_routers(
                admin.router,
                start.router,
                audit.router,
                menu.router,
                history_handlers.router,
                chat.router,
            )
            dispatcher["settings"] = settings
            dispatcher["db"] = db
            dispatcher["rag"] = rag
            dispatcher["notifier"] = notifier
            dispatcher["history"] = history
            dispatcher["view_notifier"] = view_notifier

            if not settings.managers:
                logger.warning(
                    "MANAGER_CHAT_IDS пуст: уведомления менеджерам отправляться не будут, события сохраняются в БД."
                )

            await bot.delete_webhook(drop_pending_updates=True)
            scopes = await apply_command_scopes(bot, settings, db)
            logger.info(
                "Меню команд: публичное для всех, персональное для %s из %s сотрудников (сброшено %s)",
                scopes["applied"],
                scopes["expected"],
                scopes["removed"],
            )
            await dispatcher.start_polling(bot)
        else:
            logger.info("Telegram отключён (BOT_TOKEN пуст). Работает только HTTP API.")
            await asyncio.Event().wait()
    finally:
        logger.info("Остановка")
        if view_notifier is not None:
            await view_notifier.shutdown()
        if api_runner is not None:
            await api_runner.cleanup()
        await http.close()
        if bot is not None:
            await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
