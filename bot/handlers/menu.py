"""Кнопки меню: продукты и связь с менеджером."""

from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from ..config import Settings
from ..db import Database, TelegramUser, utc_now
from ..keyboards import products_menu
from ..notifications import ManagerNotifier
from ..services.analytics import questions_summary
from ..texts import CONTACT_TEXT, NOTIFY_CONTACT_TITLE, PRODUCTS_TEXT

logger = logging.getLogger(__name__)
router = Router(name="menu")

CONTACT_DEDUPE = timedelta(minutes=30)


def _telegram_url(handle: str) -> str:
    if handle.startswith("http"):
        return handle
    return f"https://t.me/{handle.lstrip('@')}"


@router.callback_query(F.data == "menu:products")
async def cb_products(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            PRODUCTS_TEXT,
            reply_markup=products_menu(settings.site_base_url),
        )


@router.callback_query(F.data == "contact:manager")
async def cb_contact(
    callback: CallbackQuery,
    db: Database,
    notifier: ManagerNotifier,
    settings: Settings,
) -> None:
    await callback.answer("Передал менеджерам 👍")

    user = TelegramUser.from_aiogram(callback.from_user)
    db.upsert_user(user)

    last = db.last_event_at(user.id, "contact_request")
    if last is None or utc_now() - last > CONTACT_DEDUPE:
        db.log_event(user.id, "contact_request")
        await notifier.notify(
            kind="contact",
            user=user,
            title=NOTIFY_CONTACT_TITLE,
            details=[
                ("Последние запросы", questions_summary(db.recent_questions(user.id, 5))),
            ],
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Открыть чат с менеджером",
                    url=_telegram_url(settings.contact_telegram),
                )
            ],
            [InlineKeyboardButton(text="🚀 Экспресс-аудит — бесплатно", callback_data="audit:start")],
        ]
    )
    text = CONTACT_TEXT.format(
        telegram=settings.contact_telegram,
        phone=settings.contact_phone,
        site=settings.site_base_url,
    )
    if callback.message is not None:
        await callback.message.answer(
            text,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
