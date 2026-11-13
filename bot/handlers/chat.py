"""Ответы на свободные вопросы через RAG."""

from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.types import LinkPreviewOptions, Message

from ..config import Settings
from ..db import Database, TelegramUser
from ..dialogue import DialogueHistory
from ..keyboards import answer_menu, main_menu
from ..notifications import ManagerNotifier
from ..rag.retriever import RAGService
from ..services.analytics import maybe_notify_view
from ..texts import (
    NON_TEXT_REPLY,
    RATE_LIMIT_REPLY,
    THINKING,
    UNKNOWN_COMMAND,
)

logger = logging.getLogger(__name__)
router = Router(name="chat")

_last_request: dict[int, float] = {}


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer(UNKNOWN_COMMAND)


@router.message(~F.text)
async def non_text(message: Message, settings: Settings) -> None:
    await message.answer(NON_TEXT_REPLY, reply_markup=main_menu(settings.site_base_url))


@router.message(F.text)
async def on_question(
    message: Message,
    db: Database,
    rag: RAGService,
    notifier: ManagerNotifier,
    settings: Settings,
    history: DialogueHistory,
) -> None:
    question = " ".join((message.text or "").split())
    if len(question) < 2:
        return

    user = TelegramUser.from_aiogram(message.from_user)  # type: ignore[arg-type]
    db.upsert_user(user)

    now = time.monotonic()
    previous = _last_request.get(user.id, 0.0)
    if now - previous < settings.rate_limit_seconds:
        await message.answer(RATE_LIMIT_REPLY)
        return
    _last_request[user.id] = now

    db.log_event(user.id, "question")
    placeholder = await message.answer(THINKING)

    try:
        answer = await rag.answer(question, history.get(user.id))
    except Exception:  # noqa: BLE001 — бот не должен падать из-за одного вопроса
        logger.exception("Ошибка RAG для вопроса %r", question)
        await placeholder.edit_text(
            "Не получилось найти ответ 😔 Попробуйте переформулировать вопрос или напишите менеджеру."
        )
        return

    db.log_question(
        user.id,
        question,
        answer.text,
        [source.url for source in answer.sources],
        answer.top_score,
    )
    history.add(user.id, question, answer.text)

    keyboard = answer_menu(answer.sources, settings.site_base_url)
    try:
        await placeholder.edit_text(
            answer.text,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception:  # noqa: BLE001 — сообщение могло быть удалено/устареть
        await message.answer(
            answer.text,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    await maybe_notify_view(db, notifier, settings, user, question)
