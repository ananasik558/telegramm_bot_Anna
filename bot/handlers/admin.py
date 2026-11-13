"""Админские команды: статистика, заявки, проверка уведомлений."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from ..config import Settings
from ..db import Database, TelegramUser
from ..formatting import escape, shorten
from ..notifications import ManagerNotifier
from ..rag.retriever import RAGService
from ..texts import ADMIN_ONLY, LEADS_EMPTY

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _is_admin(message: Message, settings: Settings) -> bool:
    return message.from_user is not None and message.from_user.id in settings.admins


@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    db: Database,
    settings: Settings,
    rag: RAGService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer(ADMIN_ONLY)
        return

    stats = db.stats()
    await message.answer(
        "<b>📊 Статистика бота</b>\n\n"
        f"Пользователей: <b>{stats['users']}</b> (сегодня +{stats['users_today']})\n"
        f"Активных сегодня: <b>{stats['active_today']}</b>\n"
        f"Вопросов: <b>{stats['questions']}</b> (сегодня {stats['questions_today']})\n"
        f"Заявок: <b>{stats['leads']}</b> (новых {stats['leads_new']})\n\n"
        "<b>База знаний</b>\n"
        f"Документов: {stats['documents']}, чанков: {stats['chunks']}\n"
        f"В памяти: {rag.documents} чанков, из них с векторами {rag.vectors}\n\n"
        f"Менеджеров в рассылке: {len(settings.managers)}\n"
        f"LLM: {'включена' if settings.llm_enabled else 'выключена (только выдержки)'}"
    )


@router.message(Command("leads"))
async def cmd_leads(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
) -> None:
    if not _is_admin(message, settings):
        await message.answer(ADMIN_ONLY)
        return

    limit = 5
    if command.args:
        try:
            limit = max(1, min(20, int(command.args.strip())))
        except ValueError:
            pass

    leads = db.list_leads(limit=limit)
    if not leads:
        await message.answer(LEADS_EMPTY)
        return

    blocks: list[str] = [f"<b>Последние заявки ({len(leads)})</b>"]
    for lead in leads:
        created = str(lead["created_at"])[:16].replace("T", " ")
        blocks.append(
            f"\n<b>#{lead['id']}</b> · {created} · {escape(lead['status'])}\n"
            f"👤 {escape(lead['name'] or '—')} · id <code>{lead['user_id']}</code>\n"
            f"🌐 {escape(lead['site'] or '—')}\n"
            f"📞 {escape(lead['contact'] or '—')}\n"
            f"💬 {escape(shorten(lead['comment'] or '—', 200))}"
        )
    await message.answer("\n".join(blocks))


@router.message(Command("knowledge"))
async def cmd_knowledge(message: Message, db: Database, settings: Settings) -> None:
    if not _is_admin(message, settings):
        await message.answer(ADMIN_ONLY)
        return

    docs = db.knowledge_docs()
    if not docs:
        await message.answer("База знаний пуста. Запустите:\n<code>python -m bot.rag.ingest</code>")
        return

    lines = [f"<b>📚 База знаний: {len(docs)} страниц</b>", ""]
    for doc in docs[:25]:
        lines.append(f"• {escape(shorten(doc['title'], 60))} — {doc['chunks']} чанков\n  {escape(doc['url'])}")
    if len(docs) > 25:
        lines.append(f"\n… и ещё {len(docs) - 25}")
    await message.answer("\n".join(lines))


@router.message(Command("test_notify"))
async def cmd_test_notify(
    message: Message,
    settings: Settings,
    notifier: ManagerNotifier,
) -> None:
    if not _is_admin(message, settings):
        await message.answer(ADMIN_ONLY)
        return

    if not settings.managers:
        await message.answer(
            "⚠️ MANAGER_CHAT_IDS пуст — уведомления некуда отправлять.\n"
            "Напишите /id с аккаунта менеджера и добавьте ID в .env."
        )
        return

    user = TelegramUser.from_aiogram(message.from_user)  # type: ignore[arg-type]
    sent = await notifier.notify(
        kind="test",
        user=user,
        title="🧪 Проверка уведомлений",
        details=[
            ("Кому отправлено", ", ".join(str(chat_id) for chat_id in settings.managers)),
            ("Доставок", str(len(settings.managers))),
            ("Статус", "если вы это видите — всё настроено"),
        ],
    )
    await message.answer(
        f"Отправлено: {sent} из {len(settings.managers)}.\n"
        "Если доставок меньше — проверьте, что каждый менеджер нажал /start у бота "
        "или что бот добавлен в чат."
    )
