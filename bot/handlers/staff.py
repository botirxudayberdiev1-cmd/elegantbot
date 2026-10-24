from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import ROLES
from ..db import Database
from ..filters import IsAdmin
from ..keyboards import (
    BTN_STAFF,
    RoleCb,
    StaffCb,
    admin_menu,
    cancel_kb,
    confirm_delete_staff_kb,
    roles_kb,
    staff_card_kb,
    staff_list_kb,
)
from ..utils import escape, invite_link, normalize_phone

router = Router(name="staff")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class AddStaff(StatesGroup):
    name = State()
    role = State()
    phone = State()


async def staff_list_text(db: Database):
    staff = await db.staff_list()
    if not staff:
        return "👥 <b>Xodimlar</b>\n\nHozircha xodim yo'q.", staff
    linked = sum(1 for s in staff if s["tg_id"])
    return (
        f"👥 <b>Xodimlar</b> — {len(staff)} ta, ulangan: {linked}\n"
        "✅ — botga ulangan, ⏳ — hali ulanmagan",
        staff,
    )


async def staff_card_text(bot: Bot, s) -> str:
    text = (
        f"👤 <b>{escape(s['name'])}</b>\n"
        f"Lavozimi: {ROLES[s['role']]}\n"
        f"Telefon: {escape(s['phone'] or '—')}\n"
    )
    if s["tg_id"]:
        text += "Holati: ✅ botga ulangan"
    else:
        link = await invite_link(bot, "s", s["invite_token"])
        text += (
            "Holati: ⏳ hali ulanmagan\n\n"
            "Quyidagi havolani xodimga yuboring. U bosib «Start»ni bossa, ulanadi:\n"
            f"{link}"
        )
    return text


@router.message(StateFilter(None), F.text == BTN_STAFF)
async def show_staff(message: Message, db: Database):
    text, staff = await staff_list_text(db)
    await message.answer(text, reply_markup=staff_list_kb(staff))


@router.callback_query(StaffCb.filter(F.action == "back"))
async def back_to_list(call: CallbackQuery, db: Database):
    text, staff = await staff_list_text(db)
    await call.message.edit_text(text, reply_markup=staff_list_kb(staff))
    await call.answer()


@router.callback_query(StaffCb.filter(F.action.in_({"view", "link"})))
async def view_staff(call: CallbackQuery, callback_data: StaffCb, db: Database, bot: Bot):
    s = await db.staff_get(callback_data.id)
    if not s:
        await call.answer("Xodim topilmadi", show_alert=True)
        return
    await call.message.edit_text(
        await staff_card_text(bot, s),
        reply_markup=staff_card_kb(s["id"], bool(s["tg_id"])),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(StaffCb.filter(F.action == "relink"))
async def relink_staff(call: CallbackQuery, callback_data: StaffCb, db: Database, bot: Bot):
    # Xodim telefonini almashtirsa yoki noto'g'ri akkaunt ulangan bo'lsa
    await db.staff_new_token(callback_data.id)
    s = await db.staff_get(callback_data.id)
    if not s:
        await call.answer("Xodim topilmadi", show_alert=True)
        return
    await call.message.edit_text(
        await staff_card_text(bot, s),
        reply_markup=staff_card_kb(s["id"], False),
        disable_web_page_preview=True,
    )
    await call.answer("Eski ulanish bekor qilindi, yangi havola tayyor")


@router.callback_query(StaffCb.filter(F.action == "del"))
async def ask_delete_staff(call: CallbackQuery, callback_data: StaffCb, db: Database):
    s = await db.staff_get(callback_data.id)
    if not s:
        await call.answer("Xodim topilmadi", show_alert=True)
        return
    await call.message.edit_text(
        f"<b>{escape(s['name'])}</b> ro'yxatdan o'chirilsinmi?\n"
        "Eski buyurtmalardagi ma'lumotlari saqlanib qoladi.",
        reply_markup=confirm_delete_staff_kb(s["id"]),
    )
    await call.answer()


@router.callback_query(StaffCb.filter(F.action == "delok"))
async def delete_staff(call: CallbackQuery, callback_data: StaffCb, db: Database):
    s = await db.staff_get(callback_data.id)
    if s and s["tg_id"] == call.from_user.id:
        await call.answer("O'zingizni o'chira olmaysiz", show_alert=True)
        return
    await db.staff_deactivate(callback_data.id)
    text, staff = await staff_list_text(db)
    await call.message.edit_text(text, reply_markup=staff_list_kb(staff))
    await call.answer("O'chirildi")


# ---------- Yangi xodim qo'shish ----------

@router.callback_query(StaffCb.filter(F.action == "add"))
async def add_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddStaff.name)
    await call.message.answer("Xodimning ism-familiyasini yozing:", reply_markup=cancel_kb())
    await call.answer()


@router.message(AddStaff.name, F.text)
async def add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not 2 <= len(name) <= 64:
        await message.answer("Ism 2–64 belgi bo'lishi kerak. Qaytadan yozing:")
        return
    await state.update_data(name=name)
    await state.set_state(AddStaff.role)
    await message.answer("Lavozimini tanlang:", reply_markup=roles_kb())


@router.callback_query(AddStaff.role, RoleCb.filter())
async def add_role(call: CallbackQuery, callback_data: RoleCb, state: FSMContext):
    await state.update_data(role=callback_data.role)
    await state.set_state(AddStaff.phone)
    await call.message.edit_text(f"Lavozimi: <b>{ROLES[callback_data.role]}</b>")
    await call.message.answer("Telefon raqamini yozing (masalan: 90 123 45 67):")
    await call.answer()


@router.message(AddStaff.role)
async def add_role_text(message: Message):
    await message.answer("Lavozimni yuqoridagi tugmalardan tanlang.")


@router.message(AddStaff.phone, F.text)
async def add_phone(message: Message, state: FSMContext, db: Database, bot: Bot):
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer("Raqam noto'g'ri. Masalan: 90 123 45 67 yoki +998901234567")
        return
    data = await state.get_data()
    await state.clear()

    staff_id = await db.staff_add(data["name"], data["role"], phone)
    s = await db.staff_get(staff_id)
    await message.answer("✅ Xodim qo'shildi.", reply_markup=admin_menu())
    await message.answer(
        await staff_card_text(bot, s),
        reply_markup=staff_card_kb(s["id"], False),
        disable_web_page_preview=True,
    )
