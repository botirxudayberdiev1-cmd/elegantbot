"""Eslatmalar: xodimlarga tadbirdan oldin va adminga ertangi ishlar ro'yxati.

Har CHECK_EVERY soniyada tekshiriladi. Har eslatma reminders jadvaliga yoziladi,
shuning uchun bot qayta ishga tushsa ham ikki marta ketmaydi. Bot o'chiq paytda
o'tib ketgan eslatma (masalan, kechki 18:00) bot yoqilgach QUIET_FROM gacha yuboriladi.
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta

from aiogram import Bot

from .cards import STATUS_ICONS, assignment_text
from .config import (
    ADMIN_SUMMARY_AT, CHECK_EVERY, DEKOR_MORNING_AT, DEKOR_UNTIL, EVENING_AT,
    HOURS_BEFORE, QUIET_FROM,
)
from .db import Database
from .keyboards import assignment_kb
from .notify import send_card
from .utils import TZ, escape, fmt_date, notify_admins, now

log = logging.getLogger(__name__)


def _at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(day, time(h, m), TZ)


def work_day(a) -> date:
    """Dekorator tadbirdan bir kun oldin ishlaydi, qolganlar — tadbir kuni."""
    d = date.fromisoformat(a["date"])
    return d - timedelta(days=1) if a["role"] == "dekorator" else d


def due_reminders(a, t: datetime) -> list[tuple[str, date, str]]:
    """Shu paytda yuborilishi kerak bo'lgan eslatmalar: [(tur, kun, sarlavha)]."""
    wd = work_day(a)
    eve = wd - timedelta(days=1)
    due = []
    if _at(eve, EVENING_AT) <= t < _at(eve, QUIET_FROM):
        title = (
            f"🔔 <b>Eslatma: ertaga dekor qo'yish kerak</b>\n"
            f"Tadbir {fmt_date(a['date'])} — dekor bir kun oldin tayyor bo'lishi kerak."
            if a["role"] == "dekorator"
            else "🔔 <b>Eslatma: ertaga tadbiringiz bor</b>"
        )
        due.append(("kun_oldin", eve, title))

    if a["role"] == "dekorator":
        start, end = _at(wd, DEKOR_MORNING_AT), _at(wd, DEKOR_UNTIL)
        title = (
            "🎀 <b>Bugun dekoratsiya bor!</b>\nErtangi tadbir uchun. Rasmdagidek qilib, "
            "ishni oxirigacha tugatib keling. Savol bo'lsa — mijozga qo'ng'iroq qiling."
        )
    elif a["time"]:
        end = _at(wd, a["time"])
        start = end - timedelta(hours=HOURS_BEFORE)
        title = f"⏰ <b>Bugun soat {a['time']} da tadbir — vaqtida yetib boring!</b>"
    else:
        return due
    if start <= t < end:
        due.append(("ish_kuni", wd, title))
    return due


def admin_summary_text(tomorrow: date, rows) -> str | None:
    """Ertangi tadbirlar va ertaga dekor qo'yiladigan (indingi) tadbirlar. Ish bo'lmasa — None."""
    events: dict[int, dict] = {}
    dekor: dict[int, dict] = {}
    for r in rows:
        if r["date"] == tomorrow.isoformat():
            target = events
        elif r["role"] == "dekorator" and r["date"] == (tomorrow + timedelta(days=1)).isoformat():
            target = dekor
        else:
            continue
        ev = target.setdefault(r["event_id"], {"row": r, "team": []})
        ev["team"].append(r)
    if not events and not dekor:
        return None

    problems = 0

    def team_lines(team) -> list[str]:
        nonlocal problems
        out = []
        for m in team:
            line = f"   {STATUS_ICONS.get(m['status'], '▫️')} {escape(m['staff_name'])}"
            if m["role"] != "operator":
                line += f" ({m['role']})"
            if not m["staff_tg_id"]:
                line += " · ⚠️ botga ulanmagan"
            if m["status"] in ("kutilmoqda", "rad") or not m["staff_tg_id"]:
                problems += 1
            out.append(line)
        return out

    lines = [f"📋 <b>Ertangi ishlar — {fmt_date(tomorrow.isoformat())}</b>"]
    for ev in events.values():
        r = ev["row"]
        lines.append(
            f"\n<b>{escape(r['type_name'])}</b>, ⏰ {r['time']}, 📍 {escape(r['address'])}\n"
            f"   Mijoz: {escape(r['client_name'])} (№{r['order_id']})"
        )
        lines += team_lines(ev["team"])
    if dekor:
        lines.append("\n🎀 <b>Ertaga dekor qo'yiladi</b> (indingi tadbirlar uchun):")
        for ev in dekor.values():
            r = ev["row"]
            lines.append(f"\n{escape(r['type_name'])}, 📍 {escape(r['address'])}, mijoz {escape(r['client_name'])}")
            lines += team_lines(ev["team"])
    lines.append(
        f"\n⚠️ E'tibor bering: {problems} kishi bilan muammo (⏳ javob bermagan, ❌ bora olmaydi, ulanmagan)."
        if problems else "\n✅ Hamma qabul qilgan."
    )
    return "\n".join(lines)


async def check(bot: Bot, db: Database, t: datetime | None = None) -> None:
    t = t or now()
    today = t.date()
    rows = await db.assignments_between(today.isoformat(), (today + timedelta(days=2)).isoformat())

    for a in rows:
        if a["status"] == "rad" or not a["staff_tg_id"]:
            continue
        for kind, day, title in due_reminders(a, t):
            if not await db.reminder_claim(kind, a["id"], day.isoformat()):
                continue
            team = await db.event_team(a["event_id"])
            kb = assignment_kb(a["id"]) if a["status"] == "kutilmoqda" else None
            try:
                await send_card(bot, a, f"{title}\n\n{assignment_text(a, team)}", kb)
            except Exception as e:  # xodim botni bloklagan bo'lishi mumkin
                log.warning("Eslatma (%s) %s ga yuborilmadi: %s", kind, a["staff_name"], e)

    if _at(today, ADMIN_SUMMARY_AT) <= t < _at(today, QUIET_FROM):
        if await db.reminder_claim("admin_kun", 0, today.isoformat()):
            text = admin_summary_text(today + timedelta(days=1), rows)
            if text:
                await notify_admins(bot, db, text)


async def reminder_loop(bot: Bot, db: Database) -> None:
    while True:
        try:
            await check(bot, db)
        except Exception:
            log.exception("Eslatmalarni tekshirishda xato")
        await asyncio.sleep(CHECK_EVERY)
