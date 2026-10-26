import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()
}
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tashkent")

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

DEFAULT_EVENT_TYPES = ["Osh", "Nikoh", "Bazm", "Kelin salom"]
