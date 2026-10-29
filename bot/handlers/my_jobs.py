"""Xodim uchun «📅 Mening ishlarim»: bugungi va keyingi tadbirlar, montajchiga — montajdagi to'ylar.

Xodim botga istalgan savol yozsa ham (masalan, «bugun to'y qayerda»), shu ro'yxat qaytariladi.
"""

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.types import Message

from ..db import Database
from ..keyboards import staff_menu
from ..utils import escape, fmt_date, today

router = Router(name="my_jobs")
STATUS = {"kutilmoqda": "⏳ javob bermagansiz", "qabul": "✅ qabul qilgansiz",
          "keldi": "📍 yetib kelgansiz", "tugatdi": "🏁 tugatgansiz"}
MAX_SHOWN = 15


async def jobs_text(db: Database, staff) -> str:
    lines = [f"📅 <b>{escape(staff['name'])}, sizning ishlaringiz</b>"]
    jobs = await db.staff_jobs(staff["id"], today().isoformat())
    day = None
    for j in jobs[:MAX_SHOWN]:
        if j["date"] != day:
            day = j["date"]
            label = " — <b>BUGUN</b>" if day == today().isoformat() else ""
            lines.append(f"\n<b>{fmt_date(day)}</b>{label}")
        team = [t["name"] for t in await db.event_team(j["event_id"])
                if t["name"] != staff["name"] and t["status"] != "rad"]
        lines.append(
            f"⏰ <b>{escape(j['time'] or '—')}</b> · {escape(j['type_name'])}\n"
            f"   📍 {escape(j['address'] or '—')}\n"
            f"   👤 {escape(j['client_name'])}, {escape(j['client_phone'] or '')}"
            + (f"\n   👥 Birga: {escape(', '.join(team))}" if team else "")
            + (f"\n   🎀 {escape(j['decor_note'])}" if staff["role"] == "dekorator" and j["decor_note"] else "")
            + (f"\n   🗺 https://maps.google.com/?q={j['lat']},{j['lon']}" if j["lat"] is not None else "")
            + f"\n   {STATUS.get(j['status'], '')}"
        )
    if len(jobs) > MAX_SHOWN:
        lines.append(f"\n…yana {len(jobs) - MAX_SHOWN} ta tadbir bor.")
    if staff["role"] == "montajchi":
        edits = await db.editor_jobs(staff["id"])
        if edits:
            lines.append("\n🎞 <b>Montajdagi to'ylar</b>")
            lines += [f"• №{e['id']} {escape(e['client_name'])} — {escape(e['types'] or '')}"
                      f"{', ' + fmt_date(e['first_date']) if e['first_date'] else ''}" for e in edits]
    if len(lines) == 1:
        lines.append("\nHozircha sizga biriktirilgan ish yo'q.")
    return "\n".join(lines)


class IsStaff(Filter):
    """Botga ulangan xodim (admin emas). Mos kelsa, handlerga `staff` beriladi."""

    async def __call__(self, message: Message, db: Database) -> bool | dict:
        if await db.is_admin(message.from_user.id):
            return False
        staff = await db.staff_by_tg(message.from_user.id)
        return {"staff": staff} if staff else False


router.message.filter(IsStaff())


# Tugma, /ishlarim yoki istalgan matn («bugun to'y qayerda») — o'z ishlari ro'yxati
@router.message(F.text)
async def my_jobs(message: Message, db: Database, staff):
    await message.answer(await jobs_text(db, staff), reply_markup=staff_menu(), disable_web_page_preview=True)
