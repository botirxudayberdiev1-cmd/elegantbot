"""Montaj va mijoz xabarlari: to'yni montajchiga berish, tayyor bo'lgach mijozga xabar."""

import logging

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .db import Database
from .utils import escape, fmt_date, fmt_money, invite_link, notify_admins

log = logging.getLogger(__name__)


class MtCb(CallbackData, prefix="mt"):
    action: str  # done — montajchi: tayyor; client — admin: mijozga xabar
    id: int      # buyurtma ID


def _kb(text: str, action: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data=MtCb(action=action, id=order_id).pack())
    ]])


def _what(o) -> str:
    return " · ".join(x for x in (o["types"], o["services"]) if x)


def client_ready_text(o) -> str:
    text = (
        f"Assalomu alaykum, {o['client_name']}! Elegant Media studiyasidan bezovta qilyapmiz. "
        f"To'yingiz ({o['types'] or 'tadbir'}) tayyor bo'ldi — studiyamizdan olib ketishingiz mumkin."
    )
    if o["debt"] > 0:
        text += f" Qolgan to'lov: {fmt_money(o['debt'])}."
    return text + " Rahmat!"


async def client_link(bot: Bot, o) -> str:
    """Mijoz shu havolani bossa, botga ulanadi va «tayyor» xabarini bot o'zi yuboradi."""
    return await invite_link(bot, "o", o["client_token"])


async def send_to_editor(bot: Bot, db: Database, order_id: int) -> bool:
    o = await db.order_brief(order_id)
    if not o or not o["editor_tg_id"]:
        return False
    text = (
        f"🎞 <b>Montajga to'y: №{o['id']}</b>\n\n"
        f"👤 {escape(o['client_name'])}\n"
        f"🎬 {escape(_what(o))}\n"
        f"📅 {fmt_date(o['first_date']) if o['first_date'] else '—'}\n"
        + (f"📝 {escape(o['note'])}\n" if o["note"] else "")
        + "\nMontaj tugagach, pastdagi tugmani bosing."
    )
    try:
        await bot.send_message(o["editor_tg_id"], text, reply_markup=_kb("✅ Montaj tayyor", "done", order_id))
        return True
    except Exception as e:
        log.warning("Montajchiga (%s) yuborilmadi: %s", o["editor_name"], e)
        return False


async def notify_ready(bot: Bot, db: Database, order_id: int) -> None:
    """Montaj tayyor — adminlarga «mijozga xabar berish» tugmasi bilan."""
    o = await db.order_brief(order_id)
    who = f" ({escape(o['editor_name'])})" if o["editor_name"] else ""
    await notify_admins(
        bot, db,
        f"✅ <b>Montaj tayyor</b>{who}: №{o['id']} {escape(o['client_name'])} — {escape(_what(o))}",
        reply_markup=_kb("📨 Mijozga «to'yingiz tayyor»", "client", order_id) if o["client_tg_id"] else None,
    )


async def send_to_client(bot: Bot, db: Database, order_id: int) -> bool:
    """Mijoz botga ulangan bo'lsa — «to'yingiz tayyor» xabari. Ulanmagan bo'lsa — False."""
    o = await db.order_brief(order_id)
    if not o or not o["client_tg_id"]:
        return False
    try:
        await bot.send_message(o["client_tg_id"], escape(client_ready_text(o)))
    except Exception as e:
        log.warning("Mijozga (%s) yuborilmadi: %s", o["client_name"], e)
        return False
    await db.order_stamp(order_id, "ready_notified_at")
    return True
