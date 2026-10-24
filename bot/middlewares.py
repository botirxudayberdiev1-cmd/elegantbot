from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

from .keyboards import MENU_BUTTONS


class MenuResetMiddleware(BaseMiddleware):
    """Biror jarayon (buyurtma, xodim qo'shish...) o'rtasida menyu tugmasi bosilsa,
    jarayon bekor qilinadi va tugma o'z bo'limini ochadi."""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if event.text in MENU_BUTTONS and data.get("raw_state") is not None:
            await data["state"].clear()
            data["raw_state"] = None
            await event.answer("ℹ️ Avvalgi jarayon bekor qilindi.")
        return await handler(event, data)
