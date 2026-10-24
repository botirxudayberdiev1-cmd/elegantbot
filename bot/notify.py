import logging

from aiogram import Bot

from .cards import assignment_text
from .db import Database
from .keyboards import assignment_kb

log = logging.getLogger(__name__)


async def send_assignment(bot: Bot, db: Database, asg_id: int) -> bool:
    """Operatorga tadbir kartasini yuboradi. Yuborilmasa (ulanmagan, botni bloklagan) — False."""
    a = await db.assignment_info(asg_id)
    if not a or not a["staff_tg_id"]:
        return False
    team = await db.event_team(a["event_id"])
    try:
        await bot.send_message(
            a["staff_tg_id"], assignment_text(a, team), reply_markup=assignment_kb(asg_id)
        )
        return True
    except Exception as e:
        log.warning("Operatorga (%s) karta yuborilmadi: %s", a["staff_name"], e)
        return False
