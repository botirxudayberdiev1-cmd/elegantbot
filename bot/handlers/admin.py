from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..filters import IsAdmin
from ..keyboards import BTN_CANCEL, NOT_READY_BUTTONS, admin_menu

router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(StateFilter("*"), Command("cancel"))
@router.message(StateFilter("*"), F.text == BTN_CANCEL)
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=admin_menu())


@router.message(Command("menu"))
async def menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bosh menyu:", reply_markup=admin_menu())


@router.message(StateFilter(None), F.text.in_(NOT_READY_BUTTONS))
async def not_ready(message: Message):
    await message.answer("⏳ Bu bo'lim keyingi bosqichlarda qo'shiladi.")


# Oxirgi router: admin hech qaysi bo'limga tushmaydigan narsa yozsa
fallback_router = Router(name="admin_fallback")
fallback_router.message.filter(IsAdmin())


@fallback_router.message(StateFilter(None))
async def unknown(message: Message):
    await message.answer("Tushunmadim. Menyudan tanlang:", reply_markup=admin_menu())


@fallback_router.message()
async def unknown_in_state(message: Message):
    await message.answer(
        "So'ralgan ma'lumotni yozing yoki tugmalardan foydalaning.\n"
        "Bekor qilish uchun «❌ Bekor qilish»."
    )
