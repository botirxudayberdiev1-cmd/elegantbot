from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from ..db import Database
from ..montaj import MtCb, notify_ready, send_to_client
from ..utils import escape

router = Router(name="montaj")


@router.callback_query(MtCb.filter(F.action == "done"))
async def editing_done(call: CallbackQuery, callback_data: MtCb, db: Database, bot: Bot):
    o = await db.order_brief(callback_data.id)
    if not o or o["editor_tg_id"] != call.from_user.id:
        await call.answer("Bu to'y sizga biriktirilmagan.", show_alert=True)
        return
    if o["editing_done_at"]:
        await call.answer("Allaqachon «tayyor» deb belgilangan.", show_alert=True)
        return
    await db.order_stamp(o["id"], "editing_done_at")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"✅ №{o['id']} {escape(o['client_name'])} — tayyor deb belgilandi. Rahmat!")
    await call.answer()
    await notify_ready(bot, db, o["id"])


@router.callback_query(MtCb.filter(F.action == "client"))
async def tell_client(call: CallbackQuery, callback_data: MtCb, db: Database, bot: Bot):
    if not await db.is_admin(call.from_user.id):
        await call.answer("Faqat admin uchun.", show_alert=True)
        return
    ok = await send_to_client(bot, db, callback_data.id)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Mijozga yuborildi" if ok else "Mijoz botga ulanmagan", show_alert=not ok)
