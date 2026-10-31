"""Saytdan kelgan so'rov: admin «✅ Qabul qildim» bosadi — kim olgani boshqa adminlarga ham ko'rinadi."""

from aiogram import Bot, Router
from aiogram.types import CallbackQuery

from ..db import Database
from ..site import SrCb
from ..utils import escape, notify_admins

router = Router(name="site_requests")


@router.callback_query(SrCb.filter())
async def take_request(call: CallbackQuery, callback_data: SrCb, db: Database, bot: Bot):
    if not await db.is_admin(call.from_user.id):
        await call.answer("Faqat admin uchun.", show_alert=True)
        return
    staff = await db.staff_by_tg(call.from_user.id)
    who = staff["name"] if staff else call.from_user.full_name
    if not await db.site_request_take(callback_data.id, who):
        req = await db.site_request_get(callback_data.id)
        await call.answer(f"Allaqachon qabul qilingan: {req['taken_by'] if req else '—'}", show_alert=True)
        await call.message.edit_reply_markup(reply_markup=None)
        return
    await call.message.edit_text(
        call.message.html_text + f"\n\n✅ <b>Qabul qildi: {escape(who)}</b>", reply_markup=None
    )
    await call.answer("Qabul qilindi")
    req = await db.site_request_get(callback_data.id)
    await notify_admins(bot, db, f"✅ So'rov №{req['id']} ({escape(req['name'])}) — <b>{escape(who)}</b> qabul qildi.")
