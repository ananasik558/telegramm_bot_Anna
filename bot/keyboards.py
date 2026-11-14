"""Клавиатуры бота."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .rag.retriever import Source, source_button_title

PRODUCT_LINKS: tuple[tuple[str, str], ...] = (
    ("🔍 Search — умный поиск", "/search"),
    ("📸 Visual Search — поиск по фото", "/visual-search"),
    ("🤝 Adviser — рекомендации", "/adviser"),
    ("✍️ Product Generator", "/productgenerator"),
    ("🧮 Sort — AI-мерчандайзер", "/sort"),
    ("🧪 A/B Test", "/ab-test"),
    ("🧠 AI-модуль", "/ai"),
    ("🛠 Заказная ИИ-разработка", "/custom-ai"),
)


def main_menu(site_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Записаться на экспресс-аудит", callback_data="audit:start")],
            [InlineKeyboardButton(text="🧭 Продукты Ensi Cloud", callback_data="menu:products")],
            [InlineKeyboardButton(text="💬 Связаться с менеджером", callback_data="contact:manager")],
            [InlineKeyboardButton(text="🌐 Открыть сайт", url=site_url)],
        ]
    )


def answer_menu(sources: list[Source], site_url: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🚀 Бесплатный экспресс-аудит", callback_data="audit:start")],
        [
            InlineKeyboardButton(text="💬 Менеджер", callback_data="contact:manager"),
            InlineKeyboardButton(text="🌐 Сайт", url=site_url),
        ],
    ]
    for source in sources[:4]:
        rows.append([InlineKeyboardButton(text=f"📄 {source_button_title(source)}", url=source.url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def products_menu(site_url: str, platform_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for label, path in PRODUCT_LINKS:
        pair.append(InlineKeyboardButton(text=label, url=f"{site_url}{path}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    if platform_url:
        rows.append([InlineKeyboardButton(text="🏗 Платформа Ensi", url=platform_url)])
    rows.append([InlineKeyboardButton(text="🚀 Экспресс-аудит", callback_data="audit:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def audit_nav() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✖️ Отменить", callback_data="audit:cancel")]]
    )


def audit_comment_nav() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить →", callback_data="audit:skip_comment")],
            [InlineKeyboardButton(text="✖️ Отменить", callback_data="audit:cancel")],
        ]
    )


def audit_confirm_nav() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отправить заявку", callback_data="audit:submit")],
            [InlineKeyboardButton(text="✖️ Отменить", callback_data="audit:cancel")],
        ]
    )
