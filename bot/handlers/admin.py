"""Админские команды: статистика, заявки, проверка уведомлений."""

from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import LinkPreviewOptions, Message

from ..config import Settings
from ..db import Database, TelegramUser, utc_now
from ..formatting import escape, format_datetime, shorten
from ..notifications import ManagerNotifier
from ..rag.retriever import RAGService
from ..texts import ADMIN_ONLY, LEADS_EMPTY, USERS_EMPTY, USERS_USAGE

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _is_admin(message: Message, settings: Settings) -> bool:
    return message.from_user is not None and message.from_user.id in settings.admins


def _plural(number: int, one: str, few: str, many: str) -> str:
    n = abs(number) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


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


@router.message(Command("users"))
async def cmd_users(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
) -> None:
    if not _is_admin(message, settings):
        await message.answer(ADMIN_ONLY)
        return

    days = settings.n_days
    args = (command.args or "").strip()
    if args:
        try:
            days = int(args.split()[0])
        except ValueError:
            await message.answer(USERS_USAGE.format(default=settings.n_days))
            return
    days = max(1, min(days, 365))

    since = utc_now() - timedelta(days=days)
    total = db.active_users_count(since)
    if not total:
        await message.answer(USERS_EMPTY.format(days=days))
        return

    users = db.active_users(since, limit=30)
    lines: list[str] = [f"<b>👥 Писали боту за {days} дн.: {total}</b>", ""]
    for index, user in enumerate(users, start=1):
        name = " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part).strip() or "без имени"
        handle = f"@{escape(user['username'])}" if user.get("username") else "без username"
        questions = int(user.get("questions") or 0)
        lines.append(
            f'{index}. <a href="tg://user?id={user["id"]}">{escape(shorten(name, 40))}</a> · '
            f"{handle} · id <code>{user['id']}</code> · "
            f"{questions} {_plural(questions, 'вопрос', 'вопроса', 'вопросов')} · "
            f"{format_datetime(user['last_seen_at'], '%d.%m %H:%M')}"
        )

    if total > len(users):
        lines.append("")
        lines.append(f"<i>Показаны последние {len(users)}. Уточните период: /users 30</i>")

    await message.answer(
        "\n".join(lines),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


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
