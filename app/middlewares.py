from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from app.config import get_settings


class AdminMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            user = getattr(event, "from_user", None)

        if user is not None and user.id in get_settings().admin_id_set:
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer(
                "Este bot es privado. Tu ID de Telegram no está autorizado."
            )
        elif isinstance(event, CallbackQuery):
            await event.answer(
                "No tienes permiso para usar este bot.", show_alert=True
            )
        return None
