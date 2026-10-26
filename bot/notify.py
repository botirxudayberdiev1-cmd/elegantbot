import logging

from aiogram import Bot

from .cards import assignment_text
from .db import Database
from .keyboards import assignment_kb

log = logging.getLogger(__name__)


CAPTION_LIMIT = 1024  # Telegram rasm ostidagi matn chegarasi


async def send_card(bot: Bot, a, text: str, reply_markup=None) -> None:
    """Tadbir kartasi: dekoratorga dekor rasmi bilan, keyin (bo'lsa) lokatsiya."""
    if a["role"] == "dekorator" and a["decor_photo"] and len(text) <= CAPTION_LIMIT:
        await bot.send_photo(a["staff_tg_id"], a["decor_photo"], caption=text, reply_markup=reply_markup)
    else:
        await bot.send_message(a["staff_tg_id"], text, reply_markup=reply_markup)
        if a["role"] == "dekorator" and a["decor_photo"]:
            await bot.send_photo(a["staff_tg_id"], a["decor_photo"], caption="🎀 Dekor rasmi")
    if a["lat"] is not None:
        await bot.send_location(a["staff_tg_id"], a["lat"], a["lon"])


async def send_assignment(bot: Bot, db: Database, asg_id: int) -> bool:
    """Xodimga tadbir kartasini yuboradi. Yuborilmasa (ulanmagan, botni bloklagan) — False."""
    a = await db.assignment_info(asg_id)
    if not a or not a["staff_tg_id"]:
        return False
    team = await db.event_team(a["event_id"])
    try:
        await send_card(bot, a, assignment_text(a, team), assignment_kb(asg_id))
        return True
    except Exception as e:
        log.warning("Xodimga (%s) karta yuborilmadi: %s", a["staff_name"], e)
        return False
