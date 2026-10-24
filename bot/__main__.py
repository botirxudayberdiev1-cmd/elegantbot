import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import ADMIN_IDS, BOT_TOKEN, DB_PATH
from .db import Database
from .handlers import admin, event_types, operator, orders, staff, start
from .middlewares import MenuResetMiddleware


def build_dispatcher(db: Database) -> Dispatcher:
    dp = Dispatcher(db=db)
    dp.message.outer_middleware(MenuResetMiddleware())
    # Tartib muhim: avval /start, keyin admin (bekor qilish), keyin bo'limlar, oxirida "tushunmadim"
    dp.include_routers(
        start.router, operator.router, admin.router,
        staff.router, event_types.router, orders.router,
        admin.fallback_router,
    )
    return dp


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if not BOT_TOKEN:
        sys.exit("BOT_TOKEN topilmadi. .env.example dan .env yarating va tokenni yozing.")
    if not ADMIN_IDS:
        logging.warning("ADMIN_IDS bo'sh — hech kim admin menyusini ko'rmaydi.")

    db = Database(DB_PATH)
    await db.connect()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(db)
    try:
        me = await bot.me()
        logging.info("Bot ishga tushdi: @%s", me.username)
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
