"""Mijozlar uchun ochiq sayt: /sayt — roliklar, dekorlar, taklifnomalar, paketlar, albomlar, studiya.

Rasm va videolar `sayt/media/<bo'lim>/` papkalariga tashlanadi — sayt ularni o'zi ko'rsatadi.
Mijoz tanlagan narsa yoki buyurtma bazaga yoziladi va adminlarga «✅ Qabul qildim» tugmasi bilan boradi.
"""

import json
import logging
import time
from datetime import date
from pathlib import Path

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from aiohttp import web

from .config import SITE_MEDIA
from .db import Database
from .utils import escape, fmt_date, normalize_phone, parse_date

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent / "sayt"
MEDIA = (Path(SITE_MEDIA) if SITE_MEDIA else ROOT / "media").resolve()
SETTINGS = MEDIA / "sozlamalar.json"
SETTING_KEYS = ("telefon", "telegram", "instagram", "youtube", "manzil", "xarita", "ish_vaqti")
SECTIONS = ("roliklar", "dekorlar", "taklifnomalar", "albomlar", "studiya", "jamoa")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".webm", ".mov"}
KIND_TITLE = {"tanlov": "Mijoz tanlov qildi", "buyurtma": "Saytdan yangi buyurtma"}
SECTION_TITLE = {"roliklar": "Rolik", "dekorlar": "Dekor", "taklifnomalar": "Taklifnoma", "albomlar": "Albom"}
MAX_PER_WINDOW, WINDOW = 5, 600  # bitta IP dan 10 daqiqada 5 tadan ko'p so'rov qabul qilinmaydi
_hits: dict[str, list[float]] = {}


class SrCb(CallbackData, prefix="sr"):
    id: int


def take_kb(req_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Qabul qildim", callback_data=SrCb(id=req_id).pack())
    ]])


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {k: str(data.get(k) or "") for k in SETTING_KEYS}


def save_settings(values: dict) -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    data = {k: str(values.get(k) or "").strip()[:200] for k in SETTING_KEYS}
    SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _title(path: Path) -> str:
    """'01 Oq atirgul.jpg' -> 'Oq atirgul' (fayl nomi = sarlavha, boshidagi tartib raqami tashlanadi)."""
    name = path.stem.replace("_", " ").strip()
    head, _, rest = name.partition(" ")
    return rest if head.isdigit() and rest else name


def _items(section: str) -> list[dict]:
    folder = MEDIA / section
    if not folder.is_dir():
        return []
    items = []
    for f in sorted(folder.iterdir()):
        ext = f.suffix.lower()
        if ext in IMAGE_EXT or ext in VIDEO_EXT:
            items.append({"src": f"/sayt/media/{section}/{f.name}", "title": _title(f),
                          "type": "video" if ext in VIDEO_EXT else "image"})
    # YouTube/Instagram havolalari: havolalar.txt, har qatorda «Sarlavha | https://...»
    links = folder / "havolalar.txt"
    if links.is_file():
        for line in links.read_text(encoding="utf-8").splitlines():
            title, _, url = line.rpartition("|")
            url = url.strip()
            if url.startswith("https://"):
                items.append({"src": url, "title": title.strip() or "Rolik", "type": "link"})
    return items


async def site_index(request: web.Request) -> web.Response:
    return web.FileResponse(ROOT / "index.html", headers={"Cache-Control": "no-cache"})


async def gallery(request: web.Request) -> web.Response:
    info = load_settings()
    info["bot"] = request.app["bot_username"]
    hero = next((f"/sayt/media/{f.name}" for f in sorted(MEDIA.glob("hero.*"))
                 if f.suffix.lower() in VIDEO_EXT | IMAGE_EXT), "")
    return web.json_response({"info": info, "hero": hero, **{s: _items(s) for s in SECTIONS}})


def _limited(ip: str) -> bool:
    recent = [t for t in _hits.get(ip, []) if time.time() - t < WINDOW]
    _hits[ip] = recent + [time.time()]
    return len(recent) >= MAX_PER_WINDOW


def _clean(value, limit: int = 300) -> str:
    return str(value or "").strip()[:limit]


def _date(value) -> str:
    """Brauzer sanasi (2026-11-20) yoki qo'lda yozilgan (20.11) -> ISO; noto'g'ri bo'lsa ''."""
    text = _clean(value, 20)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        d = parse_date(text) if text else None
        return d.isoformat() if d else ""


def request_text(req_id: int, kind: str, d: dict) -> str:
    lines = [f"🌐 <b>{KIND_TITLE[kind]}</b> · so'rov №{req_id}",
             f"👤 {escape(d['name'])}, {escape(d['phone'])}"]
    if d.get("telegram"):
        lines.append(f"✈️ {escape(d['telegram'])}")
    if d.get("package"):
        lines.append(f"\n📦 Paket: <b>{escape(d['package'])}</b>")
    if d.get("addons"):
        lines.append(f"➕ Qo'shimcha: {escape(', '.join(d['addons']))}")
    for e in d.get("events", []):
        when = fmt_date(e["date"]) if e.get("date") else "sana —"
        lines.append(f"🎉 {escape(e.get('type') or 'Tadbir')} · {when} {escape(e.get('time') or '')}"
                     + (f" · 📍 {escape(e['address'])}" if e.get("address") else ""))
    if d.get("date") and not d.get("events"):
        lines.append(f"📅 To'y sanasi: {fmt_date(d['date'])}")
    if d.get("items"):
        lines.append("\n⭐️ <b>Tanlaganlari:</b>")
        lines += [f"• {SECTION_TITLE.get(i['section'], '')}: {escape(i['title'])}" for i in d["items"]]
    if d.get("note"):
        lines.append(f"\n📝 {escape(d['note'])}")
    return "\n".join(lines)


def _parse(body: dict) -> tuple[dict | None, str]:
    name, phone = _clean(body.get("name"), 80), normalize_phone(_clean(body.get("phone"), 30))
    if not name:
        return None, "Ismingizni yozing."
    if not phone:
        return None, "Telefon raqamni to'g'ri yozing, masalan: 90 123 45 67."
    kind = body.get("kind")
    if kind not in KIND_TITLE:
        return None, "Noto'g'ri so'rov."
    items = []
    for i in (body.get("items") or [])[:20]:
        section, src = _clean(i.get("section"), 20), _clean(i.get("src"), 300)
        if section in SECTION_TITLE:
            items.append({"section": section, "title": _clean(i.get("title"), 100), "src": src})
    events = []
    for e in (body.get("events") or [])[:8]:
        events.append({"type": _clean(e.get("type"), 40), "date": _date(e.get("date")),
                       "time": _clean(e.get("time"), 5), "address": _clean(e.get("address"), 150)})
    data = {"name": name, "phone": phone, "telegram": _clean(body.get("telegram"), 40),
            "package": _clean(body.get("package"), 40),
            "addons": [_clean(a, 40) for a in (body.get("addons") or [])[:15]],
            "events": events, "date": _date(body.get("date")),
            "items": items, "note": _clean(body.get("note"), 1000)}
    if kind == "tanlov" and not items:
        return None, "Hech narsa tanlanmagan."
    return {"kind": kind, **data}, ""


async def send_request(bot: Bot, db: Database, req_id: int, kind: str, d: dict) -> int:
    """Adminlarga: avval tanlangan rasmlar (albom ko'rinishida), keyin matn va «Qabul qildim» tugmasi."""
    photos = [MEDIA / i["src"].removeprefix("/sayt/media/") for i in d["items"]
              if i["src"].startswith("/sayt/media/") and Path(i["src"]).suffix.lower() in IMAGE_EXT]
    photos = [p for p in photos if p.resolve().is_relative_to(MEDIA) and p.is_file()][:10]
    sent = 0
    for tg_id in await db.admin_tg_ids():
        try:
            if len(photos) == 1:
                await bot.send_photo(tg_id, FSInputFile(photos[0]))
            elif photos:
                await bot.send_media_group(tg_id, [InputMediaPhoto(media=FSInputFile(p)) for p in photos])
            await bot.send_message(tg_id, request_text(req_id, kind, d), reply_markup=take_kb(req_id))
            sent += 1
        except Exception as e:
            log.warning("So'rov №%s adminga (%s) bormadi: %s", req_id, tg_id, e)
    return sent


async def new_request(request: web.Request) -> web.Response:
    ip = request.headers.get("X-Forwarded-For", request.remote or "?").split(",")[0].strip()
    if _limited(ip):
        return web.json_response({"ok": False, "error": "Juda ko'p so'rov. Birozdan keyin urinib ko'ring."},
                                 status=429)
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"ok": False, "error": "Noto'g'ri ma'lumot."}, status=400)
    if body.get("website"):  # botlar uchun yashirin maydon to'ldirilgan
        return web.json_response({"ok": True, "id": 0})
    data, error = _parse(body if isinstance(body, dict) else {})
    if not data:
        return web.json_response({"ok": False, "error": error}, status=400)
    db: Database = request.app["db"]
    kind = data.pop("kind")
    req_id = await db.site_request_add(kind, data["name"], data["phone"], json.dumps(data, ensure_ascii=False))
    await send_request(request.app["bot"], db, req_id, kind, data)
    return web.json_response({"ok": True, "id": req_id})


def add_site_routes(app: web.Application) -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    app.add_routes([
        web.get("/sayt", site_index), web.get("/sayt/", site_index),
        web.get("/sayt/api/galereya", gallery), web.post("/sayt/api/sorov", new_request),
        web.static("/sayt/media", MEDIA),
    ])
