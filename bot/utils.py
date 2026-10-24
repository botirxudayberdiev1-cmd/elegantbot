import logging
import re
from datetime import date, datetime, timedelta
from html import escape as _html_escape
from zoneinfo import ZoneInfo

from aiogram import Bot

from .config import TIMEZONE
from .db import Database

log = logging.getLogger(__name__)
TZ = ZoneInfo(TIMEZONE)
WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]


def escape(text: str) -> str:
    # Telegram HTML uchun faqat < > & yetarli; apostrof (to'y, Navro'z) o'z holicha qoladi
    return _html_escape(str(text), quote=False)


def now() -> datetime:
    return datetime.now(TZ)


def today() -> date:
    return now().date()


def fmt_money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"


def parse_money(text: str) -> int | None:
    """'5 000 000', '5mln', '5,5 mln', '500 ming', '500k', '0' -> so'mda butun son."""
    t = text.lower().replace("so'm", "").replace("сум", "").replace("sum", "").strip()
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(mln|million|m|ming|k)?", t.replace(" ", ""))
    if m:
        num, unit = m.groups()
        if unit:
            value = float(num.replace(",", "."))
            value *= 1_000_000 if unit in ("mln", "million", "m") else 1_000
            return int(round(value))
    digits = re.sub(r"[\s.,]", "", t)
    return int(digits) if digits.isdigit() else None


def parse_date(text: str) -> date | None:
    """'25.10', '25.10.2026', '25/10/26', 'bugun', 'ertaga'."""
    t = text.strip().lower()
    if t == "bugun":
        return today()
    if t == "ertaga":
        return today() + timedelta(days=1)
    m = re.fullmatch(r"(\d{1,2})[./\-\s](\d{1,2})(?:[./\-\s](\d{2,4}))?", t)
    if not m:
        return None
    day, month, year = int(m[1]), int(m[2]), m[3]
    try:
        if year:
            y = int(year)
            return date(y + 2000 if y < 100 else y, month, day)
        d = date(today().year, month, day)
        # Yil yozilmasa va sana o'tib ketgan bo'lsa — keyingi yil
        return d if d >= today() else date(today().year + 1, month, day)
    except ValueError:
        return None


def parse_time(text: str) -> str | None:
    """'18:00', '18.30', '18', '1830' -> 'HH:MM'."""
    t = text.strip().replace(".", ":").replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?", t)
    if not m:
        return None
    h, mi = int(m[1]), int(m[2] or 0)
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%d.%m.%Y} ({WEEKDAYS[d.weekday()]})"


def normalize_phone(text: str) -> str | None:
    """'90 123 45 67', '+998901234567' kabi yozuvlarni '+998901234567' ko'rinishiga keltiradi."""
    digits = re.sub(r"\D", "", text)
    if digits.startswith("00"):  # 00998... xalqaro yozuv
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("0"):  # 0901234567
        digits = digits[1:]
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return "+" + digits
    # Chet el raqamlari (Rossiya, Qozog'iston...) — faqat "+" bilan yozilsa
    if text.strip().startswith("+") and 10 <= len(digits) <= 15 and not digits.startswith("998"):
        return "+" + digits
    return None


async def invite_link(bot: Bot, prefix: str, token: str) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start={prefix}_{token}"


async def notify_admins(bot: Bot, db: Database, text: str, **kwargs) -> None:
    for tg_id in await db.admin_tg_ids():
        try:
            await bot.send_message(tg_id, text, **kwargs)
        except Exception as e:  # admin botni hali ochmagan bo'lishi mumkin
            log.warning("Adminga (%s) xabar yuborilmadi: %s", tg_id, e)


__all__ = [
    "escape", "normalize_phone", "invite_link", "notify_admins", "now", "today",
    "fmt_money", "parse_money", "parse_date", "parse_time", "fmt_date",
]
