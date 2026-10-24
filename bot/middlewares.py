import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from .keyboards import MENU_BUTTONS

log = logging.getLogger("bot.in")


class LogMiddleware(BaseMiddleware):
    """Terminalda kim nima yozgani va qaysi qadamda turgani ko'rinadi (nosozlikni topish uchun)."""

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        what = getattr(event, "text", None) or getattr(event, "data", None) or event.__class__.__name__
        log.info("<- %s [%s] %r", user.id if user else "?", data.get("raw_state") or "-", what)
        return await handler(event, data)


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
