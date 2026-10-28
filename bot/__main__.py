import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import ADMIN_IDS, BOT_TOKEN, DB_PATH
from .db import Database
from .handlers import admin, backup, event_types, montaj, operator, orders, quick_order, staff, start
from .middlewares import LogMiddleware, MenuResetMiddleware
from .reminders import reminder_loop
from .web import start_web
from .storage import SQLiteStorage


def build_dispatcher(db: Database) -> Dispatcher:
    dp = Dispatcher(storage=SQLiteStorage(db), db=db)
    dp.message.outer_middleware(LogMiddleware())
    dp.callback_query.outer_middleware(LogMiddleware())
    dp.message.outer_middleware(MenuResetMiddleware())
    # Tartib muhim: avval /start, keyin admin (bekor qilish), keyin bo'limlar, oxirida "tushunmadim"
    dp.include_routers(
        start.router, operator.router, montaj.router, admin.router, backup.router,
        staff.router, event_types.router, quick_order.router, orders.router,
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
    reminders = asyncio.create_task(reminder_loop(bot, db))
    site = await start_web(bot, db)
    try:
        me = await bot.me()
        logging.info("Bot ishga tushdi: @%s", me.username)
        await dp.start_polling(bot)
    finally:
        reminders.cancel()
        if site:
            await site.cleanup()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot to'xtatildi.")
