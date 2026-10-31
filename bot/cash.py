"""Kirim-chiqim: kategoriyalar, valyutalar va davrlar (bugun / hafta / oy).

Saytdagi «Kirim-chiqim» bo'limi (web.py) shu funksiyalardan foydalanadi.
Zakaz to'lovlari (payments jadvali) Studiya kirimiga o'zi qo'shiladi — bu yerda qayta yozilmaydi.
"""

from datetime import date, timedelta

from .utils import fmt_money

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
