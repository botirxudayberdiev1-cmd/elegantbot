"""Srochne foto: to'ydan keyin sotuvchi nechta rasm sotganini yozadi — summa (soni × narx) Kassaga tushadi.

«📸 Savdo yozish» tugmasi → tadbirni tanlash → rasm soni. Qayta yozilsa, avvalgisi almashtiriladi.
"""

from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..db import Database
from ..keyboards import BTN_SALE, staff_menu
from ..utils import escape, fmt_money, notify_admins, today

router = Router(name="sales")
SALE_DAYS = 3  # oxirgi necha kundagi tadbirlar uchun yozish mumkin


class SaleCb(CallbackData, prefix="sale"):
    action: str  # start, ev
    id: int = 0


class Sale(StatesGroup):
    count = State()


def sale_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📸 Savdo yozish", callback_data=SaleCb(action="start").pack())
    ]])


async def _sales_staff(db: Database, tg_id: int):
    staff = await db.staff_by_tg(tg_id)
    return staff if staff and staff["role"] == "srochnefoto" else None


async def _choose(db: Database, staff, answer) -> None:
    t = today()
    rows = await db.sale_events(staff["id"], (t - timedelta(days=SALE_DAYS)).isoformat(), t.isoformat())
    if not rows:
        await answer(f"Oxirgi {SALE_DAYS} kunda sizga biriktirilgan tadbir yo'q.", reply_markup=staff_menu(staff["role"]))
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=f"{r['date'][8:10]}.{r['date'][5:7]} {r['type_name']} · {r['client_name']}"
             + (f" ✅ {r['count']} ta" if r["count"] is not None else ""),
        callback_data=SaleCb(action="ev", id=r["event_id"]).pack())] for r in rows])
    await answer("📸 Qaysi tadbirning savdosini yozasiz?", reply_markup=kb)


@router.message(F.text == BTN_SALE)
async def sale_button(message: Message, db: Database, state: FSMContext):
    staff = await _sales_staff(db, message.from_user.id)
    if not staff:
        return
    await state.clear()
    await _choose(db, staff, message.answer)


@router.callback_query(SaleCb.filter(F.action == "start"))
async def sale_from_reminder(call: CallbackQuery, db: Database, state: FSMContext):
    staff = await _sales_staff(db, call.from_user.id)
    if not staff:
        await call.answer("Bu tugma srochne fotochilar uchun.", show_alert=True)
        return
    await state.clear()
    await call.answer()
    await _choose(db, staff, call.message.answer)


@router.callback_query(SaleCb.filter(F.action == "ev"))
async def sale_event(call: CallbackQuery, callback_data: SaleCb, db: Database, state: FSMContext):
    staff = await _sales_staff(db, call.from_user.id)
    t = today()
    rows = await db.sale_events(staff["id"], (t - timedelta(days=SALE_DAYS)).isoformat(), t.isoformat()) if staff else []
    ev = next((r for r in rows if r["event_id"] == callback_data.id), None)
    if not ev:
        await call.answer("Bu tadbir topilmadi yoki muddati o'tgan.", show_alert=True)
        return
    await state.set_state(Sale.count)
    await state.update_data(event_id=ev["event_id"])
    await call.message.edit_text(
        f"📸 {escape(ev['type_name'])}, {ev['date'][8:10]}.{ev['date'][5:7]}, {escape(ev['client_name'])}\n\n"
        "<b>Nechta rasm sotdingiz?</b> Faqat sonini yozing, masalan: 34"
    )
    await call.answer()


@router.message(Sale.count, F.text)
async def sale_count(message: Message, db: Database, state: FSMContext, bot: Bot):
    staff = await _sales_staff(db, message.from_user.id)
    text = message.text.strip().replace(" ", "")
    if not staff or not text.isdigit() or int(text) > 5000:
        await message.answer("Rasm sonini raqam bilan yozing, masalan: 34")
        return
    count = int(text)
    data = await state.get_data()
    await state.clear()
    t = today()
    ev = next((r for r in await db.sale_events(staff["id"], (t - timedelta(days=SALE_DAYS)).isoformat(), t.isoformat())
               if r["event_id"] == data.get("event_id")), None)
    if not ev:
        await message.answer("Tadbir topilmadi. Qaytadan «📸 Savdo yozish» ni bosing.", reply_markup=staff_menu(staff["role"]))
        return
    price = int(await db.setting_get("foto_narx", "0") or 0)
    what = f"{ev['type_name']}, {ev['date'][8:10]}.{ev['date'][5:7]}, {ev['client_name']} (№{ev['order_id']})"
    amount = await db.sale_save(ev["event_id"], staff["id"], count, price,
                                f"№{ev['order_id']} · {ev['client_name']} · {staff['name']} · {count} ta", ev["date"])
    again = " (avvalgi yozuv almashtirildi)" if ev["count"] is not None else ""
    if price:
        await message.answer(f"✅ Yozildi{again}: <b>{count} ta × {fmt_money(price)} = {fmt_money(amount)}</b>\n"
                             f"{escape(what)}\nPulni adminga topshiring.", reply_markup=staff_menu(staff["role"]))
        await notify_admins(bot, db, f"📸 <b>{escape(staff['name'])}</b> savdo yozdi{again}: {count} ta × "
                                     f"{fmt_money(price)} = <b>{fmt_money(amount)}</b>\n{escape(what)}")
    else:
        await message.answer(f"✅ Yozildi: {count} ta rasm. Narx hali belgilanmagan — admin belgilaydi.",
                             reply_markup=staff_menu(staff["role"]))
        await notify_admins(bot, db, f"📸 <b>{escape(staff['name'])}</b>: {count} ta rasm sotdi ({escape(what)}).\n"
                                     "⚠️ Rasm narxi belgilanmagan: saytda «👷 Maosh» → Srochne foto narxi.")
