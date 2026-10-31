from aiogram import Bot, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from ..config import ROLES
from ..db import Database
from ..keyboards import BTN_MY_JOBS, admin_menu, staff_menu
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
    elif arg.startswith("o_"):
        await link_client(message, arg[2:], db, bot)
    else:
        await message.answer("Havola noto'g'ri yoki eskirgan.")


async def link_client(message: Message, token: str, db: Database, bot: Bot):
    """Mijoz o'z zakazi havolasini bosdi — tayyor bo'lganda bot unga o'zi xabar beradi."""
    order = await db.order_by_client_token(token)
    if not order:
        await message.answer("Havola noto'g'ri yoki eskirgan.")
        return
    await db.order_link_client(order["id"], message.from_user.id)
    await message.answer(
        f"Assalomu alaykum, {escape(order['client_name'])}! 🎬\n"
        f"Elegant Media studiyasi: zakazingiz №{order['id']} qabul qilingan.\n"
        "Ishingiz tayyor bo'lganda shu yerga xabar beramiz.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await notify_admins(
        bot, db, f"👤 Mijoz <b>{escape(order['client_name'])}</b> (№{order['id']}) botga ulandi."
    )


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
           else f"Sizga biriktirilgan tadbirlar shu yerga keladi. Ro'yxatni ko'rish: «{BTN_MY_JOBS}»."),
        reply_markup=admin_menu() if is_admin else staff_menu(staff["role"]),
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
            f"Sizga biriktirilgan ishlar shu yerga keladi. Ro'yxatni ko'rish: «{BTN_MY_JOBS}».",
            reply_markup=staff_menu(staff["role"]),
        )
        return

    await message.answer(
        "Assalomu alaykum! Bu bot studiya xodimlari va mijozlari uchun.\n"
        "Ulanish uchun admin bergan maxsus havolani bosing."
    )
