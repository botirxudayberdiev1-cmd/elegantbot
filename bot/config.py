import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()
}
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tashkent")

# Sayt (zakaz va qarzdorlar): Railway PORT beradi; kompyuterda WEB_PORT=8080 qilib sinash mumkin
WEB_PORT = int(os.getenv("PORT") or os.getenv("WEB_PORT") or 0)
SITE_PIN = os.getenv("SITE_PIN", "").strip()
# Ochiq sayt rasmlari/videolari va sozlamalari (Render'da diskka: /data/media)
SITE_MEDIA = os.getenv("SITE_MEDIA", "").strip()

ROLES = {
    "admin": "Admin",
    "operator": "Operator",
    "montajchi": "Montajchi",
    "fotograf": "Fotograf",
    "dekorator": "Dekorator",
    "taklifnomachi": "Taklifnomachi",
}

# Tadbirga (to'yga) boradigan lavozimlar — buyurtmada shulardan tanlanadi
FIELD_ROLES = ("operator", "fotograf", "dekorator")

# Eslatmalar (vaqtlar — TIMEZONE bo'yicha)
EVENING_AT = "17:00"        # ish kunidan bir kun oldin xodimga eslatma
HOURS_BEFORE = 1            # operator/fotografga tadbirdan necha soat oldin eslatma
DEKOR_MORNING_AT = "12:00"  # dekoratorga ish kuni (tadbirdan bir kun oldin): rasm va lokatsiya bilan
DEKOR_UNTIL = "20:00"       # shu vaqtdan keyin "bugun dekor" eslatmasi yuborilmaydi
FLASH_AT = "10:00"          # tadbirdan keyingi kuni: «fleshkani topshiring» (topshirguncha, 3 kun)
FLASH_DAYS = 3
FLASH_START = "2026-11-01"  # shu sanadan keyingi tadbirlar uchun so'raladi (eskilariga birdan xabar bormasin)
ADMIN_SUMMARY_AT = "11:00"  # adminga ertangi ishlar ro'yxati
QUIET_FROM = "22:00"        # kechikkan kechki eslatmalar shundan keyin yuborilmaydi
CHECK_EVERY = 60            # necha soniyada bir tekshiriladi

DEFAULT_EVENT_TYPES = ["Osh", "Nikoh", "Bazm", "Kelin salom"]

# Kirim-chiqimda zakaz to'lovlari shu kategoriya bilan Studiya kirimiga o'zi tushadi
ORDER_CATEGORY = "Zakaz to'lovi"
