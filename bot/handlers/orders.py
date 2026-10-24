from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..cards import order_text
from ..db import Database
from ..filters import IsAdmin
from ..keyboards import (
    BTN_NEW_ORDER,
    BTN_ORDERS,
    SERVICE_PRESETS,
    OrdCb,
    admin_menu,
    cancel_kb,
    confirm_order_kb,
    deposit_kb,
    more_events_kb,
    note_kb,
    operators_kb,
    order_card_kb,
    order_event_types_kb,
    orders_list_kb,
    services_kb,
)
from ..notify import send_assignment
from ..utils import (
    escape,
    fmt_date,
    fmt_money,
    normalize_phone,
    parse_date,
    parse_money,
    parse_time,
    today,
)

router = Router(name="orders")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

MONEY_HINT = "Masalan: 5 000 000, 5 mln yoki 500 ming"


class NewOrder(StatesGroup):
    client_name = State()
    client_phone = State()
    services = State()
    service_name = State()
    service_price = State()
    ev_type = State()
    ev_date = State()
    ev_time = State()
    ev_address = State()
    ev_ops = State()
    ev_pay = State()
    ev_next = State()
    deposit = State()
    note = State()
    confirm = State()


# Qoralama FSM ichida shunday saqlanadi:
# client_name, client_phone, services: [{name, price}], events: [{type_id, type_name, date,
# time, address, ops: [{id, name, pay}]}], deposit, note
# cur — hozir yozilayotgan tadbir, pending_svc — narxi so'ralayotgan xizmat


# ---------- 1. Mijoz ----------

@router.message(StateFilter(None), F.text == BTN_NEW_ORDER)
async def new_order(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(services=[], events=[])
    await state.set_state(NewOrder.client_name)
    await message.answer("🆕 <b>Yangi buyurtma</b>\n\nMijozning ismi:", reply_markup=cancel_kb())


@router.message(NewOrder.client_name, F.text)
async def client_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 64:
        await message.answer("Ism 2–64 belgi bo'lishi kerak. Qaytadan yozing:")
        return
    await state.update_data(client_name=name)
    await state.set_state(NewOrder.client_phone)
    await message.answer("Mijozning telefon raqami:")


@router.message(NewOrder.client_phone, F.text)
async def client_phone(message: Message, state: FSMContext):
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer("Raqam noto'g'ri. Masalan: 90 123 45 67 yoki +998901234567")
        return
    await state.update_data(client_phone=phone)
    await ask_services(message, state)


# ---------- 2. Xizmatlar ----------

async def ask_services(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(NewOrder.services)
    await message.answer(
        "Xizmatlarni tanlang. Tanlaganingizdan keyin narxini so'rayman.\n"
        "Tanlangan xizmatni qayta bossangiz, o'chadi.",
        reply_markup=services_kb(data["services"]),
    )


@router.callback_query(NewOrder.services, OrdCb.filter(F.action == "svc"))
async def svc_toggle(call: CallbackQuery, callback_data: OrdCb, state: FSMContext):
    name = SERVICE_PRESETS[callback_data.id]
    services = (await state.get_data())["services"]
    if any(s["name"] == name for s in services):
        services = [s for s in services if s["name"] != name]
        await state.update_data(services=services)
        await call.message.edit_reply_markup(reply_markup=services_kb(services))
        await call.answer(f"{name} olib tashlandi")
        return
    await state.update_data(pending_svc=name)
    await state.set_state(NewOrder.service_price)
    await call.message.answer(f"<b>{name}</b> narxi?\n{MONEY_HINT}")
    await call.answer()


@router.callback_query(NewOrder.services, OrdCb.filter(F.action == "svc_rm"))
async def svc_remove(call: CallbackQuery, callback_data: OrdCb, state: FSMContext):
    services = (await state.get_data())["services"]
    if callback_data.id < len(services):
        services.pop(callback_data.id)
    await state.update_data(services=services)
    await call.message.edit_reply_markup(reply_markup=services_kb(services))
    await call.answer("Olib tashlandi")


@router.callback_query(NewOrder.services, OrdCb.filter(F.action == "svc_other"))
async def svc_other(call: CallbackQuery, state: FSMContext):
    await state.set_state(NewOrder.service_name)
    await call.message.answer("Xizmat nomini yozing:")
    await call.answer()


@router.message(NewOrder.service_name, F.text)
async def svc_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 40:
        await message.answer("Nom 2–40 belgi bo'lishi kerak:")
        return
    await state.update_data(pending_svc=name)
    await state.set_state(NewOrder.service_price)
    await message.answer(f"<b>{escape(name)}</b> narxi?\n{MONEY_HINT}")


@router.message(NewOrder.service_price, F.text)
async def svc_price(message: Message, state: FSMContext):
    price = parse_money(message.text)
    if price is None:
        await message.answer(f"Summani tushunmadim. {MONEY_HINT}")
        return
    data = await state.get_data()
    services = [s for s in data["services"] if s["name"] != data["pending_svc"]]
    services.append({"name": data["pending_svc"], "price": price})
    await state.update_data(services=services, pending_svc=None)
    await ask_services(message, state)


@router.callback_query(NewOrder.services, OrdCb.filter(F.action == "svc_done"))
async def svc_done(call: CallbackQuery, state: FSMContext, db: Database):
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await ask_event_type(call.message, state, db)


# ---------- 3. Tadbirlar ----------

async def ask_event_type(message: Message, state: FSMContext, db: Database):
    data = await state.get_data()
    n = len(data["events"]) + 1
    await state.update_data(cur={})
    await state.set_state(NewOrder.ev_type)
    await message.answer(
        f"<b>{n}-tadbir.</b> Turini tanlang:",
        reply_markup=order_event_types_kb(await db.event_types_list()),
    )


@router.callback_query(NewOrder.ev_type, OrdCb.filter(F.action == "et"))
async def ev_type(call: CallbackQuery, callback_data: OrdCb, state: FSMContext, db: Database):
    t = await db.event_type_get(callback_data.id)
    if not t:
        await call.answer("Bu tur o'chirilgan", show_alert=True)
        return
    await state.update_data(cur={"type_id": t["id"], "type_name": t["name"]})
    await state.set_state(NewOrder.ev_date)
    await call.message.edit_text(f"Tadbir: <b>{escape(t['name'])}</b>")
    await call.message.answer("Sanasi? Masalan: 25.10, 25.10.2026 yoki ertaga")
    await call.answer()


@router.message(NewOrder.ev_date, F.text)
async def ev_date(message: Message, state: FSMContext):
    d = parse_date(message.text)
    if not d:
        await message.answer("Sanani tushunmadim. Masalan: 25.10 yoki 25.10.2026")
        return
    if d < today():
        await message.answer("Bu sana o'tib ketgan. Boshqa sana yozing:")
        return
    data = await state.get_data()
    await state.update_data(cur={**data["cur"], "date": d.isoformat()})
    await state.set_state(NewOrder.ev_time)
    await message.answer(f"📅 {fmt_date(d.isoformat())}\n\nSoat nechida? Masalan: 18:00")


@router.message(NewOrder.ev_time, F.text)
async def ev_time(message: Message, state: FSMContext):
    t = parse_time(message.text)
    if not t:
        await message.answer("Vaqtni tushunmadim. Masalan: 18:00 yoki 9:30")
        return
    data = await state.get_data()
    await state.update_data(cur={**data["cur"], "time": t})
    await state.set_state(NewOrder.ev_address)
    await message.answer("Manzili? (to'yxona nomi yoki aniq manzil)")


@router.message(NewOrder.ev_address, F.text)
async def ev_address(message: Message, state: FSMContext, db: Database):
    address = message.text.strip()
    if len(address) < 2:
        await message.answer("Manzilni yozing:")
        return
    data = await state.get_data()
    cur = {**data["cur"], "address": address, "op_ids": []}
    await state.update_data(cur=cur)

    operators = await db.operators_list()
    if not operators:
        await message.answer(
            "⚠️ Ro'yxatda operator yo'q. Avval «👥 Xodimlar» bo'limida operator qo'shing.\n"
            "Hozircha bu tadbir operatorsiz saqlanadi."
        )
        await finish_event(message, state)
        return
    await state.set_state(NewOrder.ev_ops)
    await message.answer(
        "Operatorlarni tanlang (bir nechtasini tanlash mumkin):",
        reply_markup=operators_kb(operators, [], await busy_for(db, data, cur["date"])),
    )


async def busy_for(db: Database, data: dict, day: str) -> dict[int, list[str]]:
    """Bazadagi band operatorlar + shu buyurtmaning o'zida shu kunga yozilganlar."""
    busy = await db.staff_busy_on(day)
    for ev in data["events"]:
        if ev["date"] == day:
            for op in ev["ops"]:
                busy.setdefault(op["id"], []).append(ev["time"])
    return busy


@router.callback_query(NewOrder.ev_ops, OrdCb.filter(F.action == "op"))
async def ev_op_toggle(call: CallbackQuery, callback_data: OrdCb, state: FSMContext, db: Database):
    data = await state.get_data()
    cur = data["cur"]
    ids = cur["op_ids"]
    if callback_data.id in ids:
        ids.remove(callback_data.id)
    else:
        ids.append(callback_data.id)
    await state.update_data(cur=cur)
    await call.message.edit_reply_markup(reply_markup=operators_kb(
        await db.operators_list(), ids, await busy_for(db, data, cur["date"])
    ))
    await call.answer()


@router.callback_query(NewOrder.ev_ops, OrdCb.filter(F.action == "op_done"))
async def ev_ops_done(call: CallbackQuery, state: FSMContext, db: Database):
    data = await state.get_data()
    cur = data["cur"]
    ops = []
    for op_id in cur["op_ids"]:
        s = await db.staff_get(op_id)
        if s:
            ops.append({"id": s["id"], "name": s["name"], "pay": None})
    cur["ops"] = ops
    await state.update_data(cur=cur)
    names = ", ".join(escape(o["name"]) for o in ops)
    await call.message.edit_text(f"👥 Operatorlar: <b>{names}</b>")
    await call.answer()
    await ask_next_pay(call.message, state)


async def ask_next_pay(message: Message, state: FSMContext):
    cur = (await state.get_data())["cur"]
    pending = next((o for o in cur["ops"] if o["pay"] is None), None)
    if pending is None:
        await finish_event(message, state)
        return
    await state.set_state(NewOrder.ev_pay)
    await message.answer(f"<b>{escape(pending['name'])}</b> uchun ish haqi?\n{MONEY_HINT}")


@router.message(NewOrder.ev_pay, F.text)
async def ev_pay(message: Message, state: FSMContext):
    pay = parse_money(message.text)
    if pay is None:
        await message.answer(f"Summani tushunmadim. {MONEY_HINT}")
        return
    cur = (await state.get_data())["cur"]
    next(o for o in cur["ops"] if o["pay"] is None)["pay"] = pay
    await state.update_data(cur=cur)
    await ask_next_pay(message, state)


async def finish_event(message: Message, state: FSMContext):
    data = await state.get_data()
    cur = data["cur"]
    event = {
        "type_id": cur["type_id"],
        "type_name": cur["type_name"],
        "date": cur["date"],
        "time": cur["time"],
        "address": cur["address"],
        "ops": cur.get("ops", []),
    }
    events = data["events"] + [event]
    await state.update_data(events=events, cur={})
    await state.set_state(NewOrder.ev_next)

    ops = "\n".join(f"   • {escape(o['name'])} — {fmt_money(o['pay'])}" for o in event["ops"])
    await message.answer(
        f"✅ <b>{len(events)}-tadbir yozildi:</b> {escape(event['type_name'])}\n"
        f"📅 {fmt_date(event['date'])}, ⏰ {event['time']}\n"
        f"📍 {escape(event['address'])}\n{ops}",
        reply_markup=more_events_kb(),
    )


@router.callback_query(NewOrder.ev_next, OrdCb.filter(F.action == "ev_more"))
async def ev_more(call: CallbackQuery, state: FSMContext, db: Database):
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await ask_event_type(call.message, state, db)


@router.callback_query(NewOrder.ev_next, OrdCb.filter(F.action == "ev_done"))
async def ev_done(call: CallbackQuery, state: FSMContext):
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    data = await state.get_data()
    total = sum(s["price"] for s in data["services"])
    await state.set_state(NewOrder.deposit)
    await call.message.answer(
        f"💵 Jami: <b>{fmt_money(total)}</b>\n\nZakalat qancha olindi?",
        reply_markup=deposit_kb(),
    )


# ---------- 4. Zakalat va izoh ----------

@router.message(NewOrder.deposit, F.text)
async def deposit(message: Message, state: FSMContext):
    amount = parse_money(message.text)
    if amount is None:
        await message.answer(f"Summani tushunmadim. {MONEY_HINT}")
        return
    data = await state.get_data()
    total = sum(s["price"] for s in data["services"])
    if amount > total:
        await message.answer(
            f"Zakalat jami summadan ({fmt_money(total)}) ko'p bo'lishi mumkin emas. Qaytadan yozing:"
        )
        return
    await state.update_data(deposit=amount)
    await ask_note(message, state)


@router.callback_query(NewOrder.deposit, OrdCb.filter(F.action == "dep0"))
async def deposit_none(call: CallbackQuery, state: FSMContext):
    await state.update_data(deposit=0)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await ask_note(call.message, state)


async def ask_note(message: Message, state: FSMContext):
    await state.set_state(NewOrder.note)
    await message.answer(
        "Izoh bormi? (masalan: kelin tomondan chiqish, dron kerak...)", reply_markup=note_kb()
    )


@router.message(NewOrder.note, F.text)
async def note(message: Message, state: FSMContext):
    await state.update_data(note=message.text.strip()[:500])
    await show_confirm(message, state)


@router.callback_query(NewOrder.note, OrdCb.filter(F.action == "note_skip"))
async def note_skip(call: CallbackQuery, state: FSMContext):
    await state.update_data(note=None)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    await show_confirm(call.message, state)


# ---------- 5. Tekshirish va saqlash ----------

async def show_confirm(message: Message, state: FSMContext):
    await state.set_state(NewOrder.confirm)
    data = await state.get_data()
    await message.answer(
        order_text(data, "📋 <b>Buyurtmani tekshiring</b>")
        + "\n\nHammasi to'g'rimi? Xato bo'lsa, «❌ Bekor qilish» bosib qaytadan yozing.",
        reply_markup=confirm_order_kb(),
    )


@router.callback_query(NewOrder.confirm, OrdCb.filter(F.action == "save"))
async def save(call: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    data = await state.get_data()
    await state.clear()
    order_id, asg_ids = await db.order_create(data, call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Saqlandi")

    # Har bir operatorga tadbir kartasi
    sent, failed = [], []
    for asg_id in asg_ids:
        a = await db.assignment_info(asg_id)
        label = f"{a['staff_name']} ({a['type_name']}, {a['date'][8:10]}.{a['date'][5:7]})"
        (sent if await send_assignment(bot, db, asg_id) else failed).append(label)

    report = f"✅ <b>Buyurtma №{order_id} saqlandi.</b>"
    if sent:
        report += "\n\n📨 Xabar yuborildi:\n" + "\n".join(f"• {escape(s)}" for s in sent)
    if failed:
        report += (
            "\n\n⚠️ Xabar bormadi (botga ulanmagan):\n"
            + "\n".join(f"• {escape(s)}" for s in failed)
            + "\nUlarni «👥 Xodimlar» bo'limidagi havola orqali ulang."
        )
    await call.message.answer(report, reply_markup=admin_menu())


# ---------- Buyurtmalar ro'yxati ----------

async def orders_list_view(db: Database):
    orders = await db.orders_recent()
    if not orders:
        return (
            "📋 Hozircha saqlangan buyurtma yo'q.\n"
            "«➕ Yangi buyurtma» orqali yozing va oxirida «✅ Saqlash» tugmasini bosing.",
            None,
        )
    return "📋 <b>Oxirgi buyurtmalar</b>", orders_list_kb(orders)


@router.message(StateFilter(None), F.text == BTN_ORDERS)
async def show_orders(message: Message, db: Database):
    text, kb = await orders_list_view(db)
    await message.answer(text, reply_markup=kb)


@router.callback_query(OrdCb.filter(F.action == "list"))
async def back_to_orders(call: CallbackQuery, db: Database):
    text, kb = await orders_list_view(db)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(OrdCb.filter(F.action == "view"))
async def view_order(call: CallbackQuery, callback_data: OrdCb, db: Database):
    d = await db.order_full(callback_data.id)
    if not d:
        await call.answer("Buyurtma topilmadi", show_alert=True)
        return
    await call.message.edit_text(
        order_text(d, f"📋 <b>Buyurtma №{d['id']}</b>"), reply_markup=order_card_kb()
    )
    await call.answer()


# Eski (bosqichi o'tib ketgan) tugmalar bosilsa
@router.callback_query(OrdCb.filter())
async def stale_button(call: CallbackQuery):
    await call.answer("Bu tugma eskirgan.", show_alert=True)


# Tugma kutilayotgan joyda matn yozilsa yoki matn o'rniga rasm/stiker yuborilsa
@router.message(StateFilter(NewOrder))
async def unexpected_input(message: Message):
    await message.answer(
        "Iltimos, yuqoridagi xabardagi tugmalardan foydalaning yoki so'ralgan ma'lumotni "
        "matn bilan yozing.\nBekor qilish uchun «❌ Bekor qilish»."
    )
