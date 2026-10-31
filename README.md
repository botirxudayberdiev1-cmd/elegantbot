# Studiya boti

Tadbirlar, operatorlar, to'lovlar va montajni boshqarish uchun Telegram bot va zakaz/qarzdorlar sayti.

## Kompyuterda ishga tushirish

1. `.env.example` faylidan nusxa olib, `.env` deb nomlang.
2. `.env` ichiga `BOT_TOKEN` (@BotFather'dan) va `ADMIN_IDS` (o'zingizning Telegram ID, @userinfobot'dan) ni yozing.
3. `start_bot.cmd` ni ikki marta bosing (yoki `.venv\Scripts\python -m bot`).

Kutubxonalarni qaytadan o'rnatish kerak bo'lsa: `.venv\Scripts\python -m pip install -r requirements.txt`
(Python 3.12 yoki 3.13 kerak; 3.15 da aiogram o'rnatilmaydi.)

Saytni kompyuterda ko'rish: `.env` ga `SITE_PIN=...` va `WEB_PORT=8080` yozing, keyin http://localhost:8080

## Kirim-chiqim (saytda)

Saytda «💰 Kirim-chiqim» tugmasi: **Studiya** va **Shaxsiy** hisob alohida, so'm va $ alohida.
- Katta «➖ Chiqim» / «➕ Kirim» tugmalari: summa → nimaga (tayyor ro'yxat yoki o'zingiz yozasiz) → Saqlash.
- Zakaz to'lovlari Studiya kirimiga o'zi tushadi.
- Bugun / hafta / oy: kirim, chiqim, qoldiq.
- Oylik limit: kategoriya limitdan oshsa saytda va botda ogohlantiradi.

## Render'ga qo'yish (24/7)

1. render.com → **Get Started** → GitHub bilan kirish.
2. **New + → Blueprint** → **elegantbot** repozitoriysini tanlang (`render.yaml` o'zi o'qiladi).
3. So'ralgan qiymatlarni yozing:
   - `BOT_TOKEN` — @BotFather tokeni
   - `ADMIN_IDS` — sizning Telegram ID'ingiz
   - `SITE_PIN` — sayt uchun PIN-kod (kamida 6 ta raqam)
4. **Apply** → karta ma'lumotlarini kiriting (Starter tarif + 1 GB disk).
5. Tayyor bo'lgach, sayt manzili yuqorida chiqadi: `https://elegantbot-….onrender.com`.
6. Kompyuterdagi botni to'xtating (`start_bot.cmd` oynasini yoping): ikkita bot bir vaqtda ishlamaydi.

Bazani ko'chirish: kompyuterdagi botga `/backup` yozing → kelgan faylni Render'dagi botga
«/restore» izohi bilan yuboring. Render botni avtomatik qayta yoqadi.

## Railway'ga qo'yish (24/7)

1. railway.com → GitHub bilan kirish → **New Project → Deploy from GitHub repo → elegantbot**.
2. Servisda **Settings → Volumes → Add Volume**, Mount path: `/data` (baza o'chib ketmasligi uchun).
3. **Variables** bo'limiga:
   - `BOT_TOKEN` — @BotFather tokeni
   - `ADMIN_IDS` — sizning Telegram ID'ingiz
   - `DB_PATH` = `/data/bot.db`
   - `TIMEZONE` = `Asia/Tashkent`
   - `SITE_PIN` — sayt uchun PIN-kod (kamida 6 ta raqam)
4. **Settings → Networking → Generate Domain** — sayt manzili shu bo'ladi.
5. Kompyuterdagi botni to'xtating (`start_bot.cmd` oynasini yoping): ikkita bot bir vaqtda ishlamaydi.

Bazani ko'chirish: kompyuterdagi botga `/backup` yozing → kelgan faylni Railway'dagi botga
«/restore» izohi bilan yuboring. Railway botni avtomatik qayta yoqadi.

## Bosqichlar

- [x] 1. Bot, xodimlar, ularni havola orqali ulash, tadbir turlari
- [x] 2. Buyurtma yozish, operatorga xabar, «Qabul qildim / Bora olmayman»
- [ ] 3. Operator tugmalari
- [ ] 4. To'lov va qarz — saytda to'lov kiritish ✅; botda ⏳
- [ ] 5. Eslatmalar — xodimlarga tadbirdan oldin va adminga ertangi ro'yxat ✅; fleshka ⏳
- [x] 6. Montaj va mijozga xabarlar (saytdan: montajchiga berish, «tayyor», mijozga xabar, topshirildi)
- [ ] 7. Hisobot
- [x] 8. Serverga qo'yish (Railway)

## Tuzilma

```
bot/
  __main__.py        — ishga tushirish (bot + eslatmalar + sayt)
  config.py          — sozlamalar (.env)
  db.py              — SQLite bazasi va so'rovlar
  keyboards.py       — tugmalar
  filters.py         — admin tekshiruvi
  utils.py           — telefon, pul, sana, havola, adminga xabar
  cards.py           — buyurtma va tadbir kartalari matni
  notify.py          — xodimga karta yuborish (dekor rasmi, lokatsiya)
  reminders.py       — eslatmalar (vaqtlari config.py da)
  form.py            — bitta xabarli buyurtma shablonini o'qish
  web.py             — sayt: yangi zakaz, montaj, qarzdorlar (SITE_PIN bilan)
  montaj.py          — montajchiga to'y, mijozga «to'yingiz tayyor»
  handlers/
    start.py         — /start va havola orqali ulanish
    admin.py         — menyu, bekor qilish
    backup.py        — /backup va /restore
    staff.py         — Xodimlar bo'limi
    event_types.py   — Tadbir turlari bo'limi
    quick_order.py   — Yangi buyurtma bitta xabarda (shablon)
    orders.py        — Yangi buyurtma qadamma-qadam va Buyurtmalar ro'yxati
    operator.py      — xodim javobi (Qabul qildim / Bora olmayman)
    montaj.py        — montajchining «Montaj tayyor» tugmasi, mijozga xabar tugmasi
data/bot.db          — baza (o'zi yaratiladi)
railway.json         — Railway: ishga tushirish buyrug'i va tekshiruv
```
