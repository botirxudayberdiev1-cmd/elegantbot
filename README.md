# Studiya boti

Tadbirlar, operatorlar, to'lovlar va montajni boshqarish uchun Telegram bot.

## Ishga tushirish

1. `.env.example` faylidan nusxa olib, `.env` deb nomlang.
2. `.env` ichiga `BOT_TOKEN` (@BotFather'dan) va `ADMIN_IDS` (o'zingizning Telegram ID, @userinfobot'dan) ni yozing.
3. Botni ishga tushiring:

```
.venv\Scripts\python -m bot
```

Kutubxonalarni qaytadan o'rnatish kerak bo'lsa: `.venv\Scripts\python -m pip install -r requirements.txt`
(Python 3.12 yoki 3.13 kerak; 3.15 da aiogram o'rnatilmaydi.)

## Bosqichlar

- [x] 1. Bot, xodimlar, ularni havola orqali ulash, tadbir turlari
- [x] 2. Buyurtma yozish, operatorga xabar, «Qabul qildim / Bora olmayman»
- [ ] 3. Operator tugmalari
- [ ] 4. To'lov va qarz
- [ ] 5. Eslatmalar — xodimlarga tadbirdan oldin va adminga ertangi ro'yxat ✅; fleshka ⏳
- [ ] 6. Montaj va mijozga xabarlar
- [ ] 7. Hisobot
- [ ] 8. Serverga qo'yish

## Tuzilma

```
bot/
  __main__.py        — ishga tushirish
  config.py          — sozlamalar (.env)
  db.py              — SQLite bazasi (8 ta jadval) va so'rovlar
  keyboards.py       — tugmalar
  filters.py         — admin tekshiruvi
  utils.py           — telefon, pul, sana, havola, adminga xabar
  cards.py           — buyurtma va tadbir kartalari matni
  notify.py          — operatorga karta yuborish
  reminders.py       — eslatmalar (vaqtlari config.py da)
  handlers/
    start.py         — /start va havola orqali ulanish
    admin.py         — menyu, bekor qilish
    staff.py         — Xodimlar bo'limi
    event_types.py   — Tadbir turlari bo'limi
    orders.py        — Yangi buyurtma va Buyurtmalar ro'yxati
    operator.py      — operator tugmalari
data/bot.db          — baza (o'zi yaratiladi)
```
