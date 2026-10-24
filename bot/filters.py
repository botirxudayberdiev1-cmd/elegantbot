from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from .db import Database


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, db: Database) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and await db.is_admin(user.id)
