"""Admin menyusidagi ko'rinishlar: yaqin tadbirlar, qarzlar, montaj, fleshkalar, hisobot, saytdan so'rovlar.

Hammasi saytdagi ma'lumotlarning o'zi (bitta baza) — saytda nima bo'lsa, botda ham shu.
"""

import json
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from ..cards import STATUS_ICONS
from ..cash import month_range
from ..db import Database
from ..filters import IsAdmin
from ..keyboards import BTN_DEBTS, BTN_EDITING, BTN_FLASH, BTN_REPORT, BTN_REQUESTS, BTN_UPCOMING
from ..site import SECTION_TITLE
from ..utils import escape, fmt_date, fmt_money, today

router = Router(name="admin_views")
router.message.filter(IsAdmin(), StateFilter(None))

UPCOMING_DAYS = 7
FLASH_DAYS = 14
LIMIT = 3800  # Telegram xabar chegarasi 4096 — biroz zaxira bilan
MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]


def _join(lines: list[str], more: str = "…ro'yxat uzun, to'lig'i saytda.") -> str:
    """Xabar Telegram chegarasidan oshmasin."""
    out, size = [], 0
    for line in lines:
        if size + len(line) > LIMIT:
            out.append(more)
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def _short(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"


@router.message(F.text == BTN_UPCOMING)
async def upcoming(message: Message, db: Database):
    first = today()
    rows = await db.assignments_between(first.isoformat(), (first + timedelta(days=UPCOMING_DAYS)).isoformat())
    events: dict[int, dict] = {}
    for r in rows:
        events.setdefault(r["event_id"], {"row": r, "team": []})["team"].append(r)
    if not events:
        await message.answer(f"📅 Keyingi {UPCOMING_DAYS} kunda tadbir yo'q.")
        return
    lines, day, problems = [f"📅 <b>Yaqin {UPCOMING_DAYS} kun</b>"], None, 0
    for ev in events.values():
        r = ev["row"]
        if r["date"] != day:
            day = r["date"]
            label = " — <b>BUGUN</b>" if day == first.isoformat() else ""
            lines.append(f"\n<b>{fmt_date(day)}</b>{label}")
        team = []
        for m in ev["team"]:
            mark = STATUS_ICONS.get(m["status"], "▫️") + ("⚠️" if not m["staff_tg_id"] else "")
            team.append(f"{mark}{escape(m['staff_name'])}")
            problems += m["status"] in ("kutilmoqda", "rad") or not m["staff_tg_id"]
        lines.append(f"⏰ <b>{escape(r['time'] or '—')}</b> {escape(r['type_name'])} · {escape(r['client_name'])} (№{r['order_id']})\n"
                     f"   📍 {escape(r['address'] or '—')}\n   👥 {', '.join(team)}")
    lines.append(f"\n⚠️ {problems} ta muammo: ⏳ javob yo'q, ❌ rad yoki ⚠️ botga ulanmagan." if problems
                 else "\n✅ Hamma qabul qilgan.")
    await message.answer(_join(lines))


@router.message(F.text == BTN_DEBTS)
async def debts(message: Message, db: Database):
    orders = [o for o in await db.orders_overview() if o["total"] - o["paid"] > 0]
    if not orders:
        await message.answer("💰 Qarzdor yo'q 🎉")
        return
    orders.sort(key=lambda o: o["paid"] - o["total"])
    total = sum(o["total"] - o["paid"] for o in orders)
    lines = [f"💰 <b>Qarzdorlar: {len(orders)} ta</b>\nJami qarz: <b>{fmt_money(total)}</b>\n"]
    for o in orders:
        dates = sorted(e["date"] for e in o["events"])
        lines.append(f"• №{o['id']} <b>{escape(o['client_name'])}</b> — {fmt_money(o['total'] - o['paid'])}\n"
                     f"   {escape(o['client_phone'] or '')}"
                     + (f" · to'y {_short(dates[0])}" if dates else "")
                     + f" · to'lagan {fmt_money(o['paid'])} / {fmt_money(o['total'])}")
    lines.append("\nTo'lov yozish: saytda «Qarzdorlar» bo'limi.")
    await message.answer(_join(lines))


def _stage(o: dict) -> str:
    if o["ready_notified_at"]:
        return "📣 mijozga aytilgan, olib ketishi kutilmoqda"
    if o["editing_done_at"]:
        return "✅ montaj tayyor — mijozga xabar berish kerak"
    if o["editor_id"]:
        return f"🎞 montajda: {escape(o['editor_name'] or '')}"
    return "⚠️ montajchiga berilmagan"


@router.message(F.text == BTN_EDITING)
async def editing(message: Message, db: Database):
    iso = today().isoformat()
    orders = [o for o in await db.orders_overview()
              if not o["delivered_at"] and o["events"] and all(e["date"] < iso for e in o["events"])]
    if not orders:
        await message.answer("🎬 Topshirilmagan to'y yo'q.")
        return
    orders.sort(key=lambda o: min(e["date"] for e in o["events"]))
    waiting = sum(1 for o in orders if not o["editor_id"])
    lines = [f"🎬 <b>Topshirilmagan to'ylar: {len(orders)} ta</b>"
             + (f"\n⚠️ Montajga berilmagan: {waiting} ta" if waiting else "") + "\n"]
    for o in orders:
        last = max(e["date"] for e in o["events"])
        days = (today() - date.fromisoformat(last)).days
        lines.append(f"• №{o['id']} <b>{escape(o['client_name'])}</b> · to'y {_short(last)} ({days} kun oldin)\n   {_stage(o)}")
    lines.append("\nMontajchiga berish va «tayyor» xabari: saytda «Montaj» bo'limi.")
    await message.answer(_join(lines))


@router.message(F.text == BTN_FLASH)
async def flash(message: Message, db: Database):
    end = today()
    rows = await db.flash_pending((end - timedelta(days=FLASH_DAYS)).isoformat(), (end - timedelta(days=1)).isoformat())
    if not rows:
        await message.answer(f"💾 Oxirgi {FLASH_DAYS} kundagi barcha fleshkalar topshirilgan ✅")
        return
    lines, ev = [f"💾 <b>Fleshkasini topshirmaganlar: {len(rows)} ta</b>"], None
    for r in rows:
        if r["event_id"] != ev:
            ev = r["event_id"]
            lines.append(f"\n<b>{_short(r['date'])}</b> {escape(r['type_name'])} · {escape(r['client_name'])} (№{r['order_id']})")
        lines.append(f"   ▫️ {escape(r['staff_name'])}" + ("" if r["staff_tg_id"] else " · ⚠️ botga ulanmagan"))
    lines.append("\nTo'ydan keyingi kuni bot har biriga «Fleshkani topshirdim» tugmasini yuboradi.")
    await message.answer(_join(lines))


@router.message(F.text == BTN_REPORT)
async def report(message: Message, db: Database):
    t = today()
    first, last = (d.isoformat() for d in month_range(t))
    orders = await db.orders_overview()
    month_orders = [o for o in orders if first <= o["created_at"][:10] <= last]
    events = [e for o in orders for e in o["events"] if first <= e["date"] <= last]
    paid = sum(p["amount"] for o in orders for p in o["payments"] if first <= p["paid_at"][:10] <= last)
    cash = await db.cash_entries("biznes", first, last)
    other_in = sum(c["amount"] for c in cash if c["src"] == "cash" and c["kind"] == "kirim" and c["currency"] == "UZS")
    spent = sum(c["amount"] for c in cash if c["kind"] == "chiqim" and c["currency"] == "UZS")
    by_cat: dict[str, int] = {}
    for c in cash:
        if c["kind"] == "chiqim" and c["currency"] == "UZS":
            by_cat[c["category"]] = by_cat.get(c["category"], 0) + c["amount"]
    requests = [r for r in await db.site_requests(500) if first <= r["created_at"][:10] <= last]
    debt = sum(o["total"] - o["paid"] for o in orders if o["total"] > o["paid"])

    lines = [f"📊 <b>Hisobot — {MONTHS[t.month - 1]} {t.year}</b>\n",
             f"📝 Yangi zakazlar: <b>{len(month_orders)} ta</b>, dogovor {fmt_money(sum(o['total'] for o in month_orders))}",
             f"🎉 Shu oydagi tadbirlar: <b>{len(events)} ta</b>",
             f"🌐 Saytdan so'rovlar: {len(requests)} ta"
             + (f" (qabul qilinmagan: {sum(r['status'] == 'yangi' for r in requests)})" if requests else ""),
             "\n<b>Pul (Studiya, so'm)</b>",
             f"➕ Zakaz to'lovlari: {fmt_money(paid)}",
             f"➕ Boshqa kirim: {fmt_money(other_in)}",
             f"➖ Chiqim: {fmt_money(spent)}",
             f"= <b>Qoldi: {fmt_money(paid + other_in - spent)}</b>",
             f"\n💰 Mijozlardagi jami qarz: <b>{fmt_money(debt)}</b>"]
    if by_cat:
        lines.append("\n<b>Chiqim nimalarga ketdi</b>")
        lines += [f"• {escape(k)}: {fmt_money(v)}" for k, v in sorted(by_cat.items(), key=lambda x: -x[1])[:8]]
    await message.answer(_join(lines))


@router.message(F.text == BTN_REQUESTS)
async def requests(message: Message, db: Database):
    rows = [r for r in await db.site_requests(30) if r["status"] == "yangi"]
    if not rows:
        await message.answer("🌐 Saytdan yangi so'rov yo'q. Qabul qilinganlari saytda «So'rovlar» bo'limida.")
        return
    lines = [f"🌐 <b>Qabul qilinmagan so'rovlar: {len(rows)} ta</b>\n"]
    for r in rows:
        d = json.loads(r["data"])
        what = d.get("package") and f"📦 {escape(d['package'])}" or ", ".join(
            f"{SECTION_TITLE.get(i['section'], '')}: {escape(i['title'])}" for i in d.get("items", [])[:4])
        when = next((e["date"] for e in d.get("events", []) if e.get("date")), d.get("date") or "")
        lines.append(f"• №{r['id']} <b>{escape(r['name'])}</b>, {escape(r['phone'])}\n   {what}"
                     + (f" · 📅 {_short(when)}" if when else "") + f" · {escape(r['created_at'][5:16])}")
    lines.append("\nQabul qilish: kelgan xabardagi «✅ Qabul qildim» yoki saytda «So'rovlar».")
    await message.answer(_join(lines))
