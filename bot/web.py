"""Zakaz, montaj va qarzdorlar sayti — bot bilan bir jarayonda, bitta bazadan ishlaydi.

PORT (Railway beradi) yoki WEB_PORT bo'lsa ishga tushadi. Kirish — SITE_PIN bilan.
Zakaz saytda yoziladi; bot xodimlarga karta, montajchiga to'y va mijozga «tayyor» xabarini yuboradi.
"""

import hashlib
import hmac
import json
import logging
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiohttp import web

from .cash import BOOKS, CATEGORIES, CURRENCIES, DEFAULT_CATEGORY, PERIODS, fmt_cur, month_range, period_range
from .config import ADMIN_IDS, BOT_TOKEN, FIELD_ROLES, ORDER_CATEGORY, ROLES, SITE_PIN, WEB_PORT
from .db import Database
from .montaj import client_ready_text, send_to_client, send_to_editor
from .kassa_api import add_kassa_routes
from .notify import send_assignment
from .site import IMAGE_EXT, MEDIA, SECTION_TITLE, VIDEO_EXT, add_site_routes, load_settings, save_settings
from .utils import escape, fmt_date, fmt_money, normalize_phone, notify_admins, parse_money, parse_time, today

log = logging.getLogger(__name__)
COOKIE = "em_site"
MAX_FAILS, BLOCK_SECONDS = 5, 300
MAX_EVENTS = 8
_fails: dict[str, list[float]] = {}  # IP -> noto'g'ri PIN vaqtlari


def _token() -> str:
    return hmac.new((SITE_PIN + BOT_TOKEN).encode(), b"elegant-site", hashlib.sha256).hexdigest()


def _ip(request: web.Request) -> str:
    return request.headers.get("X-Forwarded-For", request.remote or "?").split(",")[0].strip()


def _authed(request: web.Request) -> bool:
    return bool(SITE_PIN) and hmac.compare_digest(request.cookies.get(COOKIE, ""), _token())


def _blocked(ip: str) -> bool:
    recent = [t for t in _fails.get(ip, []) if time.time() - t < BLOCK_SECONDS]
    _fails[ip] = recent
    return len(recent) >= MAX_FAILS


def _back(tab: str = "orders", **flash) -> web.HTTPSeeOther:
    return web.HTTPSeeOther("/?" + urlencode({"tab": tab, **flash}))


# ---------- Sahifa ----------

STYLE = """
:root{--bg:#f7f4f6;--surface:#fff;--ink:#24161f;--muted:#7a6872;--line:#e6dde2;--accent:#7b2350;
--accent-soft:#f3e3eb;--debt:#b4232f;--debt-soft:#fbe6e7;--ok:#1f7a4d;--ok-soft:#e1f2e8;--on-accent:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#17111a;--surface:#221a24;--ink:#f2e9ee;--muted:#a8969f;
--line:#382b36;--accent:#e08ab4;--accent-soft:#3a2231;--debt:#ff8a8f;--debt-soft:#3d1f24;--ok:#6fd3a0;
--ok-soft:#1b3328;--on-accent:#1a0f15}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 "Golos Text",system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:720px;margin:0 auto;padding:20px 16px 48px;display:flex;flex-direction:column;gap:16px}
h1{font:700 1.35rem "Unbounded",system-ui,sans-serif;margin:0}
h2{font:600 1rem "Golos Text",system-ui,sans-serif;margin:0}
.eyebrow{font-size:.72rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);font-weight:600}
.num{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
header{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.total{background:var(--accent);color:var(--on-accent);border-radius:16px;padding:18px;display:grid;grid-template-columns:1fr auto;gap:6px 16px;align-items:end}
.total .eyebrow{color:inherit;opacity:.75}.total .big{font:500 1.7rem "JetBrains Mono",monospace;line-height:1.1;word-break:break-word}
.total .side{text-align:right;font-size:.85rem;opacity:.9}
@media (max-width:480px){.total{grid-template-columns:1fr}.total .side{text-align:left}.total .big{font-size:1.5rem}}
.tabs{display:grid;grid-template-columns:repeat(4,1fr);gap:4px;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:4px}
.tabs a{display:block;text-align:center;padding:10px 4px;border-radius:9px;font-weight:600;color:var(--muted);text-decoration:none;font-size:.92rem}
.tabs a[aria-current]{background:var(--accent-soft);color:var(--accent)}
.row{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:10px}
.top{display:grid;grid-template-columns:1fr auto;gap:4px 12px}
.name{font-weight:600;font-size:1.02rem;overflow-wrap:anywhere}.meta{color:var(--muted);font-size:.84rem;overflow-wrap:anywhere}
.owe{text-align:right;font:1.05rem "JetBrains Mono",monospace;color:var(--debt);white-space:nowrap}
.owe.ok{color:var(--ok)}.owe small{display:block;font:.75rem "Golos Text",system-ui,sans-serif;color:var(--muted)}
.pill{display:inline-block;font-size:.72rem;font-weight:600;padding:2px 8px;border-radius:999px;background:var(--debt-soft);color:var(--debt)}
.pill.ok{background:var(--ok-soft);color:var(--ok)}.pill.plain{background:var(--accent-soft);color:var(--accent)}
.pill.grey{background:var(--line);color:var(--ink)}
.progress{height:6px;border-radius:99px;background:var(--debt-soft);overflow:hidden}.progress span{display:block;height:100%;background:var(--ok)}
.ev{font-size:.86rem;border-top:1px dashed var(--line);padding-top:6px;overflow-wrap:anywhere}
.pays{border-top:1px dashed var(--line);padding-top:8px;display:flex;flex-direction:column;gap:4px;font-size:.85rem;color:var(--muted)}
.pays div{display:flex;justify-content:space-between;gap:8px}
.inline{display:grid;grid-template-columns:1fr auto;gap:8px}
input,select,textarea,button{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:9px 12px;min-width:0;width:100%}
button,.btn{cursor:pointer;font-weight:500;width:auto;display:inline-block;text-decoration:none;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:11px 16px}
.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.okbtn{background:var(--ok);border-color:var(--ok);color:var(--on-accent)}
input:focus,select:focus,textarea:focus,button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.stage{border:1px solid var(--line);border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;gap:8px;background:var(--bg)}
.ready{border-color:var(--ok-soft);background:var(--ok-soft)}
.msgbox{background:var(--surface);border-radius:8px;padding:10px;font-size:.88rem;user-select:all;white-space:pre-wrap}
.empty{text-align:center;padding:36px 16px;color:var(--muted);border:1px dashed var(--line);border-radius:14px}
.msg{padding:10px 12px;border-radius:10px;background:var(--ok-soft);color:var(--ok)}.msg.err{background:var(--debt-soft);color:var(--debt)}
.login{max-width:340px;margin:12vh auto;display:flex;flex-direction:column;gap:12px}
form.card{display:flex;flex-direction:column;gap:12px}
label{display:flex;flex-direction:column;gap:4px;font-size:.82rem;color:var(--muted);font-weight:500}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}.grid2>*{min-width:0}
@media (max-width:480px){.grid2{grid-template-columns:1fr}}
fieldset{border:1px solid var(--line);border-radius:12px;padding:12px;display:flex;flex-direction:column;gap:10px;margin:0;min-width:0;background:var(--surface)}
legend{font-weight:600;padding:0 6px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{position:relative;display:inline-flex}
.chip input{position:absolute;opacity:0;width:1px;height:1px}
.chip span{display:inline-block;padding:7px 12px;border:1px solid var(--line);border-radius:999px;background:var(--bg);font-size:.86rem;cursor:pointer}
.chip span small{color:var(--muted);margin-left:4px}
.chip input:checked+span{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.chip input:checked+span small{color:inherit;opacity:.8}
.chip input:focus-visible+span{outline:2px solid var(--accent);outline-offset:1px}
.tabs.two{grid-template-columns:1fr 1fr}
summary{cursor:pointer}
.ledger{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:4px 14px}
.ledger .day{font-size:.75rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;padding:12px 0 2px}
.line{display:grid;grid-template-columns:1fr auto auto;gap:10px;align-items:center;padding:9px 0;border-top:1px solid var(--line)}
.line .cat{font-weight:500;overflow-wrap:anywhere}
.amt{font:1rem "JetBrains Mono",monospace;white-space:nowrap;text-align:right}.amt.in{color:var(--ok)}.amt.out{color:var(--debt)}
.x{padding:4px 9px;color:var(--muted)}
.progress.over span{background:var(--debt)}
.bigbtns{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.bigbtns .btn{text-align:center;padding:16px 8px;font-size:1.05rem;font-weight:600;border-radius:14px}
.btn.out{background:var(--debt);border-color:var(--debt);color:var(--on-accent)}
.btn.in{background:var(--ok);border-color:var(--ok);color:var(--on-accent)}
.linkbtn{background:none;border:0;padding:6px 0;color:var(--muted);text-decoration:underline}
.sum3>div{display:flex;justify-content:space-between;align-items:baseline;gap:8px;padding:3px 0}
.sum3 b{font:500 1.1rem "JetBrains Mono",monospace;text-align:right}.sum3>div:last-child b{font-size:1.5rem}
.fold>summary{list-style:none;font-weight:600;padding:10px 0 2px;color:var(--accent)}
.fold>summary::-webkit-details-marker{display:none}
.fold[open]>summary{margin-bottom:8px}
.amountbig{font:500 1.6rem "JetBrains Mono",monospace;text-align:center;padding:14px}
.chip span{padding:10px 14px;font-size:.95rem}
"""

FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Unbounded:wght@700'
         '&family=Golos+Text:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap">')


def page(title: str, body: str) -> web.Response:
    html = (
        f'<!doctype html><html lang="uz"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="robots" content="noindex"><title>{escape(title)}</title>{FONTS}'
        f'<style>{STYLE}</style></head><body>{body}</body></html>'
    )
    return web.Response(text=html, content_type="text/html")


def attr(value) -> str:
    return escape(value or "").replace('"', "&quot;")


def login_page(error: str = "", nxt: str = "/") -> web.Response:
    err = f'<div class="msg err">{escape(error)}</div>' if error else ""
    return page("Kirish", f"""
<form class="login" method="post" action="/login">
  <div class="eyebrow">Elegant Media</div><h1>Kirish</h1>{err}
  <input name="pin" type="password" inputmode="numeric" autocomplete="current-password" placeholder="PIN-kod" required autofocus>
  <input type="hidden" name="next" value="{attr(nxt)}">
  <button class="primary" type="submit">Kirish</button>
</form>""")


def _when(d: str) -> str:
    days = (date.fromisoformat(d) - today()).days
    if days == 0:
        return '<span class="pill plain">Bugun</span>'
    if days == 1:
        return '<span class="pill plain">Ertaga</span>'
    if days > 1:
        return f'<span class="pill plain">{days} kun qoldi</span>'
    return f'<span class="meta">{-days} kun oldin</span>'


def stage_block(o: dict, editors: list, bot_username: str) -> str:
    """Montaj bosqichi: montajchiga berish → tayyor → mijozga xabar → topshirildi."""
    oid = o["id"]

    def btn(action: str, text: str, cls: str = "") -> str:
        return (f'<form method="post" action="/stage"><input type="hidden" name="order" value="{oid}">'
                f'<input type="hidden" name="action" value="{action}">'
                f'<button class="{cls}" type="submit">{text}</button></form>')

    if o["delivered_at"]:
        return '<div class="actions"><span class="pill ok">✓ Mijozga topshirildi</span></div>'

    if o["editing_done_at"] or o["ready_notified_at"]:
        head = ('<span class="pill ok">Tayyor</span>'
                + (' <span class="pill grey">Mijozga xabar berildi</span>' if o["ready_notified_at"] else ""))
        if o["client_tg_id"]:
            tell = "" if o["ready_notified_at"] else btn("client", "📨 Mijozga bot orqali xabar", "okbtn")
            manual = ""
        else:
            text = client_ready_text({**o, "types": ", ".join(e["type_name"] for e in o["events"]),
                                      "debt": o["total"] - o["paid"]})
            phone = (o["client_phone"] or "").lstrip("+")
            tg = f'<a class="btn" href="https://t.me/+{phone}" target="_blank" rel="noopener">Telegram\'da ochish</a>' if phone else ""
            tell = btn("notified", "✓ Xabar berdim")
            manual = (f'<div class="meta">Mijoz botga ulanmagan — matnni nusxalab o\'zingiz yuboring:</div>'
                      f'<div class="msgbox">{escape(text)}</div><div class="actions">{tg}</div>')
        return (f'<div class="stage ready"><div class="actions">{head}</div>{manual}'
                f'<div class="actions">{tell}{btn("delivered", "✓ Topshirildi")}</div></div>')

    if o["editor_id"]:
        return (f'<div class="stage"><div class="actions"><span class="pill plain">Montajda: '
                f'{escape(o["editor_name"] or "?")}</span></div>'
                f'<div class="actions">{btn("ready", "✓ Montaj tayyor", "okbtn")}</div></div>')

    if not editors:
        return ('<div class="stage"><div class="meta">Montajga berish uchun botda «Montajchi» lavozimli '
                'xodim qo\'shing.</div></div>')
    options = "".join(f'<option value="{s["id"]}">{escape(s["name"])}</option>' for s in editors)
    return (f'<form class="stage inline" method="post" action="/editor">'
            f'<input type="hidden" name="order" value="{oid}">'
            f'<select name="staff" aria-label="Montajchi">{options}</select>'
            f'<button class="primary" type="submit">Montajga berish</button></form>')


def order_card(o: dict, editors: list, bot_username: str, show_stage: bool) -> str:
    """Kartada faqat asosiysi: mijoz, qarz, tadbir sanasi. Qolgani «Batafsil» ichida."""
    left = o["total"] - o["paid"]
    pct = min(100, round(o["paid"] * 100 / o["total"])) if o["total"] else 100
    events = "".join(
        f'<div class="ev">📅 <b>{fmt_date(e["date"])}</b>{", " + escape(e["time"]) if e["time"] else ""} '
        f'{_when(e["date"])}<br><span class="meta">{escape(e["type_name"])} · 📍 {escape(e["address"] or "—")}</span></div>'
        for e in o["events"]
    )
    teams = "".join(
        f'<div>👥 {escape(e["type_name"])}: {escape(e["team"]) if e["team"] else "xodim yo&#39;q"}</div>'
        for e in o["events"]
    )
    pays = "".join(
        f'<div><span>{escape(p["paid_at"][:10])} · {escape(p["note"] or "")}</span>'
        f'<span class="num">{fmt_money(p["amount"])}</span></div>'
        for p in reversed(o["payments"])
    )
    pay = ""
    if left > 0:
        pay = f"""
<details class="fold"><summary>💵 To'lov qo'shish</summary>
<form class="inline" method="post" action="/pay">
  <input type="hidden" name="order" value="{o['id']}">
  <input name="amount" inputmode="numeric" placeholder="Masalan 500 000" required aria-label="To'lov summasi">
  <button class="primary" type="submit">Saqlash</button>
</form>
<form method="post" action="/pay" style="margin-top:8px" onsubmit="return confirm('Qolgan {fmt_money(left)} to\\'liq to\\'landimi?')">
  <input type="hidden" name="order" value="{o['id']}"><input type="hidden" name="amount" value="{left}">
  <button type="submit">✓ Hammasi to'landi ({fmt_money(left)})</button>
</form></details>"""
    client = ('<div>🤖 Mijoz botga ulangan</div>' if o["client_tg_id"] else
              f'<div>🔗 Mijozga shu havolani yuboring — tayyor bo\'lganda bot o\'zi xabar beradi:</div>'
              f'<input readonly onclick="this.select()" value="https://t.me/{attr(bot_username)}?start=o_{attr(o["client_token"])}">')
    phone = o["client_phone"] or ""
    return f"""
<article class="row">
  <div class="top"><div><div class="name">{escape(o['client_name'])}</div>
    {f'<a class="meta num" href="tel:{attr(phone)}">📞 {escape(phone)}</a>' if phone else ''}</div>
    <div class="owe{' ok' if left <= 0 else ''}">{fmt_money(left) if left > 0 else '✓ To&#39;langan'}
      <small>{'qarz' if left > 0 else fmt_money(o['total'])}</small></div></div>
  {events}
  {stage_block(o, editors, bot_username) if show_stage else ''}
  {pay}
  <details class="fold"><summary>ℹ️ Batafsil</summary><div class="meta" style="display:flex;flex-direction:column;gap:6px">
    <div>№{o['id']} · {escape(o['services'] or '')} · {fmt_money(o['total'])} ({pct}% to'landi)</div>
    {teams}
    {f'<div>📝 {escape(o["note"])}</div>' if o["note"] else ''}
    {client}
    {f'<div class="pays">{pays}</div>' if pays else ''}
  </div></details>
</article>"""


FLASH = {
    "paid": ("", "To'lov saqlandi."),
    "badpay": ("err", "Summani tushunmadim yoki u qarzdan katta."),
    "editor": ("", "Montajchiga yuborildi."),
    "editor_off": ("err", "Montajchi botga ulanmagan — xabar bormadi. «Xodimlar» bo'limidagi havolani unga yuboring."),
    "ready": ("", "Montaj tayyor deb belgilandi."),
    "client": ("", "Mijozga bot orqali xabar yuborildi."),
    "client_off": ("err", "Mijoz botga ulanmagan. Matnni nusxalab o'zingiz yuboring."),
    "notified": ("", "Belgilandi: mijozga xabar berildi."),
    "delivered": ("", "Topshirildi deb belgilandi."),
}


async def index(request: web.Request) -> web.Response:
    if not SITE_PIN:
        return page("Sozlanmagan", '<div class="wrap"><div class="empty">Sayt yopiq: '
                                   'SITE_PIN o\'zgaruvchisi o\'rnatilmagan.</div></div>')
    if not _authed(request):
        return login_page()
    db: Database = request.app["db"]
    orders = await db.orders_overview()
    editors = [s for s in await db.staff_list() if s["role"] == "montajchi"]
    username = request.app["bot_username"]
    tab = request.query.get("tab", "orders")
    iso = today().isoformat()

    upcoming = [o for o in orders if any(e["date"] >= iso for e in o["events"])]
    upcoming.sort(key=lambda o: min(e["date"] + (e["time"] or "") for e in o["events"] if e["date"] >= iso))
    montaj = [o for o in orders if not o["delivered_at"] and o["events"]
              and min(e["date"] for e in o["events"]) < iso and o not in upcoming]
    montaj.sort(key=lambda o: min(e["date"] for e in o["events"]))
    debts = sorted((o for o in orders if o["total"] - o["paid"] > 0), key=lambda o: o["paid"] - o["total"])
    requests = await db.site_requests()
    fresh = sum(1 for r in requests if r["status"] == "yangi")

    if tab == "debts":
        summary = (f'<div><div class="eyebrow">Jami qolgan qarz</div>'
                   f'<div class="big">{fmt_money(sum(o["total"] - o["paid"] for o in debts))}</div></div>'
                   f'<div class="side">{len(debts)} nafar qarzdor<br>'
                   f'To\'langan: {fmt_money(sum(o["paid"] for o in orders))}</div>')
        items = "".join(order_card(o, editors, username, True) for o in debts) or '<div class="empty">Qarzdor yo\'q 🎉</div>'
    elif tab == "sorov":
        summary = (f'<div><div class="eyebrow">Saytdan kelgan so&#39;rovlar</div>'
                   f'<div class="big">{fresh} ta yangi</div></div>'
                   f'<div class="side">Ochiq sayt: <a href="/sayt" target="_blank" style="color:inherit">/sayt</a></div>')
        items = "".join(request_card(r) for r in requests) or "<div class=\"empty\">Hozircha so'rov yo'q</div>"
    elif tab == "montaj":
        waiting = sum(1 for o in montaj if not o["editor_id"])
        summary = (f'<div><div class="eyebrow">Topshirilmagan to\'ylar</div>'
                   f'<div class="big">{len(montaj)} ta</div></div>'
                   f'<div class="side">Montajga berilmagan: {waiting} ta</div>')
        items = "".join(order_card(o, editors, username, True) for o in montaj) or \
            '<div class="empty">Topshirilmagan to\'y yo\'q</div>'
    else:
        tab = "orders"
        summary = (f'<div><div class="eyebrow">Kelayotgan zakazlar</div>'
                   f'<div class="big">{len(upcoming)} ta</div></div>'
                   f'<div class="side">Jami: {fmt_money(sum(o["total"] for o in upcoming))}</div>')
        items = "".join(order_card(o, editors, username, False) for o in upcoming) or \
            '<div class="empty">Kelayotgan zakaz yo\'q. «+ Yangi zakaz» tugmasini bosing.</div>'

    m = request.query.get("m", "")
    if m == "new":
        q = request.query
        msg_html = (f'<div class="msg">✅ Zakaz №{escape(q.get("id", ""))} saqlandi. Xodimlarga xabar ketdi: '
                    f'{escape(q.get("sent", "0"))} ta'
                    + (f'. <b>Bormadi (botga ulanmagan): {escape(q.get("failed"))}</b>' if q.get("failed") else "")
                    + '</div>')
    elif m in FLASH:
        cls, text = FLASH[m]
        msg_html = f'<div class="msg {cls}">{text}</div>'
    else:
        msg_html = ""
    cur = ' aria-current="page"'
    return page("Elegant Media", f"""
<div class="wrap">
  <header><h1>Elegant Media</h1>
    <form method="post" action="/logout"><button class="linkbtn" type="submit">Chiqish</button></form></header>
  <div class="bigbtns"><a class="btn primary" href="/new">➕ Yangi zakaz</a>
    <a class="btn" href="/kassa/">💰 Kassa</a>
    <a class="btn" href="/maosh">👷 Maosh</a>
    <a class="btn" href="/media" style="grid-column:1/-1">🖼 Sayt: rasm, video, kontaktlar</a></div>
  <nav class="tabs">
    <a href="/?tab=orders"{cur if tab == 'orders' else ''}>Zakazlar · {len(upcoming)}</a>
    <a href="/?tab=montaj"{cur if tab == 'montaj' else ''}>Montaj · {len(montaj)}</a>
    <a href="/?tab=debts"{cur if tab == 'debts' else ''}>Qarzdorlar · {len(debts)}</a>
    <a href="/?tab=sorov"{cur if tab == 'sorov' else ''}>So'rovlar{' · ' + str(fresh) if fresh else ''}</a></nav>
  <section class="total">{summary}</section>
  {msg_html}
  {items}
</div>""")


def request_card(r) -> str:
    """Saytdan kelgan so'rov: tanlovlar rasmlari, paket, tadbirlar; «Qabul qildim» va «Zakaz yozish»."""
    d = json.loads(r["data"])
    title = "Buyurtma" if r["kind"] == "buyurtma" else "Tanlov"
    status = (f'<span class="pill ok">✅ {escape(r["taken_by"] or "")}</span>' if r["status"] == "qabul"
              else '<span class="pill">Yangi</span>')
    lines = []
    if d.get("package"):
        lines.append(f'📦 <b>{escape(d["package"])}</b>' + (f' + {escape(", ".join(d["addons"]))}' if d.get("addons") else ""))
    for e in d.get("events", []):
        lines.append(f'🎉 {escape(e.get("type") or "Tadbir")} · {fmt_date(e["date"]) if e.get("date") else "—"} '
                     f'{escape(e.get("time") or "")} {("· " + escape(e["address"])) if e.get("address") else ""}')
    if d.get("date") and not d.get("events"):
        lines.append(f'📅 {fmt_date(d["date"])}')
    if d.get("note"):
        lines.append(f'📝 {escape(d["note"])}')
    thumbs = "".join(
        f'<a href="{attr(i["src"])}" target="_blank" title="{attr(i["title"])}">'
        f'<img src="{attr(i["src"])}" alt="{attr(i["title"])}" loading="lazy" '
        f'style="width:64px;height:64px;object-fit:cover;border-radius:8px"></a>'
        if i["src"].startswith("/sayt/media/") and i["src"].rsplit(".", 1)[-1].lower() in ("jpg", "jpeg", "png", "webp", "gif")
        else f'<span class="pill grey">{SECTION_TITLE.get(i["section"], "")}: {escape(i["title"])}</span>'
        for i in d.get("items", []))
    prefill = urlencode({"name": r["name"], "phone": r["phone"], "note": d.get("note") or ""})
    take = ("" if r["status"] == "qabul" else
            f'<form method="post" action="/sorov"><input type="hidden" name="id" value="{r["id"]}">'
            f'<button class="okbtn" type="submit">✅ Qabul qildim</button></form>')
    return f"""
<article class="row">
  <div class="top"><div><div class="name">№{r["id"]} {escape(r["name"])} · {title}</div>
    <div class="meta">{escape(r["phone"])}{(" · " + escape(d["telegram"])) if d.get("telegram") else ""} · {escape(r["created_at"][:16])}</div></div>
    <div>{status}</div></div>
  {"".join(f'<div class="ev">{l}</div>' for l in lines)}
  {f'<div class="actions">{thumbs}</div>' if thumbs else ""}
  <div class="actions">{take}<a class="btn" href="/new?{attr(prefill)}">📝 Zakaz yozish</a>
    <a class="btn" href="tel:{attr(r["phone"])}">📞 Qo'ng'iroq</a></div>
</article>"""


# ---------- Yangi zakaz ----------

EVENT_JS = """
<script>
(function(){
  const box = document.getElementById('events');
  const tpl = document.getElementById('ev-tpl').innerHTML;
  document.getElementById('add-ev').addEventListener('click', () => {
    const n = box.children.length;
    if (n >= %d) return;
    box.insertAdjacentHTML('beforeend', tpl.replaceAll('__I__', n).replaceAll('__N__', n + 1));
  });
})();
</script>""" % MAX_EVENTS


def event_fieldset(i, ev: dict, staff: list, types: list[str]) -> str:
    chosen = {str(x) for x in ev.get("staff", [])}
    chips = "".join(
        f'<label class="chip"><input type="checkbox" name="ev_staff_{i}" value="{s["id"]}"'
        f'{" checked" if str(s["id"]) in chosen else ""}><span>{escape(s["name"])}'
        f'<small>{escape(ROLES[s["role"]].lower())}{"" if s["tg_id"] else " · ulanmagan"}</small></span></label>'
        for s in staff
    ) or '<span class="meta">Botda hali xodim yo\'q — «👥 Xodimlar» bo\'limidan qo\'shing.</span>'
    # Tadbir turi — tugmalar (turlar botdagi «Tadbir turlari» bo'limidan)
    type_chips = "".join(
        f'<label class="chip"><input type="radio" name="ev_type_{i}" value="{attr(t)}" required'
        f'{" checked" if (ev.get("type") or "").lower() == t.lower() else ""}><span>{escape(t)}</span></label>'
        for t in types
    ) or f'<input name="ev_type_{i}" value="{attr(ev.get("type"))}" placeholder="Nikoh, Bazm..." required>'
    title = "📅 Tadbir" if i == 0 else f"📅 {i + 1 if isinstance(i, int) else '__N__'}-tadbir"
    decor_open = " open" if ev.get("decor") else ""
    return f"""
<fieldset><legend>{title}</legend>
  <div class="chips">{type_chips}</div>
  <div class="grid2">
    <label>Sana<input type="date" name="ev_date_{i}" value="{attr(ev.get('date'))}" required></label>
    <label>Soat<input type="time" name="ev_time_{i}" value="{attr(ev.get('time'))}" required></label>
  </div>
  <label>To'yxona / manzil<input name="ev_address_{i}" value="{attr(ev.get('address'))}" placeholder="Yakkasaroy" required></label>
  <div><div class="meta" style="margin-bottom:6px">Kim boradi</div><div class="chips">{chips}</div></div>
  <details class="fold"{decor_open}><summary>🎀 Dekor (ixtiyoriy)</summary>
    <div style="display:flex;flex-direction:column;gap:10px">
    <label>Qanday bo'lishi kerak<input name="ev_decor_{i}" value="{attr(ev.get('decor'))}" placeholder="Saraylik max"></label>
    <label>Rasm (dekoratorga boradi)<input type="file" name="ev_photo_{i}" accept="image/*"></label></div>
  </details>
</fieldset>"""


async def form_page(request: web.Request, values: dict | None = None, errors: list | None = None) -> web.Response:
    db: Database = request.app["db"]
    v = values or {}
    staff = [s for s in await db.staff_list() if s["role"] in FIELD_ROLES]
    types = [t["name"] for t in await db.event_types_list()]
    events = v.get("events") or [{}]
    err = ('<div class="msg err">❗️ ' + "<br>".join(escape(e) for e in errors) + '</div>') if errors else ""
    extra_open = " open" if v.get("services") or v.get("note") else ""
    return page("Yangi zakaz", f"""
<div class="wrap">
  <header><h1>Yangi zakaz</h1><a class="btn" href="/">← Orqaga</a></header>
  {err}
  <form class="card" method="post" action="/new" enctype="multipart/form-data">
    <fieldset><legend>👤 Mijoz</legend><div class="grid2">
      <label>Ism<input name="name" value="{attr(v.get('name'))}" required placeholder="Botir"></label>
      <label>Telefon<input name="phone" value="{attr(v.get('phone'))}" inputmode="tel" required placeholder="91 943 76 76"></label>
    </div></fieldset>
    <div id="events" style="display:flex;flex-direction:column;gap:12px">
      {"".join(event_fieldset(i, ev, staff, types) for i, ev in enumerate(events))}
    </div>
    <button type="button" id="add-ev">➕ Yana tadbir qo'shish</button>
    <fieldset><legend>💵 Pul</legend><div class="grid2">
      <label>Umumiy narx<input name="total" value="{attr(v.get('total'))}" inputmode="numeric" required placeholder="2 500 000"></label>
      <label>Avans (berilgan)<input name="deposit" value="{attr(v.get('deposit'))}" inputmode="numeric" placeholder="0"></label>
    </div></fieldset>
    <details class="fold"{extra_open}><summary>📝 Qo'shimcha (ixtiyoriy)</summary>
      <div style="display:flex;flex-direction:column;gap:10px">
      <label>Xizmatlar<input name="services" value="{attr(v.get('services'))}" placeholder="Video, foto, dekor"></label>
      <label>Izoh<textarea name="note" rows="2" placeholder="Dron kerak...">{escape(v.get('note') or '')}</textarea></label>
      </div></details>
    <button class="primary" type="submit" style="padding:16px">Saqlash va xodimlarga yuborish</button>
  </form>
  <template id="ev-tpl">{event_fieldset("__I__", {}, staff, types)}</template>
</div>{EVENT_JS}""")


async def new_form(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    q = request.query  # saytdagi so'rovdan «Zakaz yozish» bosilganda ism/telefon tayyor keladi
    return await form_page(request, {k: q.get(k, "") for k in ("name", "phone", "note")})


async def new_save(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    db: Database = request.app["db"]
    bot: Bot = request.app["bot"]
    form = await request.post()
    get = lambda k: str(form.get(k, "")).strip()  # noqa: E731

    values = {k: get(k) for k in ("name", "phone", "services", "total", "deposit", "note")}
    values["events"] = []
    photos = {}
    for i in range(MAX_EVENTS):
        if f"ev_date_{i}" not in form:
            continue
        values["events"].append({
            "type": get(f"ev_type_{i}"), "address": get(f"ev_address_{i}"), "date": get(f"ev_date_{i}"),
            "time": get(f"ev_time_{i}"), "decor": get(f"ev_decor_{i}"),
            "staff": [str(x) for x in form.getall(f"ev_staff_{i}", [])],
        })
        f = form.get(f"ev_photo_{i}")
        if getattr(f, "file", None) and getattr(f, "filename", ""):
            data = f.file.read()
            if data:
                photos[len(values["events"]) - 1] = data

    errors = []
    phone = normalize_phone(values["phone"])
    total = parse_money(values["total"])
    deposit = parse_money(values["deposit"]) if values["deposit"] else 0
    if not 2 <= len(values["name"]) <= 64:
        errors.append("Mijoz ismini yozing.")
    if not phone:
        errors.append("Telefon raqam noto'g'ri. Masalan: 91 943 76 76")
    if not total:
        errors.append("Umumiy narxni yozing. Masalan: 2 500 000")
    if deposit is None or (total and deposit > total):
        errors.append("Avans noto'g'ri yoki umumiy narxdan katta.")
    staff_by_id = {str(s["id"]): s for s in await db.staff_list() if s["role"] in FIELD_ROLES}
    events = []
    for n, ev in enumerate(values["events"], 1):
        try:
            d = date.fromisoformat(ev["date"])
        except ValueError:
            d = None
        if not ev["type"] or not d or not parse_time(ev["time"]) or len(ev["address"]) < 2:
            errors.append(f"{n}-tadbir: turi, sana, soat va manzilni to'ldiring.")
            continue
        if d < today():
            errors.append(f"{n}-tadbir: sana o'tib ketgan.")
            continue
        events.append((ev, d))
    if not values["events"]:
        errors.append("Kamida bitta tadbir yozing.")
    if errors:
        return await form_page(request, values, errors)

    out_events = []
    for idx, (ev, d) in enumerate(events):
        types = await db.event_types_list()
        t = next((x for x in types if x["name"].lower() == ev["type"].lower()), None)
        if not t:
            await db.event_type_add(ev["type"][:40])
            t = next(x for x in await db.event_types_list() if x["name"].lower() == ev["type"][:40].lower())
        ops = [{"id": staff_by_id[s]["id"], "name": staff_by_id[s]["name"], "role": staff_by_id[s]["role"], "pay": 0}
               for s in ev["staff"] if s in staff_by_id]
        photo_id = None
        if idx in photos and ADMIN_IDS:
            # Telegram rasmni saqlab, file_id beradi — dekoratorga shu ID bilan yuboriladi
            msg = await bot.send_photo(next(iter(ADMIN_IDS)), BufferedInputFile(photos[idx], "dekor.jpg"),
                                       caption=f"🎀 Dekor rasmi: {escape(values['name'])}, {escape(ev['type'])}")
            photo_id = msg.photo[-1].file_id
        out_events.append({
            "type_id": t["id"], "type_name": t["name"], "date": d.isoformat(), "time": parse_time(ev["time"]),
            "address": ev["address"][:200], "lat": None, "lon": None,
            "decor_photo": photo_id, "decor_note": ev["decor"][:500] or None, "ops": ops,
        })

    # Xizmat yozilmasa, tadbir turlari olinadi: «Nikoh, Bazm»
    services = values["services"] or ", ".join(dict.fromkeys(e["type_name"] for e in out_events))
    data = {"client_name": values["name"], "client_phone": phone, "deposit": deposit,
            "services": [{"name": services[:100], "price": total}],
            "events": out_events, "note": values["note"][:500] or None}
    order_id, asg_ids = await db.order_create(data, next(iter(ADMIN_IDS), 0))
    sent, failed = 0, []
    for asg_id in asg_ids:
        if await send_assignment(bot, db, asg_id):
            sent += 1
        else:
            failed.append((await db.assignment_info(asg_id))["staff_name"])
    await notify_admins(bot, db, f"🆕 Saytdan zakaz №{order_id}: <b>{escape(values['name'])}</b>, "
                                 f"{fmt_money(total)}. Xodimlarga xabar: {sent} ta.")
    flash = {"m": "new", "id": order_id, "sent": sent}
    if failed:
        flash["failed"] = ", ".join(sorted(set(failed)))
    raise _back("orders", **flash)


# ---------- Amallar ----------

async def _order_or_back(request: web.Request, form) -> dict:
    db: Database = request.app["db"]
    try:
        order_id = int(form.get("order", ""))
    except ValueError:
        raise _back()
    o = next((x for x in await db.orders_overview() if x["id"] == order_id), None)
    if not o:
        raise _back()
    return o


async def pay(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    db: Database = request.app["db"]
    o = await _order_or_back(request, form)
    amount = parse_money(str(form.get("amount", "")))
    if not amount or amount > o["total"] - o["paid"]:
        raise _back("debts", m="badpay")
    left = o["total"] - o["paid"] - amount
    await db.payment_add(o["id"], amount, "Sayt orqali" if left else "Sayt orqali · to'liq yopildi")
    await notify_admins(
        request.app["bot"], db,
        f"💵 Sayt orqali to'lov: <b>{escape(o['client_name'])}</b> (№{o['id']}) — {fmt_money(amount)}\n"
        + (f"Qolgan qarz: {fmt_money(left)}" if left else "✅ Qarz to'liq yopildi"),
    )
    raise _back("debts", m="paid")


async def set_editor(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    db: Database = request.app["db"]
    o = await _order_or_back(request, form)
    staff = await db.staff_get(int(form.get("staff", 0) or 0))
    if not staff or staff["role"] != "montajchi":
        raise _back("montaj")
    await db.order_set_editor(o["id"], staff["id"])
    ok = await send_to_editor(request.app["bot"], db, o["id"])
    raise _back("montaj", m="editor" if ok else "editor_off")


async def stage(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    db: Database = request.app["db"]
    o = await _order_or_back(request, form)
    action = str(form.get("action", ""))
    if action == "ready":
        await db.order_stamp(o["id"], "editing_done_at")
        if o["client_tg_id"]:
            ok = await send_to_client(request.app["bot"], db, o["id"])
            raise _back("montaj", m="client" if ok else "ready")
        raise _back("montaj", m="ready")
    if action == "client":
        ok = await send_to_client(request.app["bot"], db, o["id"])
        raise _back("montaj", m="client" if ok else "client_off")
    if action == "notified":
        await db.order_stamp(o["id"], "ready_notified_at")
        raise _back("montaj", m="notified")
    if action == "delivered":
        await db.order_stamp(o["id"], "delivered_at")
        raise _back("montaj", m="delivered")
    raise _back("montaj")


# ---------- Kirim-chiqim ----------

CASH_FLASH = {
    "saved": ("", "✅ Yozildi: {info}"),
    "limit": ("err", "⚠️ Oylik limitdan oshdi — {info}"),
    "bad": ("err", "Summani tushunmadim. Masalan: 150 000 yoki 2 mln"),
    "deleted": ("", "O'chirildi."),
    "limit_set": ("", "Limit saqlandi."),
}


CASH_EMPTY = {"day": "Bugun", "week": "Bu hafta", "month": "Bu oy"}


def _book_period(data) -> tuple[str, str]:
    book = data.get("book") if data.get("book") in BOOKS else "biznes"
    period = data.get("p") if data.get("p") in PERIODS else "month"
    return book, period


def _cash_back(book: str, period: str, **flash) -> web.HTTPSeeOther:
    return web.HTTPSeeOther("/cash?" + urlencode({"book": book, "p": period, **flash}))


async def _cash_categories(db: Database, book: str) -> dict[str, list[str]]:
    """Tayyor kategoriyalar + o'zingiz yozganlari («Boshqa» oxirida qoladi)."""
    out = {}
    for kind in ("chiqim", "kirim"):
        names = list(CATEGORIES[(book, kind)])
        for c in await db.cash_categories_used(book, kind):
            if c.lower() not in {n.lower() for n in names}:
                names.insert(len(names) - 1, c)
        out[kind] = names
    return out


def _totals(entries: list[dict]) -> dict[str, dict[str, int]]:
    t: dict[str, dict[str, int]] = {}
    for e in entries:
        t.setdefault(e["currency"], {"kirim": 0, "chiqim": 0})[e["kind"]] += e["amount"]
    return t


async def _limits_state(db: Database, book: str) -> list[dict]:
    first, last = (d.isoformat() for d in month_range(today()))
    out = []
    for lim in await db.cash_limits(book):
        spent = await db.cash_spent(book, lim["category"], lim["currency"], first, last)
        out.append({**dict(lim), "spent": spent})
    return out


async def cash_page(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    db: Database = request.app["db"]
    q = request.query
    book, period = _book_period(q)
    first, last = period_range(period, today())
    entries = await db.cash_entries(book, first.isoformat(), last.isoformat())
    totals, overall = _totals(entries), _totals(await db.cash_entries(book))
    limits = await _limits_state(db, book)

    zero = {"kirim": 0, "chiqim": 0}
    t, o = totals.get("UZS", zero), overall.get("UZS", zero)
    summary = (f'<div class="sum3"><div><span class="eyebrow">Kirim</span><b>+{fmt_money(t["kirim"])}</b></div>'
               f'<div><span class="eyebrow">Chiqim</span><b>−{fmt_money(t["chiqim"])}</b></div>'
               f'<div><span class="eyebrow">Qoldi</span><b>{fmt_money(t["kirim"] - t["chiqim"])}</b></div></div>'
               f'<div class="meta" style="color:inherit;opacity:.85;margin-top:8px">'
               f'Kassada jami: {fmt_money(o["kirim"] - o["chiqim"])}')
    if "USD" in overall:
        u, uo = totals.get("USD", zero), overall["USD"]
        summary += (f'<br>Dollar: +{fmt_cur(u["kirim"], "USD")} / −{fmt_cur(u["chiqim"], "USD")}'
                    f' · jami {fmt_cur(uo["kirim"] - uo["chiqim"], "USD")}')
    summary += '</div>'

    hidden = f'<input type="hidden" name="book" value="{book}"><input type="hidden" name="p" value="{period}">'
    lines, day = [], None
    for e in entries:
        if e["day"] != day:
            day = e["day"]
            lines.append(f'<div class="day">{fmt_date(day)}</div>')
        sign, cls = ("+", "in") if e["kind"] == "kirim" else ("−", "out")
        delete = (f'<form method="post" action="/cash/del" onsubmit="return confirm(&quot;O&#39;chirilsinmi?&quot;)">'
                  f'<input type="hidden" name="id" value="{e["id"]}">{hidden}'
                  f'<button class="x" type="submit" aria-label="O&#39;chirish">×</button></form>'
                  if e["src"] == "cash" else '<span class="x" title="Zakaz to&#39;lovi">🔗</span>')
        note = f'<div class="meta">{escape(e["note"])}</div>' if e["note"] else ""
        lines.append(f'<div class="line"><div><div class="cat">{escape(e["category"])}</div>{note}</div>'
                     f'<div class="amt {cls}">{sign}{fmt_cur(e["amount"], e["currency"])}</div>{delete}</div>')
    ledger = (f'<section class="ledger">{"".join(lines)}</section>' if lines else
              f'<div class="empty">{CASH_EMPTY[period]} hali hech narsa yozilmagan.</div>')

    m = q.get("m", "")
    msg_html = ""
    if m in CASH_FLASH:
        cls, text = CASH_FLASH[m]
        msg_html = f'<div class="msg {cls}">{escape(text.format(info=q.get("info", "")))}</div>'
    over = [x for x in limits if x["spent"] > x["amount"]]
    if over and m != "limit":
        msg_html += ('<div class="msg err">⚠️ Bu oy limitdan oshgan: ' + ", ".join(
            f'{escape(x["category"])} ({fmt_cur(x["spent"], x["currency"])} / {fmt_cur(x["amount"], x["currency"])})'
            for x in over) + '</div>')

    limit_rows = "".join(
        f'<div class="ev"><div class="top"><span><b>{escape(x["category"])}</b></span>'
        f'<span class="num">{fmt_cur(x["spent"], x["currency"])} / {fmt_cur(x["amount"], x["currency"])}</span></div>'
        f'<div class="progress{" over" if x["spent"] > x["amount"] else ""}"><span style="width:'
        f'{min(100, round(x["spent"] * 100 / x["amount"]))}%"></span></div></div>'
        for x in limits
    ) or '<div class="meta">Hali limit qo\'yilmagan.</div>'
    cat_options = "".join(f'<option value="{attr(n)}">' for n in (await _cash_categories(db, book))["chiqim"])
    cur_options = "".join(f'<option value="{c}">{label}</option>' for c, label in CURRENCIES.items())
    cur = ' aria-current="page"'
    book_tabs = "".join(f'<a href="/cash?book={b}&p={period}"{cur if b == book else ""}>{label}</a>'
                        for b, label in BOOKS.items())
    period_tabs = "".join(f'<a href="/cash?book={book}&p={p}"{cur if p == period else ""}>{label}</a>'
                          for p, label in PERIODS.items())
    span = fmt_date(first.isoformat()) if period == "day" else f"{first:%d.%m} – {last:%d.%m.%Y}"
    biz_note = ('<div class="meta" style="text-align:center">Zakaz to&#39;lovlari kirimga o&#39;zi tushadi.</div>'
                if book == "biznes" else "")
    new = f"/cash/new?book={book}&p={period}&kind="
    return page("Kirim-chiqim", f"""
<div class="wrap">
  <header><h1>Kirim-chiqim</h1><a class="btn" href="/">← Zakazlar</a></header>
  <nav class="tabs two">{book_tabs}</nav>
  {msg_html}
  <div class="bigbtns"><a class="btn out" href="{new}chiqim">➖ Chiqim</a>
    <a class="btn in" href="{new}kirim">➕ Kirim</a></div>
  {biz_note}
  <nav class="tabs">{period_tabs}</nav>
  <section class="total" style="display:block">{summary}</section>
  <h2>{span}</h2>
  {ledger}
  <details class="row"{" open" if over else ""}><summary><b>🎯 Oylik limitlar</b>
    <span class="meta">— chiqim limitdan oshsa ogohlantiradi</span></summary>
    {limit_rows}
    <form class="card" method="post" action="/cash/limit">{hidden}
      <div class="grid2">
        <label>Kategoriya<input name="category" list="cash-cats" required maxlength="40" placeholder="Reklama"></label>
        <label>Oyiga ko'pi bilan<input name="amount" required placeholder="2 mln (0 — o'chirish)"></label></div>
      <div class="inline"><select name="currency" aria-label="Valyuta">{cur_options}</select>
        <button type="submit">Limitni saqlash</button></div>
    </form></details>
  <datalist id="cash-cats">{cat_options}</datalist>
</div>""")


async def cash_new(request: web.Request) -> web.Response:
    """Bitta kirim yoki chiqimni yozish: summa → kategoriya → saqlash."""
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    q = request.query
    book, period = _book_period(q)
    kind = "kirim" if q.get("kind") == "kirim" else "chiqim"
    names = (await _cash_categories(request.app["db"], book))[kind]
    chips = "".join(
        f'<label class="chip"><input type="radio" name="cat_{kind}" value="{attr(n)}"><span>{escape(n)}</span></label>'
        for n in names
    )
    currencies = "".join(
        f'<label class="chip"><input type="radio" name="currency" value="{c}"{" checked" if c == "UZS" else ""}>'
        f'<span>{label}</span></label>'
        for c, label in CURRENCIES.items()
    )
    title = "➕ Kirim" if kind == "kirim" else "➖ Chiqim"
    err = f'<div class="msg err">{CASH_FLASH["bad"][1]}</div>' if q.get("m") == "bad" else ""
    return page(title, f"""
<div class="wrap">
  <header><h1>{title} · {BOOKS[book]}</h1><a class="btn" href="/cash?book={book}&p={period}">← Orqaga</a></header>
  {err}
  <form class="card" method="post" action="/cash/add">
    <input type="hidden" name="book" value="{book}"><input type="hidden" name="p" value="{period}">
    <input type="hidden" name="kind" value="{kind}">
    <label>Qancha?<input class="amountbig" name="amount" inputmode="numeric" required autofocus
      placeholder="150 000" autocomplete="off"></label>
    <div class="chips">{currencies}</div>
    <div><div class="meta" style="margin-bottom:6px">Nimaga?</div><div class="chips">{chips}</div></div>
    <label>Ro'yxatda yo'q bo'lsa, yozing<input name="cat_custom" maxlength="40" placeholder="Masalan: Internet"></label>
    <label>Izoh (ixtiyoriy)<input name="note" maxlength="200" placeholder="Nexia, 20 litr"></label>
    <details class="fold"><summary>📅 Bugun emas, boshqa kun</summary>
      <label>Sana<input type="date" name="day" value="{today().isoformat()}" required></label></details>
    <button class="primary" type="submit" style="padding:16px">Saqlash</button>
  </form>
</div>""")


async def _cash_save(request: web.Request, book: str, period: str, e: dict) -> None:
    db: Database = request.app["db"]
    await db.cash_add(book, e["kind"], e["amount"], e["currency"], e["category"], e["note"] or None, e["day"])
    info = (f'{"+" if e["kind"] == "kirim" else "−"}{fmt_cur(e["amount"], e["currency"])} · {e["category"]}'
            + (f' · {e["note"]}' if e["note"] else ""))
    lim = await db.cash_limit_get(book, e["category"], e["currency"])
    if e["kind"] == "chiqim" and lim:
        first, last = (d.isoformat() for d in month_range(date.fromisoformat(e["day"])))
        spent = await db.cash_spent(book, e["category"], e["currency"], first, last)
        if spent > lim["amount"]:
            text = (f'{e["category"]}: bu oy {fmt_cur(spent, e["currency"])}, '
                    f'limit {fmt_cur(lim["amount"], e["currency"])}')
            if spent - e["amount"] <= lim["amount"]:  # aynan shu yozuv limitdan oshirdi
                await notify_admins(request.app["bot"], db,
                                    f"⚠️ Oylik limit oshdi ({BOOKS[book]}): <b>{escape(text)}</b>")
            raise _cash_back(book, period, m="limit", info=f"{info}. {text}")
    raise _cash_back(book, period, m="saved", info=info)


async def cash_add(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    get = lambda k: str(form.get(k, "")).strip()  # noqa: E731
    book, period = _book_period(form)
    kind = "kirim" if get("kind") == "kirim" else "chiqim"
    amount = parse_money(get("amount"))
    try:
        day = date.fromisoformat(get("day")).isoformat()
    except ValueError:
        day = None
    if not amount or not day:
        raise web.HTTPSeeOther("/cash/new?" + urlencode({"book": book, "p": period, "kind": kind, "m": "bad"}))
    category = (get("cat_custom") or get(f"cat_{kind}") or DEFAULT_CATEGORY[kind])[:40]
    await _cash_save(request, book, period, {
        "kind": kind, "amount": amount, "currency": "USD" if get("currency") == "USD" else "UZS",
        "category": category, "note": get("note")[:200], "day": day,
    })


async def cash_del(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    book, period = _book_period(form)
    try:
        await request.app["db"].cash_delete(int(form.get("id", "")))
    except ValueError:
        raise _cash_back(book, period)
    raise _cash_back(book, period, m="deleted")


async def cash_limit(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    book, period = _book_period(form)
    category = str(form.get("category", "")).strip()[:40]
    amount = parse_money(str(form.get("amount", "")))
    if not category or amount is None or category == ORDER_CATEGORY:
        raise _cash_back(book, period, m="bad")
    currency = "USD" if form.get("currency") == "USD" else "UZS"
    known = (await _cash_categories(request.app["db"], book))["chiqim"]
    category = next((n for n in known if n.lower() == category.lower()), category)  # «reklama» -> «Reklama»
    await request.app["db"].cash_limit_set(book, category, currency, amount)
    raise _cash_back(book, period, m="limit_set")


# ---------- Maosh: oylik + har tadbir uchun, srochne foto savdosi ----------

PAYOUT_CATEGORY = "Operatorlarga maosh"
MONTH_NAMES = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr",
               "noyabr", "dekabr"]
PAY_FLASH = {"rates": ("", "✅ Stavka saqlandi."), "paid": ("", "✅ To'lov yozildi — Kassada ham ko'rinadi."),
             "price": ("", "✅ Srochne foto narxi saqlandi."), "bad": ("err", "Summani to'g'ri yozing.")}


def _month(value: str) -> date:
    try:
        return date.fromisoformat(value + "-01")
    except ValueError:
        return today().replace(day=1)


def _shift(d: date, months: int) -> str:
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return f"{y}-{m + 1:02d}"


async def payroll_page(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    db: Database = request.app["db"]
    m = _month(request.query.get("m", ""))
    first, last = (d.isoformat() for d in month_range(m))
    mkey = f"{m.year}-{m.month:02d}"
    rows = await db.payroll(first, last)
    price = int(await db.setting_get("foto_narx", "0") or 0)
    sales = await db.sales_between(first, last)
    missing = await db.sales_missing(first, min(last, (today() - timedelta(days=1)).isoformat()))
    flash = PAY_FLASH.get(request.query.get("f", ""))
    msg = f'<div class="msg {flash[0]}">{flash[1]}</div>' if flash else ""

    cards = []
    for r in rows:
        left = r["left"]
        status = (f'<span class="owe">{fmt_money(left)}<small>berish kerak</small></span>' if left > 0 else
                  f'<span class="owe ok">{fmt_money(-left) if left else "0 so\'m"}<small>{"ortiqcha berilgan" if left else "hisob yopiq"}</small></span>')
        hidden = f'<input type="hidden" name="id" value="{r["id"]}"><input type="hidden" name="m" value="{mkey}">'
        cards.append(f"""
<article class="row">
  <div class="top"><div><div class="name">{escape(r["name"])}</div>
    <div class="meta">{ROLES.get(r["role"], r["role"])} · {r["events"]} ta tadbir{"" if r["tg_id"] else " · botga ulanmagan"}</div></div>
    {status}</div>
  <div class="pays">
    <div><span>Oylik</span><span class="num">{fmt_money(r["salary"])}</span></div>
    <div><span>Tadbirlar uchun ({r["events"]} ta)</span><span class="num">{fmt_money(r["event_pay"])}</span></div>
    <div><span><b>Hisoblandi</b></span><span class="num"><b>{fmt_money(r["earned"])}</b></span></div>
    <div><span>Berildi</span><span class="num">{fmt_money(r["paid"])}</span></div>
  </div>
  <form class="inline" method="post" action="/maosh/pay" onsubmit="return confirm(&quot;{attr(r["name"])}ga to'lov yozilsinmi?&quot;)">{hidden}
    <input name="amount" inputmode="numeric" placeholder="{fmt_money(max(left, 0))}" value="{max(left, 0) or ''}" aria-label="Summa">
    <button class="okbtn" type="submit">💵 To'lash</button></form>
  <details><summary class="meta">Stavkani o'zgartirish</summary>
  <form class="card" method="post" action="/maosh/rates" style="margin-top:8px">{hidden}
    <div class="grid2"><label>Oylik<input name="salary" inputmode="numeric" value="{r["salary"] or ''}" placeholder="0"></label>
    <label>Har tadbir uchun<input name="rate" inputmode="numeric" value="{r["event_rate"] or ''}" placeholder="300 000"></label></div>
    <div class="meta">«Har tadbir uchun» — yangi zakazlarda summa yozilmasa shu qo'yiladi. Zakaz shablonida «Orif 350» deb boshqa summa yozish mumkin.</div>
    <button type="submit">Saqlash</button></form></details>
</article>""")

    sale_lines = "".join(
        f'<div><span>{_short(s_["date"])} {escape(s_["type_name"])} · {escape(s_["client_name"])} — {escape(s_["staff_name"])}, '
        f'{s_["count"]} ta × {fmt_money(s_["price"])}</span><span class="num">{fmt_money(s_["amount"])}</span></div>'
        for s_ in sales)
    miss_lines = "".join(f'<div class="ev">⚠️ {_short(x["date"])} {escape(x["type_name"])} · {escape(x["client_name"])} — '
                         f'{escape(x["staff_name"])} savdoni yozmagan</div>' for x in missing)
    total_paid = sum(r["paid"] for r in rows)
    total_left = sum(max(r["left"], 0) for r in rows)
    return page("Maosh", f"""
<div class="wrap">
  <header><h1>👷 Maosh</h1><a class="btn" href="/">← Orqaga</a></header>
  <div class="actions"><a class="btn" href="/maosh?m={_shift(m, -1)}">‹</a>
    <b style="flex:1;text-align:center">{MONTH_NAMES[m.month - 1].capitalize()} {m.year}</b>
    <a class="btn" href="/maosh?m={_shift(m, 1)}">›</a></div>
  <section class="total"><div><div class="eyebrow">Xodimlarga berish kerak</div><div class="big">{fmt_money(total_left)}</div></div>
    <div class="side">Berildi: {fmt_money(total_paid)}</div></section>
  {msg}
  {"".join(cards) or '<div class="empty">Xodim yo&#39;q</div>'}
  <section class="row"><div class="name">📸 Srochne foto</div>
    <form class="inline" method="post" action="/maosh/price"><input type="hidden" name="m" value="{mkey}">
      <input name="price" inputmode="numeric" value="{price or ''}" placeholder="Bitta rasm narxi, masalan 25 000" aria-label="Rasm narxi">
      <button type="submit">Saqlash</button></form>
    <div class="meta">Srochne fotochi to'ydan keyin botga nechta rasm sotganini yozadi — summa shu narxga ko'paytiriladi va Kassaga tushadi.</div>
    <div class="pays">{sale_lines or "<div>Bu oyda savdo yozilmagan.</div>"}
      {f'<div><span><b>Jami</b></span><span class="num"><b>{fmt_money(sum(x["amount"] for x in sales))}</b></span></div>' if sales else ""}</div>
    {miss_lines}
  </section>
</div>""")


def _short(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"


async def payroll_rates(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    salary, rate = parse_money(str(form.get("salary") or "0")), parse_money(str(form.get("rate") or "0"))
    try:
        staff_id = int(form.get("id", ""))
    except ValueError:
        staff_id = 0
    mkey = str(form.get("m", ""))[:7]
    if salary is None or rate is None or not staff_id:
        raise web.HTTPSeeOther(f"/maosh?m={mkey}&f=bad")
    await request.app["db"].staff_rates_set(staff_id, salary, rate)
    raise web.HTTPSeeOther(f"/maosh?m={mkey}&f=rates")


async def payroll_pay(request: web.Request) -> web.Response:
    """To'lov Kassaga Studiya chiqimi bo'lib yoziladi; xodimga botda xabar boradi."""
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    db: Database = request.app["db"]
    form = await request.post()
    amount = parse_money(str(form.get("amount") or ""))
    m = _month(str(form.get("m", ""))[:7])
    mkey = f"{m.year}-{m.month:02d}"
    try:
        staff = await db.staff_get(int(form.get("id", "")))
    except ValueError:
        staff = None
    if not amount or not staff:
        raise web.HTTPSeeOther(f"/maosh?m={mkey}&f=bad")
    label = f"{MONTH_NAMES[m.month - 1]} {m.year}"
    await db.cash_add("biznes", "chiqim", amount, "UZS", PAYOUT_CATEGORY, f"{staff['name']} · {label}",
                      today().isoformat(), staff_id=staff["id"], pay_month=mkey)
    if staff["tg_id"]:
        first, last = (d.isoformat() for d in month_range(m))
        r = next((x for x in await db.payroll(first, last) if x["id"] == staff["id"]), None)
        tail = (f"\n{label.capitalize()}: hisoblandi {fmt_money(r['earned'])}, berildi {fmt_money(r['paid'])}"
                + (f", qoldi {fmt_money(r['left'])}" if r["left"] > 0 else "")) if r else ""
        try:
            await request.app["bot"].send_message(staff["tg_id"], f"💵 Sizga <b>{fmt_money(amount)}</b> berildi ({label} maoshi).{tail}")
        except Exception as e:
            log.warning("Maosh xabari %s ga bormadi: %s", staff["name"], e)
    raise web.HTTPSeeOther(f"/maosh?m={mkey}&f=paid")


async def payroll_price(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    price = parse_money(str(form.get("price") or ""))
    mkey = str(form.get("m", ""))[:7]
    if price is None:
        raise web.HTTPSeeOther(f"/maosh?m={mkey}&f=bad")
    await request.app["db"].setting_set("foto_narx", str(price))
    raise web.HTTPSeeOther(f"/maosh?m={mkey}&f=price")


# ---------- Kirish ----------

async def take_request(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    db: Database = request.app["db"]
    try:
        req_id = int((await request.post()).get("id", 0))
    except ValueError:
        raise _back("sorov")
    if await db.site_request_take(req_id, "Sayt (admin)"):
        r = await db.site_request_get(req_id)
        await notify_admins(request.app["bot"], db,
                            f"✅ So'rov №{req_id} ({escape(r['name'])}) saytda qabul qilindi.")
    raise _back("sorov")


# ---------- Ochiq sayt: rasm/video va kontaktlar ----------

MEDIA_TABS = {"dekorlar": "Dekorlar", "taklifnomalar": "Taklifnomalar", "albomlar": "Albomlar",
              "roliklar": "Roliklar", "studiya": "Studiya", "jamoa": "Jamoa", "bosh": "Bosh video",
              "sozlamalar": "Kontaktlar"}
MEDIA_HINT = {
    "jamoa": "Rasm nomi yoki sarlavha: «Ism - lavozim», masalan «Orif Rahmatov - operator».",
    "bosh": "Bosh sahifadagi katta fon: bitta video (.mp4) yoki rasm. Yangisi eskisini almashtiradi.",
    "roliklar": "Video fayl yuklang yoki pastda YouTube havolalarini yozing.",
}
MAX_UPLOAD = 300 * 1024 * 1024  # bitta fayl: 300 MB
BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SETTING_LABELS = {"telefon": ("Telefon", "+998 91 943 76 76"), "telegram": ("Telegram", "@elegantmedia"),
                  "instagram": ("Instagram", "elegant.media"), "youtube": ("YouTube kanal havolasi", "https://youtube.com/@..."),
                  "manzil": ("Manzil", "Toshkent, ..."), "xarita": ("Xarita havolasi", "https://maps.app.goo.gl/..."),
                  "ish_vaqti": ("Ish vaqti", "Har kuni 09:00–21:00")}
MEDIA_FLASH = {"up": ("", "✅ Yuklandi — saytda ko'rinadi."), "del": ("", "🗑 O'chirildi."), "set": ("", "✅ Saqlandi."),
               "bad": ("err", "Fayl rasm yoki video emas yoki juda katta (300 MB dan ko'p).")}


def _media_folder(section: str) -> Path:
    return MEDIA if section == "bosh" else MEDIA / section


def _media_files(section: str) -> list[Path]:
    folder = _media_folder(section)
    if not folder.is_dir():
        return []
    files = [f for f in sorted(folder.iterdir()) if f.suffix.lower() in IMAGE_EXT | VIDEO_EXT]
    return [f for f in files if f.stem == "hero"] if section == "bosh" else files


def _media_card(section: str, f: Path) -> str:
    src = attr(f"/sayt/media/{'' if section == 'bosh' else section + '/'}{f.name}")
    style = "width:100%;border-radius:8px;aspect-ratio:4/3;object-fit:cover;background:#000"
    preview = (f'<video src="{src}" muted preload="metadata" style="{style}"></video>' if f.suffix.lower() in VIDEO_EXT
               else f'<img src="{src}" alt="" loading="lazy" style="{style}">')
    return (f'<div class="row" style="padding:8px;gap:6px">{preview}'
            f'<div class="meta" style="color:var(--ink)">{escape(f.stem)}</div>'
            f'<form method="post" action="/media/del"><input type="hidden" name="s" value="{section}">'
            f'<input type="hidden" name="f" value="{attr(f.name)}">'
            f"<button type=\"submit\" style=\"width:100%\">🗑 O'chirish</button></form></div>")


async def media_page(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    sec = request.query.get("s", "dekorlar")
    sec = sec if sec in MEDIA_TABS else "dekorlar"
    tabs = "".join(f'<label class="chip"><input type="radio"{" checked" if k == sec else ""} '
                   f'onclick="location=\'/media?s={k}\'"><span>{v}</span></label>' for k, v in MEDIA_TABS.items())
    flash = MEDIA_FLASH.get(request.query.get("m", ""))
    msg = f'<div class="msg {flash[0]}">{flash[1]}</div>' if flash else ""
    if sec == "sozlamalar":
        st = load_settings()
        fields = "".join(f'<label>{lab}<input name="{k}" value="{attr(st[k])}" placeholder="{attr(ph)}"></label>'
                         for k, (lab, ph) in SETTING_LABELS.items())
        body = (f'<form class="card" method="post" action="/media/settings"><fieldset><legend>Saytdagi kontaktlar</legend>'
                f'{fields}</fieldset><button class="primary" type="submit">Saqlash</button></form>')
    else:
        files = _media_files(sec)
        links = ""
        if sec == "roliklar":
            path = MEDIA / "roliklar" / "havolalar.txt"
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            links = ('<form class="card" method="post" action="/media/links"><fieldset><legend>YouTube havolalari</legend>'
                     '<label>Har qatorda: Sarlavha | havola<textarea name="links" rows="5" '
                     f"placeholder=\"Aziz va Madina to'yi | https://youtu.be/...\">{escape(text)}</textarea></label>"
                     '<button class="primary" type="submit">Saqlash</button></fieldset></form>')
        hint = MEDIA_HINT.get(sec, "Bir nechta rasm yoki videoni birdan tanlash mumkin. Fayl nomi — saytdagi sarlavha.")
        body = f"""
  <form class="card" method="post" action="/media/upload?s={sec}" enctype="multipart/form-data">
    <fieldset><legend>Yangi: {MEDIA_TABS[sec].lower()}</legend>
      <div class="meta">{hint}</div>
      <label>Sarlavha (ixtiyoriy, bitta fayl uchun)<input name="title" placeholder="Masalan: Oq atirgul"></label>
      <label>Fayllar<input type="file" name="files" accept="image/*,video/*"{"" if sec == "bosh" else " multiple"} required></label>
      <button class="primary" type="submit">⬆️ Yuklash</button>
    </fieldset></form>
  {links}
  <div class="meta">Saytda: {len(files)} ta fayl</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px">
    {"".join(_media_card(sec, f) for f in files)}</div>"""
    return page("Sayt rasmlari", f"""
<div class="wrap">
  <header><h1>🖼 Sayt</h1><div class="actions"><a class="btn" href="/sayt" target="_blank">Saytni ochish ↗</a>
    <a class="btn" href="/">← Orqaga</a></div></header>
  <div class="chips">{tabs}</div>
  {msg}
  {body}
</div>""")


def _safe_name(name: str) -> str:
    name = BAD_NAME.sub(" ", name).strip(" .")
    return re.sub(r"\s+", " ", name)[:80] or "fayl"


async def media_upload(request: web.Request) -> web.Response:
    """Fayllar oqim bilan diskka yoziladi (katta video ham xotirani to'ldirmaydi)."""
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    sec = request.query.get("s", "")
    if sec not in MEDIA_TABS or sec == "sozlamalar":
        raise web.HTTPSeeOther("/media")
    folder = _media_folder(sec)
    folder.mkdir(parents=True, exist_ok=True)
    reader = await request.multipart()
    title, saved, bad = "", 0, False
    while (part := await reader.next()) is not None:
        if part.name == "title":
            title = (await part.text()).strip()
            continue
        if part.name != "files" or not part.filename:
            continue
        ext = Path(part.filename).suffix.lower()
        if ext not in IMAGE_EXT | VIDEO_EXT:
            bad = True
            continue
        if sec == "bosh":
            for old in _media_files("bosh"):
                old.unlink()
            stem = "hero"
        else:
            # telefon nomi «02 Oltin sahna» bo'lsa ham raqam ikki marta chiqmasin
            name = _safe_name(title if title and not saved else re.sub(r"^\d+\s+", "", Path(part.filename).stem))
            stem = f"{len(_media_files(sec)) + 1:02d} {name}"
        target, n = folder / f"{stem}{ext}", 2
        while target.exists():
            target, n = folder / f"{stem} ({n}){ext}", n + 1
        size = 0
        with open(target, "wb") as fh:
            while chunk := await part.read_chunk(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    break
                fh.write(chunk)
        if size > MAX_UPLOAD or size == 0:
            target.unlink(missing_ok=True)
            bad = True
        else:
            saved += 1
    raise web.HTTPSeeOther(f"/media?s={sec}&m={'up' if saved and not bad else 'bad'}")


async def media_delete(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    sec, name = str(form.get("s", "")), Path(str(form.get("f", ""))).name
    if sec in MEDIA_TABS and sec != "sozlamalar":
        target = _media_folder(sec) / name
        if target in _media_files(sec):  # faqat ro'yxatdagi faylni o'chiradi
            target.unlink()
    raise web.HTTPSeeOther(f"/media?s={sec}&m=del")


async def media_links(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    text = str((await request.post()).get("links", ""))
    lines = [line.strip() for line in text.splitlines() if "https://" in line][:100]
    folder = MEDIA / "roliklar"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "havolalar.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    raise web.HTTPSeeOther("/media?s=roliklar&m=set")


async def media_settings(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    save_settings(dict(await request.post()))
    raise web.HTTPSeeOther("/media?s=sozlamalar&m=set")


async def login(request: web.Request) -> web.Response:
    ip = _ip(request)
    if _blocked(ip):
        return login_page("Ko'p marta xato kiritildi. 5 daqiqadan keyin urinib ko'ring.")
    form = await request.post()
    pin = form.get("pin", "")
    nxt = "/kassa/" if form.get("next") == "/kassa/" else "/"  # Kassa ilovasidan kirilsa, o'shanga qaytadi
    if not SITE_PIN or not hmac.compare_digest(str(pin), SITE_PIN):
        _fails.setdefault(ip, []).append(time.time())
        return login_page("PIN-kod noto'g'ri.", nxt)
    resp = web.HTTPSeeOther(nxt)
    resp.set_cookie(COOKIE, _token(), max_age=30 * 24 * 3600, httponly=True,
                    secure=request.secure or request.headers.get("X-Forwarded-Proto") == "https",
                    samesite="Strict")
    raise resp


async def logout(request: web.Request) -> web.Response:
    resp = web.HTTPSeeOther("/")
    resp.del_cookie(COOKIE)
    raise resp


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app(bot: Bot, db: Database, bot_username: str) -> web.Application:
    app = web.Application(client_max_size=15 * 1024 * 1024)  # dekor rasmlari uchun
    app["bot"], app["db"], app["bot_username"] = bot, db, bot_username
    app.add_routes([
        web.get("/", index), web.get("/new", new_form), web.post("/new", new_save),
        web.post("/login", login), web.post("/logout", logout), web.post("/pay", pay),
        web.post("/editor", set_editor), web.post("/stage", stage), web.get("/health", health),
        web.post("/sorov", take_request),
        web.get("/maosh", payroll_page), web.post("/maosh/rates", payroll_rates), web.post("/maosh/pay", payroll_pay),
        web.post("/maosh/price", payroll_price),
        web.get("/media", media_page), web.post("/media/upload", media_upload), web.post("/media/del", media_delete),
        web.post("/media/links", media_links), web.post("/media/settings", media_settings),
        web.get("/cash", cash_page), web.get("/cash/new", cash_new), web.post("/cash/add", cash_add),
        web.post("/cash/del", cash_del), web.post("/cash/limit", cash_limit),
    ])
    add_site_routes(app)
    add_kassa_routes(app, _authed)
    return app


async def start_web(bot: Bot, db: Database) -> web.AppRunner | None:
    if not WEB_PORT:
        return None
    runner = web.AppRunner(build_app(bot, db, (await bot.me()).username), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    log.info("Sayt ishga tushdi: port %s%s", WEB_PORT, "" if SITE_PIN else " (SITE_PIN yo'q — yopiq)")
    return runner
