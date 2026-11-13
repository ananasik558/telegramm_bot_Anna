"""Точка входа: aiogram 3 + RAG."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .commands import apply_command_scopes
from .config import Settings
from .db import Database
from .dialogue import DialogueHistory
from .handlers import admin, audit, chat, menu, start
from .handlers import history as history_handlers
from .llm import EmbeddingClient, LLMClient
from .notifications import ManagerNotifier
from .rag.retriever import RAGService

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

    if not settings.bot_token.strip():
        raise SystemExit(
            "BOT_TOKEN не задан.\nСкопируйте .env.example в .env и заполните BOT_TOKEN (токен от @BotFather)."
        )

    db = Database(settings.db_path)
    db.migrate()

    http = aiohttp.ClientSession()
    bot = Bot(
        token=settings.bot_token.strip(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    llm = LLMClient(http, settings)
    embedder = EmbeddingClient(http, settings)
    rag = RAGService(db, llm, embedder, settings)
    rag.load()

    notifier = ManagerNotifier(bot, settings, db)
    history = DialogueHistory(settings.history_turns)

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

    if not rag.ready:
        logger.warning("База знаний пуста. Выполните: python -m bot.rag.ingest")
    if not settings.managers:
        logger.warning("MANAGER_CHAT_IDS пуст: уведомления менеджерам отправляться не будут, события сохраняются в БД.")
    logger.info(
        "Запуск. RAG: %s чанков (%s с векторами), LLM: %s, менеджеров: %s",
        rag.documents,
        rag.vectors,
        "да" if settings.llm_enabled else "нет",
        len(settings.managers),
    )

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        scopes = await apply_command_scopes(bot, settings, db)
        logger.info(
            "Меню команд: публичное для всех, персональное для %s из %s сотрудников (сброшено %s)",
            scopes["applied"],
            scopes["expected"],
            scopes["removed"],
        )
        await dispatcher.start_polling(bot)
    finally:
        logger.info("Остановка бота")
        await http.close()
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
