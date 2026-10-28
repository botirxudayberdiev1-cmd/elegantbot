"""Kirim-chiqim: kategoriyalar, davrlar va tezkor qatorni («-150000 benzin») tushunish.

Saytdagi «Kirim-chiqim» bo'limi (web.py) shu funksiyalardan foydalanadi.
Zakaz to'lovlari (payments jadvali) Studiya kirimiga o'zi qo'shiladi — bu yerda qayta yozilmaydi.
"""

import re
from datetime import date, timedelta

from .utils import fmt_money, parse_money

BOOKS = {"biznes": "Studiya", "shaxsiy": "Shaxsiy"}
CURRENCIES = {"UZS": "so'm", "USD": "$"}

# Tayyor kategoriyalar; o'zingiz yozgan kategoriyalar ham keyin shu ro'yxatga qo'shilib ko'rinadi
CATEGORIES = {
    ("biznes", "chiqim"): ["Operatorlarga maosh", "Ijara", "Texnika", "Benzin", "Reklama", "Ovqat",
                           "Kommunal to'lovlar", "Boshqa"],
    ("biznes", "kirim"): ["Boshqa kirim"],
    ("shaxsiy", "chiqim"): ["Oziq-ovqat", "Kommunal to'lovlar", "Transport", "Kiyim", "Sog'liq", "Bolalar",
                            "Boshqa"],
    ("shaxsiy", "kirim"): ["Maosh", "Studiyadan", "Boshqa kirim"],
}
DEFAULT_CATEGORY = {"chiqim": "Boshqa", "kirim": "Boshqa kirim"}

PERIODS = {"day": "Bugun", "week": "Hafta", "month": "Oy"}

_CYR = dict(zip("абвгдежзийклмнопрстуфхцчшщъыьэюяўқғҳё", [
    "a", "b", "v", "g", "d", "e", "j", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u",
    "f", "x", "ts", "ch", "sh", "sh", "'", "i", "", "e", "yu", "ya", "o'", "q", "g'", "h", "yo",
]))


def latin(text: str) -> str:
    """Kirillni lotinga (faqat solishtirish uchun): 'Бензин' -> 'benzin'. Apostroflar bir xil bo'ladi."""
    t = re.sub(r"[ʻʼ’‘`]", "'", text.lower())
    return "".join(_CYR.get(ch, ch) for ch in t)


def fmt_cur(amount: int, currency: str) -> str:
    if currency == "USD":
        return ("-" if amount < 0 else "") + "$" + f"{abs(amount):,}".replace(",", " ")
    return fmt_money(amount)


def period_range(period: str, day: date) -> tuple[date, date]:
    if period == "day":
        return day, day
    if period == "week":
        monday = day - timedelta(days=day.weekday())
        return monday, monday + timedelta(days=6)
    return month_range(day)


def month_range(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


AMOUNT_RE = re.compile(
    r"([+-])\s*(\$)?\s*(\d[\d\s.,]*)\s*(mln|million|ming|k|m)?\s*(\$|usd|dollar|so'm|sum)?"
)


def match_category(text: str, names: list[str]) -> tuple[str | None, str]:
    """Matn boshidagi kategoriyani topadi: ('Benzin', qolgan izoh) yoki (None, butun matn)."""
    low = latin(text)
    for name in sorted(names, key=len, reverse=True):  # «Kommunal to'lovlar» «Kommunal»dan oldin
        n = latin(name)
        if low == n or low.startswith(n + " "):
            return name, text[len(name):].strip()
    first = low.split(" ", 1)[0]
    if len(first) >= 3:
        for name in names:
            if any(w.startswith(first) for w in latin(name).split()):
                return name, text.split(" ", 1)[1].strip() if " " in text else ""
    return None, text


def parse_quick(text: str, categories: dict[str, list[str]]) -> dict | None:
    """'-150000 benzin', '+2 mln to'y Aliyev', '-$50 reklama', '-50 dollar reklama' -> yozuv.

    categories: {"kirim": [...], "chiqim": [...]} — shu kitobdagi kategoriyalar.
    """
    words = text.split()
    # Boshidagi eng uzun «summa» qismini topamiz; qolgani — kategoriya va izoh (yozilgandek saqlanadi)
    for k in range(len(words), 0, -1):
        m = AMOUNT_RE.fullmatch(latin(" ".join(words[:k])))
        if m:
            break
    else:
        return None
    sign, dollar_before, num, unit, cur = m.groups()
    amount = parse_money(num + (unit or ""))
    if not amount:
        return None
    kind = "kirim" if sign == "+" else "chiqim"
    currency = "USD" if dollar_before or cur in ("$", "usd", "dollar") else "UZS"
    rest = " ".join(words[k:])
    category, note = match_category(rest, categories.get(kind, []))
    return {"kind": kind, "amount": amount, "currency": currency,
            "category": category or DEFAULT_CATEGORY[kind], "note": note if category else rest}
