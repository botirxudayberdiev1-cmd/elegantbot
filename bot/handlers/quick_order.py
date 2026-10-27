"""Yangi buyurtma bitta xabarda: shablonni to'ldirib yuborish.

Shablon -> (xatolar bo'lsa, tuzatib qayta yuborish) -> har tadbirga lokatsiya -> tekshirish va
saqlash (orders.py dagi show_confirm va save). Qadamma-qadam usul ham saqlanib qolgan.
"""

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import Database
from ..filters import IsAdmin
from ..form import EXAMPLE, TEMPLATE, parse_order
from ..keyboards import BTN_NEW_ORDER, OrdCb, cancel_kb, skip_kb
from ..utils import escape, fmt_date
from . import orders

router = Router(name="quick_order")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class QuickOrder(StatesGroup):
    form = State()
    location = State()


@router.message(StateFilter(None), F.text == BTN_NEW_ORDER)
async def start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(QuickOrder.form)
    await message.answer(
        "🆕 <b>Yangi buyurtma</b>\n\n"
        "Shablonni bosib nusxalang, to'ldirib bitta xabarda yuboring:",
        reply_markup=cancel_kb(),
    )
    await message.answer(f"<pre>{TEMPLATE}</pre>")
    await message.answer(
        f"<b>Namuna:</b>\n<pre>{escape(EXAMPLE)}</pre>\n"
        "• Bir nechta xizmat yoki xodimni vergul bilan yozing.\n"
        "• Ikkinchi tadbir bo'lsa, «Tadbir:» dan boshlab yana yozing (Sana, Soat, Manzil, Xodimlar).\n"
        "• Dekor rasmi bo'lsa — rasmni yuboring, to'ldirilgan shablonni rasm ostiga yozing.\n"
        "• Avans, Dekor, Izoh bo'sh qolsa ham bo'ladi.",
        reply_markup=skip_kb("📝 Qadamma-qadam yozish", "qstep"),
    )


@router.callback_query(QuickOrder.form, OrdCb.filter(F.action == "qstep"))
async def step_by_step(call: CallbackQuery, state: FSMContext):
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await orders.new_order(call.message, state)


@router.message(QuickOrder.form, F.text | F.caption)
async def form(message: Message, state: FSMContext, db: Database):
    photo = message.photo[-1].file_id if message.photo else None
    data, errors = parse_order(
        message.text or message.caption, await db.event_types_list(), await db.staff_list(), photo
    )
    if errors:
        await message.answer(
            "❗️ <b>Tuzatish kerak:</b>\n"
            + "\n".join(f"• {escape(e)}" for e in errors)
            + "\n\nXabaringizni nusxalab, tuzatib qayta yuboring."
        )
        return

    warnings = []
    for ev in data["events"]:
        busy = await db.staff_busy_on(ev["date"])
        for op in ev["ops"]:
            if op["id"] in busy:
                warnings.append(
                    f"{op['name']} {fmt_date(ev['date'])} kuni band: {', '.join(busy[op['id']])}"
                )
    if warnings:
        await message.answer("⚠️ <b>Diqqat:</b>\n" + "\n".join(f"• {escape(w)}" for w in warnings))

    await state.update_data(**data, loc_idx=0)
    await ask_location(message, state)


async def ask_location(message: Message, state: FSMContext):
    data = await state.get_data()
    i = data["loc_idx"]
    if i >= len(data["events"]):
        await orders.show_confirm(message, state)
        return
    ev = data["events"][i]
    await state.set_state(QuickOrder.location)
    await message.answer(
        f"🗺 <b>{escape(ev['type_name'])}</b>, {escape(ev['address'])} — lokatsiyasini yuboring:\n"
        "📎 → «Lokatsiya» (xaritadan joyni tanlang).",
        reply_markup=skip_kb("➖ Lokatsiyasiz", "qloc_skip"),
    )


@router.message(QuickOrder.location, F.location)
async def location(message: Message, state: FSMContext):
    data = await state.get_data()
    ev = data["events"][data["loc_idx"]]
    ev["lat"], ev["lon"] = message.location.latitude, message.location.longitude
    await state.update_data(events=data["events"], loc_idx=data["loc_idx"] + 1)
    await message.answer("🗺 Lokatsiya saqlandi.")
    await ask_location(message, state)


@router.callback_query(QuickOrder.location, OrdCb.filter(F.action == "qloc_skip"))
async def location_skip(call: CallbackQuery, state: FSMContext):
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    data = await state.get_data()
    await state.update_data(loc_idx=data["loc_idx"] + 1)
    await ask_location(call.message, state)
