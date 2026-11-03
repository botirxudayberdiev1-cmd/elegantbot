"""Elegant Media mobil ilovasidan kelgan buyurtma: mijoz tayyor matnni botga yuboradi.

Bot matnni o'qib «So'rovlar»ga yozadi (saytdagi so'rov bilan bir xil), adminlarga «✅ Qabul qildim»
tugmasi bilan yuboradi va mijozga javob beradi. Mijozning Telegram'i so'rovda saqlanadi —
shu so'rovdan zakaz yozilsa, mijoz zakazga o'zi ulanadi («To'yingiz tayyor» xabari unga boradi).
"""

import json
import re

from aiogram import Bot, F, Router
from aiogram.filters import Filter
from aiogram.types import Message

from ..db import Database
from ..site import send_request
from ..utils import escape, normalize_phone, notify_admins, parse_date

router = Router(name="app_orders")
HEADER = "🎬 Yangi buyurtma"
SECTIONS = {"dekorlar": "dekorlar", "taklifnomalar": "taklifnomalar", "albomlar": "albomlar"}


def parse_app_order(text: str) -> dict | None:
    """Ilova yuborgan matn → so'rov ma'lumoti (site_requests.data bilan bir xil tuzilish)."""
    lines = [line.strip() for line in text.splitlines()]
    if not lines or not lines[0].startswith(HEADER):
        return None
    d = {"name": "", "phone": "", "telegram": "", "package": "", "addons": [], "events": [], "date": "",
         "items": [], "note": "", "source": "ilova"}
    note_from = None
    for i, line in enumerate(lines[1:], 1):
        if line.startswith("👤"):
            name, _, phone = line[1:].strip().rpartition(",")
            d["name"], d["phone"] = (name or phone).strip()[:80], phone.strip()[:30]
        elif line.startswith("📦"):
            d["package"] = line.split(":", 1)[-1].strip()[:40]
        elif line.startswith("➕"):
            d["addons"] = [a.strip()[:40] for a in line.split(":", 1)[-1].split(",") if a.strip()][:15]
        elif line.startswith("🎉"):
            parts = [p.strip() for p in line[1:].split("·")]
            ev = {"type": parts[0][:40], "date": "", "time": "", "address": ""}
            if len(parts) > 1:
                m = re.match(r"(\d{1,2}\.\d{1,2}\.\d{4})\s*(\d{1,2}:\d{2})?", parts[1])
                if m:
                    day = parse_date(m[1])
                    ev["date"], ev["time"] = (day.isoformat() if day else ""), (m[2] or "")
            if len(parts) > 2:
                ev["address"] = parts[2].replace("📍", "").strip()[:150]
            d["events"].append(ev)
        elif line.startswith("•") and ":" in line:
            title, _, name = line[1:].partition(":")
            section = SECTIONS.get(title.strip().lower())
            if section:
                d["items"].append({"section": section, "title": name.strip()[:100], "src": ""})
        elif line.startswith("📝"):
            note_from = i
            break
    if note_from is not None:
        d["note"] = "\n".join([lines[note_from][1:].strip(), *lines[note_from + 1:]]).strip()[:1000]
    if not d["name"] or not d["phone"]:
        return None
    d["phone"] = normalize_phone(d["phone"]) or d["phone"]
    return d


@router.message(F.text.startswith(HEADER))
async def app_order(message: Message, db: Database, bot: Bot):
    d = parse_app_order(message.text)
    if not d:
        await message.answer("Buyurtma matnini o'qib bo'lmadi. Ilovadan qaytadan yuboring yoki qo'ng'iroq qiling.")
        return
    user = message.from_user
    if user.username:
        d["telegram"] = "@" + user.username
    req_id = await db.site_request_add("buyurtma", d["name"], d["phone"], json.dumps(d, ensure_ascii=False),
                                       client_tg_id=user.id)
    await send_request(bot, db, req_id, "buyurtma", d)
    await message.answer(
        f"✅ Rahmat, {escape(d['name'])}! Buyurtmangiz qabul qilindi (№{req_id}).\n"
        "Menejerimiz tez orada siz bilan bog'lanadi. Ishingiz tayyor bo'lganda shu yerga xabar beramiz."
    )


class IsStranger(Filter):
    """Admin ham, xodim ham emas — mijoz yoki begona odam."""

    async def __call__(self, message: Message, db: Database) -> bool:
        uid = message.from_user.id
        return not await db.is_admin(uid) and not await db.staff_by_tg(uid)


# Ilovadan kelmagan oddiy xabar — adminlarga yetkaziladi (mijoz yo'qolib qolmasin)
@router.message(IsStranger(), F.text)
async def stranger(message: Message, db: Database, bot: Bot):
    user = message.from_user
    who = escape(user.full_name) + (f" (@{escape(user.username)})" if user.username else "")
    await notify_admins(bot, db, f"💬 <b>Mijozdan xabar</b> — {who}:\n{escape(message.text[:1500])}")
    await message.answer(
        "Assalomu alaykum! Xabaringiz studiyaga yetkazildi, tez orada javob beramiz.\n"
        "Buyurtma berish uchun Elegant Media ilovasidagi «Telegram orqali yuborish» tugmasidan foydalaning."
    )
