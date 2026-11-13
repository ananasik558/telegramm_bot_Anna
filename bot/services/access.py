"""Проверка доступа: кто считается «своим» (менеджеры и администраторы)."""

from __future__ import annotations

from ..config import Settings


def is_staff(
    *,
    user_id: int | None,
    chat_id: int | None,
    settings: Settings,
) -> bool:
    """Доступ есть у личных ID менеджеров/админов и у чатов из этих списков.

    Второе нужно, когда уведомления идут в общую группу: кнопку истории
    может нажать любой её участник, но не посторонний пользователь бота.
    """
    allowed = set(settings.managers) | set(settings.admins)
    if not allowed:
        return False
    return bool((user_id is not None and user_id in allowed) or (chat_id is not None and chat_id in allowed))


def is_admin(*, user_id: int | None, chat_id: int | None, settings: Settings) -> bool:
    """Админские команды: достаточно личного ID админа или админского чата."""
    admins = set(settings.admins)
    return bool((user_id is not None and user_id in admins) or (chat_id is not None and chat_id in admins))
