"""Запись на бесплатный экспресс-аудит: FSM-диалог и уведомление менеджерам."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message

from ..config import Settings
from ..db import Database, TelegramUser
from ..formatting import escape
from ..keyboards import audit_comment_nav, audit_confirm_nav, audit_nav
from ..notifications import ManagerNotifier
from ..services.analytics import questions_summary
from ..texts import (
    AUDIT_ACCEPTED,
    AUDIT_ASK_COMMENT,
    AUDIT_ASK_CONTACT,
    AUDIT_ASK_SITE,
    AUDIT_CANCELLED,
    AUDIT_CONFIRM,
    AUDIT_CONFIRM_HINT,
    AUDIT_INTRO,
    AUDIT_INVALID_CONTACT,
    AUDIT_INVALID_NAME,
    AUDIT_INVALID_SITE,
    AUDIT_TEXT_ONLY,
    NOTIFY_AUDIT_TITLE,
)

logger = logging.getLogger(__name__)
router = Router(name="audit")


class AuditFlow(StatesGroup):
    name = State()
    site = State()
    contact = State()
    comment = State()
    confirm = State()


async def begin_audit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AuditFlow.name)
    await message.answer(AUDIT_INTRO, reply_markup=audit_nav())


def _clean_name(raw: str) -> str:
    return " ".join(raw.split())[:80]


def _clean_site(raw: str) -> str | None:
    value = raw.strip().lower()
    if value in {"нет", "no", "net", "-", "—", "не", "неа"}:
        return "нет"
    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0].strip().strip(".")
    if value.startswith("www."):
        value = value[4:]
    if len(value) < 4 or "." not in value or " " in value:
        return None
    return value[:120]


def _clean_contact(raw: str) -> str | None:
    value = " ".join(raw.split())
    if len(value) < 3 or len(value) > 120:
        return None
    return value


@router.message(Command("audit"))
async def cmd_audit(message: Message, state: FSMContext) -> None:
    await begin_audit(message, state)


@router.callback_query(F.data == "audit:start")
async def cb_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is not None:
        await begin_audit(callback.message, state)


@router.callback_query(F.data == "audit:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Заявка отменена")
    if callback.message is not None:
        await callback.message.edit_text(AUDIT_CANCELLED, reply_markup=None)


# ------------------------------------------------------------------ шаги FSM


@router.message(StateFilter(AuditFlow.name), F.text)
async def step_name(message: Message, state: FSMContext) -> None:
    name = _clean_name(message.text or "")
    if len(name) < 2:
        await message.answer(AUDIT_INVALID_NAME)
        return
    await state.update_data(name=name)
    await state.set_state(AuditFlow.site)
    await message.answer(
        AUDIT_ASK_SITE.format(name=escape(name)),
        reply_markup=audit_nav(),
    )


@router.message(StateFilter(AuditFlow.site), F.text)
async def step_site(message: Message, state: FSMContext) -> None:
    site = _clean_site(message.text or "")
    if site is None:
        await message.answer(AUDIT_INVALID_SITE)
        return
    await state.update_data(site=site)
    await state.set_state(AuditFlow.contact)
    await message.answer(AUDIT_ASK_CONTACT, reply_markup=audit_nav())


@router.message(StateFilter(AuditFlow.contact), F.text)
async def step_contact(message: Message, state: FSMContext) -> None:
    contact = _clean_contact(message.text or "")
    if contact is None:
        await message.answer(AUDIT_INVALID_CONTACT)
        return
    await state.update_data(contact=contact)
    await state.set_state(AuditFlow.comment)
    await message.answer(AUDIT_ASK_COMMENT, reply_markup=audit_comment_nav())


@router.message(StateFilter(AuditFlow.comment), F.text)
async def step_comment(message: Message, state: FSMContext, settings: Settings) -> None:
    comment = " ".join((message.text or "").split())[:1000]
    if comment in {"-", "—", "нет"}:
        comment = ""
    await state.update_data(comment=comment)
    await _show_confirm(message, state, settings)


@router.callback_query(StateFilter(AuditFlow.comment), F.data == "audit:skip_comment")
async def cb_skip_comment(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await callback.answer()
    await state.update_data(comment="")
    if callback.message is not None:
        await _show_confirm(callback.message, state, settings)


@router.message(StateFilter(AuditFlow.confirm), F.text)
async def step_confirm_text(message: Message) -> None:
    await message.answer(AUDIT_CONFIRM_HINT)


@router.message(StateFilter(AuditFlow), ~F.text)
async def step_non_text(message: Message) -> None:
    await message.answer(AUDIT_TEXT_ONLY)


async def _show_confirm(message: Message, state: FSMContext, settings: Settings) -> None:
    data = await state.get_data()
    await state.set_state(AuditFlow.confirm)
    await message.answer(
        AUDIT_CONFIRM.format(
            name=escape(data.get("name", "—")),
            site=escape(data.get("site", "—")),
            contact=escape(data.get("contact", "—")),
            comment=escape(data.get("comment") or "—"),
            privacy_url=f"{settings.site_base_url}/privacy-policy",
        ),
        reply_markup=audit_confirm_nav(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


# --------------------------------------------------------------- отправка


@router.callback_query(StateFilter(AuditFlow.confirm), F.data == "audit:submit")
async def cb_submit(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    notifier: ManagerNotifier,
    settings: Settings,
) -> None:
    data = await state.get_data()
    await callback.answer("Отправляю…")

    if not data:
        if callback.message is not None:
            await begin_audit(callback.message, state)
        return

    user = TelegramUser.from_aiogram(callback.from_user)
    db.upsert_user(user)

    lead_id = db.create_lead(
        user.id,
        name=data.get("name"),
        site=data.get("site"),
        contact=data.get("contact"),
        comment=data.get("comment") or None,
    )
    db.log_event(user.id, "audit_request", {"lead_id": lead_id, "site": data.get("site")})

    await notifier.notify(
        kind="audit",
        user=user,
        title=NOTIFY_AUDIT_TITLE,
        details=[
            ("Заявка", f"#{lead_id}"),
            ("Имя", data.get("name", "—")),
            ("Сайт", data.get("site", "—")),
            ("Контакт", data.get("contact", "—")),
            ("Комментарий", data.get("comment") or "—"),
            ("Что искал(а) в боте", questions_summary(db.recent_questions(user.id, 5))),
        ],
    )

    await state.clear()

    telegram_url = (
        settings.contact_telegram
        if settings.contact_telegram.startswith("http")
        else f"https://t.me/{settings.contact_telegram.lstrip('@')}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать менеджеру", url=telegram_url)],
            [InlineKeyboardButton(text="🌐 Сайт Ensi Cloud", url=settings.site_base_url)],
        ]
    )
    text = AUDIT_ACCEPTED.format(audit_url=f"{settings.site_base_url}/express-audit")

    if callback.message is not None:
        try:
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except Exception:  # noqa: BLE001 — сообщение могло устареть
            await callback.message.answer(
                text,
                reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
