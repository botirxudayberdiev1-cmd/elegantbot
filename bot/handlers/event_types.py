from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import Database
from ..filters import IsAdmin
from ..keyboards import (
    BTN_EVENT_TYPES,
    EventTypeCb,
    admin_menu,
    cancel_kb,
    confirm_delete_type_kb,
    event_types_kb,
)
from ..utils import escape

router = Router(name="event_types")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class AddEventType(StatesGroup):
    name = State()


async def types_text(db: Database):
    types = await db.event_types_list()
    names = "\n".join(f"• {escape(t['name'])}" for t in types) or "Hozircha yo'q."
    return f"🎉 <b>Tadbir turlari</b>\n\n{names}\n\nO'chirish uchun nomini bosing.", types


@router.message(StateFilter(None), F.text == BTN_EVENT_TYPES)
async def show_types(message: Message, db: Database):
    text, types = await types_text(db)
    await message.answer(text, reply_markup=event_types_kb(types))


@router.callback_query(EventTypeCb.filter(F.action == "back"))
async def back(call: CallbackQuery, db: Database):
    text, types = await types_text(db)
    await call.message.edit_text(text, reply_markup=event_types_kb(types))
    await call.answer()


@router.callback_query(EventTypeCb.filter(F.action == "del"))
async def ask_delete(call: CallbackQuery, callback_data: EventTypeCb, db: Database):
    t = await db.event_type_get(callback_data.id)
    if not t:
        await call.answer("Topilmadi", show_alert=True)
        return
    await call.message.edit_text(
        f"«{escape(t['name'])}» turi o'chirilsinmi?\n"
        "Eski buyurtmalardagi tadbirlar o'zgarmaydi.",
        reply_markup=confirm_delete_type_kb(t["id"]),
    )
    await call.answer()


@router.callback_query(EventTypeCb.filter(F.action == "delok"))
async def delete(call: CallbackQuery, callback_data: EventTypeCb, db: Database):
    await db.event_type_deactivate(callback_data.id)
    text, types = await types_text(db)
    await call.message.edit_text(text, reply_markup=event_types_kb(types))
    await call.answer("O'chirildi")


@router.callback_query(EventTypeCb.filter(F.action == "add"))
async def add_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddEventType.name)
    await call.message.answer("Yangi tadbir turining nomini yozing:", reply_markup=cancel_kb())
    await call.answer()


@router.message(AddEventType.name, F.text)
async def add_name(message: Message, state: FSMContext, db: Database):
    name = message.text.strip()
    if not 2 <= len(name) <= 40:
        await message.answer("Nom 2–40 belgi bo'lishi kerak. Qaytadan yozing:")
        return
    if not await db.event_type_add(name):
        await message.answer("Bu tur allaqachon bor. Boshqa nom yozing:")
        return
    await state.clear()
    await message.answer(f"✅ «{escape(name)}» qo'shildi.", reply_markup=admin_menu())
    text, types = await types_text(db)
    await message.answer(text, reply_markup=event_types_kb(types))
