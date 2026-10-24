from aiogram import Bot, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from ..config import ROLES
from ..db import Database
from ..keyboards import admin_menu
from ..utils import escape, notify_admins

router = Router(name="start")


@router.message(CommandStart(deep_link=True))
async def start_with_link(
    message: Message, command: CommandObject, db: Database, bot: Bot, state: FSMContext
):
    await state.clear()
    arg = command.args or ""

    if arg.startswith("s_"):
        await link_staff(message, arg[2:], db, bot)
    else:
        # Mijoz havolalari (o_...) 6-bosqichda qo'shiladi
        await message.answer("Havola noto'g'ri yoki eskirgan.")


async def link_staff(message: Message, token: str, db: Database, bot: Bot):
    user = message.from_user
    staff = await db.staff_by_token(token)
    if not staff:
        await message.answer("Havola noto'g'ri yoki eskirgan. Admindan yangi havola so'rang.")
        return

    if staff["tg_id"] == user.id:
        await message.answer(f"Siz allaqachon ulangansiz, {escape(staff['name'])}.")
        return
    if staff["tg_id"]:
        await message.answer("Bu havola boshqa akkauntga ulangan. Admindan yangi havola so'rang.")
        return

    other = await db.staff_by_tg(user.id)
    if other:
        await message.answer(
            f"Bu Telegram akkaunt allaqachon <b>{escape(other['name'])}</b> nomiga ulangan."
        )
        return

    await db.staff_link(staff["id"], user.id)
    role = ROLES[staff["role"]]
    is_admin = await db.is_admin(user.id)
    await message.answer(
        f"✅ Xush kelibsiz, <b>{escape(staff['name'])}</b>!\n"
        f"Siz <b>{role}</b> sifatida ulandingiz.\n\n"
        + ("Quyidagi menyudan foydalaning." if is_admin
           else "Sizga biriktirilgan tadbirlar shu yerga keladi."),
        reply_markup=admin_menu() if is_admin else ReplyKeyboardRemove(),
    )

    username = f" (@{escape(user.username)})" if user.username else ""
    await notify_admins(
        bot, db,
        f"🔗 <b>{escape(staff['name'])}</b> ({role}) botga ulandi{username}.",
    )


@router.message(CommandStart())
async def start_plain(message: Message, db: Database, state: FSMContext):
    await state.clear()
    user = message.from_user

    if await db.is_admin(user.id):
        await message.answer(
            f"Assalomu alaykum, {escape(user.first_name)}! Bosh menyu:",
            reply_markup=admin_menu(),
        )
        return

    staff = await db.staff_by_tg(user.id)
    if staff:
        await message.answer(
            f"Assalomu alaykum, <b>{escape(staff['name'])}</b>!\n"
            f"Siz {ROLES[staff['role']]} sifatida ro'yxatdasiz. "
            "Sizga biriktirilgan ishlar shu yerga keladi.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await message.answer(
        "Assalomu alaykum! Bu bot studiya xodimlari va mijozlari uchun.\n"
        "Ulanish uchun admin bergan maxsus havolani bosing."
    )
