from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from ..cards import assignment_text
from ..db import Database
from ..keyboards import AsgCb
from ..utils import escape, notify_admins

router = Router(name="operator")


@router.callback_query(AsgCb.filter(F.action.in_({"yes", "no"})))
async def respond(call: CallbackQuery, callback_data: AsgCb, db: Database, bot: Bot):
    a = await db.assignment_info(callback_data.id)
    if not a or a["staff_tg_id"] != call.from_user.id:
        await call.answer("Bu tadbir sizga tegishli emas.", show_alert=True)
        return
    if a["status"] != "kutilmoqda":
        await call.answer("Siz allaqachon javob bergansiz.", show_alert=True)
        return

    status = "qabul" if callback_data.action == "yes" else "rad"
    await db.assignment_respond(a["id"], status)
    a = await db.assignment_info(a["id"])
    await call.message.edit_text(
        assignment_text(a, await db.event_team(a["event_id"])), reply_markup=None
    )
    await call.answer("Javobingiz yuborildi")

    when = f"{a['date'][8:10]}.{a['date'][5:7]} {a['time']}"
    what = (
        f"{escape(a['type_name'])}, {when}, mijoz {escape(a['client_name'])} "
        f"(buyurtma №{a['order_id']})"
    )
    if status == "qabul":
        text = f"✅ <b>{escape(a['staff_name'])}</b> qabul qildi: {what}"
    else:
        text = (
            f"❌ <b>{escape(a['staff_name'])}</b> bora olmaydi: {what}\n"
            "O'rniga boshqa operator qo'yish kerak."
        )
    await notify_admins(bot, db, text)
