"""Bazaning nusxasi: /backup — bot bazani fayl qilib yuboradi; o'sha faylni «/restore» izohi bilan
qaytarib yuborsangiz, bot uni tiklab, qayta ishga tushadi (kompyuterdan Railway'ga ko'chirish uchun)."""

import asyncio
import logging
import os
import sqlite3
import tempfile
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import FSInputFile, Message

from ..config import DB_PATH
from ..db import Database
from ..filters import IsAdmin

log = logging.getLogger(__name__)
router = Router(name="backup")
router.message.filter(IsAdmin())

RESTORE_PATH = DB_PATH + ".restore"
NEEDED_TABLES = {"staff", "orders", "events", "assignments", "payments"}


@router.message(StateFilter("*"), Command("backup"))
async def backup(message: Message, db: Database):
    path = os.path.join(tempfile.gettempdir(), f"bot-{datetime.now():%Y%m%d-%H%M}.db")
    if os.path.exists(path):
        os.remove(path)
    await db.conn.execute("VACUUM INTO ?", (path,))  # yozilayotgan paytda ham butun nusxa
    await message.answer_document(
        FSInputFile(path),
        caption="💾 Baza nusxasi. Boshqa joyda tiklash: shu faylni «/restore» izohi bilan botga yuboring.",
    )
    os.remove(path)


@router.message(StateFilter("*"), F.document, F.caption == "/restore")
async def restore(message: Message, bot: Bot):
    if not (message.document.file_name or "").endswith(".db"):
        await message.answer("Bu baza fayli emas (.db bo'lishi kerak).")
        return
    await bot.download(message.document, destination=RESTORE_PATH)
    try:
        with sqlite3.connect(RESTORE_PATH) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or not NEEDED_TABLES <= tables:
                raise ValueError
    except Exception:
        os.remove(RESTORE_PATH)
        await message.answer("❌ Fayl buzilgan yoki bu botning bazasi emas. Hech narsa o'zgarmadi.")
        return
    await message.answer("✅ Baza qabul qilindi. Bot qayta ishga tushyapti — 15–30 soniyadan keyin /start bosing.")
    log.warning("Baza tiklanadi, bot qayta ishga tushiriladi")
    # Database.connect() keyingi ishga tushishda .restore faylini asosiy baza o'rniga qo'yadi.
    # Xato kodi bilan chiqamiz — Railway ham, start_bot.cmd ham botni qayta yoqadi.
    asyncio.get_running_loop().call_later(1, os._exit, 3)
