from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .config import ROLES
from .utils import fmt_money

# ---------- Admin menyusi ----------

BTN_NEW_ORDER = "➕ Yangi buyurtma"
BTN_ORDERS = "📋 Buyurtmalar"
BTN_UPCOMING = "📅 Yaqin tadbirlar"
BTN_DEBTS = "💰 Qarzlar"
BTN_FLASH = "💾 Fleshkalar"
BTN_EDITING = "🎬 Montaj"
BTN_REPORT = "📊 Hisobot"
BTN_STAFF = "👥 Xodimlar"
BTN_EVENT_TYPES = "🎉 Tadbir turlari"
BTN_ADD_OPERATOR = "➕ Operator qo'shish"
BTN_CANCEL = "❌ Bekor qilish"

MENU_BUTTONS = {
    BTN_NEW_ORDER, BTN_ORDERS, BTN_UPCOMING, BTN_DEBTS, BTN_FLASH,
    BTN_EDITING, BTN_REPORT, BTN_STAFF, BTN_EVENT_TYPES, BTN_ADD_OPERATOR,
}

# Keyingi bosqichlarda quriladigan bo'limlar
NOT_READY_BUTTONS = [BTN_UPCOMING, BTN_DEBTS, BTN_FLASH, BTN_EDITING, BTN_REPORT]


def admin_menu() -> ReplyKeyboardMarkup:
    rows = [
        [BTN_NEW_ORDER],
        [BTN_ORDERS, BTN_UPCOMING],
        [BTN_DEBTS, BTN_FLASH],
        [BTN_EDITING, BTN_REPORT],
        [BTN_STAFF, BTN_ADD_OPERATOR],
        [BTN_EVENT_TYPES],
    ]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)


# ---------- Xodimlar ----------

class StaffCb(CallbackData, prefix="st"):
    action: str  # view, add, link, relink, del, delok, back
    id: int = 0


class RoleCb(CallbackData, prefix="role"):
    role: str


def staff_list_kb(staff) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"{'✅' if s['tg_id'] else '⏳'} {s['name']} — {ROLES[s['role']]}",
            callback_data=StaffCb(action="view", id=s["id"]).pack(),
        )]
        for s in staff
    ]
    buttons.append([InlineKeyboardButton(
        text="➕ Xodim qo'shish", callback_data=StaffCb(action="add").pack()
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def staff_card_kb(staff_id: int, linked: bool) -> InlineKeyboardMarkup:
    rows = []
    if linked:
        rows.append([InlineKeyboardButton(
            text="🔄 Qayta ulash (yangi havola)",
            callback_data=StaffCb(action="relink", id=staff_id).pack(),
        )])
    else:
        rows.append([InlineKeyboardButton(
            text="🔗 Ulash havolasi", callback_data=StaffCb(action="link", id=staff_id).pack()
        )])
    rows.append([InlineKeyboardButton(
        text="🗑 O'chirish", callback_data=StaffCb(action="del", id=staff_id).pack()
    )])
    rows.append([InlineKeyboardButton(
        text="⬅️ Ro'yxatga", callback_data=StaffCb(action="back").pack()
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_staff_kb(staff_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha, o'chir", callback_data=StaffCb(action="delok", id=staff_id).pack()),
        InlineKeyboardButton(text="↩️ Yo'q", callback_data=StaffCb(action="view", id=staff_id).pack()),
    ]])


def roles_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=title, callback_data=RoleCb(role=key).pack())]
        for key, title in ROLES.items()
    ])


# ---------- Tadbir turlari ----------

class EventTypeCb(CallbackData, prefix="et"):
    action: str  # add, del, delok, back
    id: int = 0


def event_types_kb(types) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"🗑 {t['name']}", callback_data=EventTypeCb(action="del", id=t["id"]).pack()
        )]
        for t in types
    ]
    rows.append([InlineKeyboardButton(
        text="➕ Tur qo'shish", callback_data=EventTypeCb(action="add").pack()
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_type_kb(type_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha, o'chir", callback_data=EventTypeCb(action="delok", id=type_id).pack()),
        InlineKeyboardButton(text="↩️ Yo'q", callback_data=EventTypeCb(action="back").pack()),
    ]])


# ---------- Yangi buyurtma ----------

SERVICE_PRESETS = ["Video", "Foto", "Dekoratsiya", "Taklifnoma", "Albom"]


class OrdCb(CallbackData, prefix="ord"):
    # svc, svc_other, svc_done, et, op, op_done, loc_skip, decor_skip, ev_more, ev_done, dep0,
    # note_skip, save, view, list
    action: str
    id: int = 0


def _btn(text: str, action: str, id: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=OrdCb(action=action, id=id).pack())


def services_kb(chosen: list[dict]) -> InlineKeyboardMarkup:
    by_name = {s["name"]: s for s in chosen}
    rows = []
    for i, name in enumerate(SERVICE_PRESETS):
        s = by_name.get(name)
        text = f"✅ {name} — {fmt_money(s['price'])}" if s else f"▫️ {name}"
        rows.append([_btn(text, "svc", i)])
    # Qo'lda yozilgan xizmatlar (ro'yxatda yo'qlar) — bosilsa o'chiriladi
    for i, s in enumerate(chosen):
        if s["name"] not in SERVICE_PRESETS:
            rows.append([_btn(f"✅ {s['name']} — {fmt_money(s['price'])}", "svc_rm", i)])
    rows.append([_btn("✍️ Boshqa xizmat", "svc_other")])
    if chosen:
        rows.append([_btn("➡️ Tayyor, davom etish", "svc_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_event_types_kb(types) -> InlineKeyboardMarkup:
    buttons = [_btn(t["name"], "et", t["id"]) for t in types]
    return InlineKeyboardMarkup(inline_keyboard=[buttons[i:i + 2] for i in range(0, len(buttons), 2)])


def operators_kb(operators, selected: list[int], busy: dict[int, list[str]]) -> InlineKeyboardMarkup:
    rows = []
    for op in operators:
        mark = "✅" if op["id"] in selected else "▫️"
        extra = ""
        if op["role"] != "operator":
            extra += f" · {ROLES[op['role']].lower()}"
        if op["id"] in busy:
            extra += f" · band {', '.join(busy[op['id']])}"
        if not op["tg_id"]:
            extra += " · ulanmagan"
        rows.append([_btn(f"{mark} {op['name']}{extra}", "op", op["id"])])
    rows.append([_btn("➕ Yangi operator qo'shish", "op_new")])
    if selected:
        rows.append([_btn(f"➡️ Tayyor ({len(selected)} ta)", "op_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def more_events_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("➕ Yana tadbir qo'shish", "ev_more")],
        [_btn("➡️ Davom etish", "ev_done")],
    ])


def deposit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("Zakalat yo'q", "dep0")]])


def skip_kb(text: str, action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(text, action)]])


def note_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("➖ Izohsiz", "note_skip")]])


def confirm_order_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("✅ Saqlash", "save")]])


def orders_list_kb(orders) -> InlineKeyboardMarkup:
    rows = []
    for o in orders:
        day = o["first_date"][8:10] + "." + o["first_date"][5:7] if o["first_date"] else "—"
        debt = o["total"] - o["paid"]
        tail = f" · qarz {fmt_money(debt)}" if debt > 0 else " · ✅"
        rows.append([_btn(f"№{o['id']} {o['client_name']} · {day}{tail}", "view", o["id"])])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_card_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("⬅️ Ro'yxatga", "list")]])


# ---------- Operator ----------

class AsgCb(CallbackData, prefix="asg"):
    action: str  # yes, no
    id: int


def assignment_kb(asg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Qabul qildim", callback_data=AsgCb(action="yes", id=asg_id).pack()),
        InlineKeyboardButton(text="❌ Bora olmayman", callback_data=AsgCb(action="no", id=asg_id).pack()),
    ]])
