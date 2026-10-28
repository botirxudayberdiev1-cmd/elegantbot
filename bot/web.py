"""Zakazlar va qarzdorlar sayti — bot bilan bir jarayonda, bitta bazadan o'qiydi.

PORT (Railway beradi) yoki WEB_PORT bo'lsa ishga tushadi. Kirish — SITE_PIN bilan.
Saytdan kiritilgan to'lov adminlarga Telegramda xabar qilinadi.
"""

import hashlib
import hmac
import logging
import time
from datetime import date

from aiogram import Bot
from aiohttp import web

from .config import BOT_TOKEN, SITE_PIN, WEB_PORT
from .db import Database
from .utils import escape, fmt_date, fmt_money, notify_admins, parse_money, today

log = logging.getLogger(__name__)
COOKIE = "em_site"
MAX_FAILS, BLOCK_SECONDS = 5, 300
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


# ---------- Sahifa ----------

STYLE = """
:root{--bg:#f7f4f6;--surface:#fff;--ink:#24161f;--muted:#7a6872;--line:#e6dde2;--accent:#7b2350;
--accent-soft:#f3e3eb;--debt:#b4232f;--debt-soft:#fbe6e7;--ok:#1f7a4d;--ok-soft:#e1f2e8;--on-accent:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#17111a;--surface:#221a24;--ink:#f2e9ee;--muted:#a8969f;
--line:#382b36;--accent:#e08ab4;--accent-soft:#3a2231;--debt:#ff8a8f;--debt-soft:#3d1f24;--ok:#6fd3a0;
--ok-soft:#1b3328;--on-accent:#1a0f15}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 "Golos Text",system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:720px;margin:0 auto;padding:20px 16px 48px;display:flex;flex-direction:column;gap:16px}
h1{font:700 1.35rem "Unbounded",system-ui,sans-serif;margin:0}
.eyebrow{font-size:.72rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);font-weight:600}
.num{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
header{display:flex;justify-content:space-between;align-items:center;gap:12px}
.total{background:var(--accent);color:var(--on-accent);border-radius:16px;padding:18px;display:grid;grid-template-columns:1fr auto;gap:6px 16px;align-items:end}
.total .eyebrow{color:inherit;opacity:.75}.total .big{font:500 1.7rem "JetBrains Mono",monospace;line-height:1.1;word-break:break-word}
.total .side{text-align:right;font-size:.85rem;opacity:.9}
@media (max-width:480px){.total{grid-template-columns:1fr}.total .side{text-align:left}.total .big{font-size:1.5rem}}
.tabs{display:grid;grid-template-columns:1fr 1fr;gap:4px;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:4px}
.tabs a{display:block;text-align:center;padding:10px 8px;border-radius:9px;font-weight:600;color:var(--muted);text-decoration:none}
.tabs a[aria-current]{background:var(--accent-soft);color:var(--accent)}
.row{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:10px}
.top{display:grid;grid-template-columns:1fr auto;gap:4px 12px}
.name{font-weight:600;font-size:1.02rem;overflow-wrap:anywhere}.meta{color:var(--muted);font-size:.84rem;overflow-wrap:anywhere}
.owe{text-align:right;font:1.05rem "JetBrains Mono",monospace;color:var(--debt);white-space:nowrap}
.owe small{display:block;font:.75rem "Golos Text",system-ui,sans-serif;color:var(--muted)}
.pill{display:inline-block;font-size:.72rem;font-weight:600;padding:2px 8px;border-radius:999px;background:var(--debt-soft);color:var(--debt)}
.pill.ok{background:var(--ok-soft);color:var(--ok)}.pill.plain{background:var(--accent-soft);color:var(--accent)}
.progress{height:6px;border-radius:99px;background:var(--debt-soft);overflow:hidden}.progress span{display:block;height:100%;background:var(--ok)}
.ev{font-size:.86rem;border-top:1px dashed var(--line);padding-top:6px;overflow-wrap:anywhere}
.pays{border-top:1px dashed var(--line);padding-top:8px;display:flex;flex-direction:column;gap:4px;font-size:.85rem;color:var(--muted)}
.pays div{display:flex;justify-content:space-between;gap:8px}
form.pay{display:grid;grid-template-columns:1fr auto;gap:8px}
input,button{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:9px 12px;min-width:0}
button{cursor:pointer;font-weight:500}.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
input:focus,button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.actions{display:flex;gap:8px;flex-wrap:wrap}
.empty{text-align:center;padding:36px 16px;color:var(--muted);border:1px dashed var(--line);border-radius:14px}
.msg{padding:10px 12px;border-radius:10px;background:var(--ok-soft);color:var(--ok)}.msg.err{background:var(--debt-soft);color:var(--debt)}
.login{max-width:340px;margin:12vh auto;display:flex;flex-direction:column;gap:12px}
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


def login_page(error: str = "") -> web.Response:
    err = f'<div class="msg err">{escape(error)}</div>' if error else ""
    return page("Kirish", f"""
<form class="login" method="post" action="/login">
  <div class="eyebrow">Elegant Media</div><h1>Kirish</h1>{err}
  <input name="pin" type="password" inputmode="numeric" autocomplete="current-password" placeholder="PIN-kod" required autofocus>
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


def order_card(o: dict) -> str:
    left = o["total"] - o["paid"]
    pct = min(100, round(o["paid"] * 100 / o["total"])) if o["total"] else 100
    events = "".join(
        f'<div class="ev"><b>{escape(e["type_name"])}</b> · {fmt_date(e["date"])}'
        f'{", " + escape(e["time"]) if e["time"] else ""} {_when(e["date"])}<br>'
        f'<span class="meta">📍 {escape(e["address"] or "—")}'
        f'{" · 👥 " + escape(e["team"]) if e["team"] else ""}</span></div>'
        for e in o["events"]
    )
    pays = "".join(
        f'<div><span>{escape(p["paid_at"][:10])} · {escape(p["note"] or "")}</span>'
        f'<span class="num">{fmt_money(p["amount"])}</span></div>'
        for p in reversed(o["payments"])
    )
    status = ('<span class="pill ok">To\'liq to\'langan</span>' if left <= 0
              else '<span class="pill">Qarzda</span>')
    actions = ""
    if left > 0:
        actions = f"""
<form class="pay" method="post" action="/pay">
  <input type="hidden" name="order" value="{o['id']}">
  <input name="amount" inputmode="numeric" placeholder="To'lov summasi (masalan 500 ming)" required>
  <button class="primary" type="submit">To'lov</button>
</form>
<form method="post" action="/pay" onsubmit="return confirm('Qolgan {fmt_money(left)} to\\'liq to\\'landimi?')">
  <input type="hidden" name="order" value="{o['id']}"><input type="hidden" name="amount" value="{left}">
  <button type="submit">✓ To'liq to'landi</button>
</form>"""
    return f"""
<article class="row">
  <div class="top"><div><div class="name">№{o['id']} · {escape(o['client_name'])}</div>
    <div class="meta">{escape(o['services'] or '')}</div>
    <div class="meta num">{escape(o['client_phone'] or '')}</div></div>
    <div class="owe">{fmt_money(max(left, 0))}<small>{fmt_money(o['total'])} dan</small></div></div>
  <div class="actions" style="align-items:center">{status}<span class="meta">{pct}% to'landi</span></div>
  <div class="progress"><span style="width:{pct}%"></span></div>
  {events}
  {f'<div class="meta">📝 {escape(o["note"])}</div>' if o["note"] else ''}
  <div class="actions">{actions}</div>
  {f'<div class="pays">{pays}</div>' if pays else ''}
</article>"""


async def index(request: web.Request) -> web.Response:
    if not SITE_PIN:
        return page("Sozlanmagan", '<div class="wrap"><div class="empty">Sayt yopiq: Railway\'da '
                                   'SITE_PIN o\'zgaruvchisi o\'rnatilmagan.</div></div>')
    if not _authed(request):
        return login_page()
    db: Database = request.app["db"]
    orders = await db.orders_overview()
    tab = "orders" if request.query.get("tab") == "orders" else "debts"
    debts = [o for o in orders if o["total"] - o["paid"] > 0]
    iso = today().isoformat()
    upcoming = [o for o in orders if any(e["date"] >= iso for e in o["events"])]
    upcoming.sort(key=lambda o: min(e["date"] for e in o["events"] if e["date"] >= iso))

    if tab == "debts":
        debts.sort(key=lambda o: o["paid"] - o["total"])
        summary = (f'<div><div class="eyebrow">Jami qolgan qarz</div>'
                   f'<div class="big">{fmt_money(sum(o["total"] - o["paid"] for o in debts))}</div></div>'
                   f'<div class="side">{len(debts)} nafar qarzdor<br>'
                   f'To\'langan: {fmt_money(sum(o["paid"] for o in orders))}</div>')
        items = "".join(order_card(o) for o in debts) or '<div class="empty">Qarzdor yo\'q 🎉</div>'
    else:
        summary = (f'<div><div class="eyebrow">Kelayotgan zakazlar</div>'
                   f'<div class="big">{len(upcoming)} ta</div></div>'
                   f'<div class="side">Jami: {fmt_money(sum(o["total"] for o in upcoming))}</div>')
        items = "".join(order_card(o) for o in upcoming) or '<div class="empty">Kelayotgan zakaz yo\'q</div>'

    flash = {"ok": ('', "To'lov saqlandi."), "bad": ("err", "Summani tushunmadim yoki u qarzdan katta.")}
    msg = flash.get(request.query.get("m", ""))
    msg_html = f'<div class="msg {msg[0]}">{msg[1]}</div>' if msg else ""
    cur = ' aria-current="page"'
    return page("Elegant Media", f"""
<div class="wrap">
  <header><div><div class="eyebrow">Elegant Media</div><h1>Zakaz va qarzlar</h1></div>
    <form method="post" action="/logout"><button type="submit">Chiqish</button></form></header>
  <nav class="tabs"><a href="/?tab=debts"{cur if tab == 'debts' else ''}>Qarzdorlar · {len(debts)}</a>
    <a href="/?tab=orders"{cur if tab == 'orders' else ''}>Zakazlar · {len(upcoming)}</a></nav>
  <section class="total">{summary}</section>
  {msg_html}
  {items}
  <p class="meta">Ma'lumotlar Telegram botdagi zakazlardan olinadi. Yangi zakaz — botda «➕ Yangi buyurtma».</p>
</div>""")


async def login(request: web.Request) -> web.Response:
    ip = _ip(request)
    if _blocked(ip):
        return login_page("Ko'p marta xato kiritildi. 5 daqiqadan keyin urinib ko'ring.")
    pin = (await request.post()).get("pin", "")
    if not SITE_PIN or not hmac.compare_digest(str(pin), SITE_PIN):
        _fails.setdefault(ip, []).append(time.time())
        return login_page("PIN-kod noto'g'ri.")
    resp = web.HTTPSeeOther("/")
    resp.set_cookie(COOKIE, _token(), max_age=30 * 24 * 3600, httponly=True,
                    secure=request.secure or request.headers.get("X-Forwarded-Proto") == "https",
                    samesite="Strict")
    raise resp


async def logout(request: web.Request) -> web.Response:
    resp = web.HTTPSeeOther("/")
    resp.del_cookie(COOKIE)
    raise resp


async def pay(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    db: Database = request.app["db"]
    try:
        order_id = int(form.get("order", ""))
    except ValueError:
        raise web.HTTPSeeOther("/?m=bad")
    amount = parse_money(str(form.get("amount", "")))
    o = next((x for x in await db.orders_overview() if x["id"] == order_id), None)
    if not o or not amount or amount > o["total"] - o["paid"]:
        raise web.HTTPSeeOther("/?m=bad")
    left = o["total"] - o["paid"] - amount
    await db.payment_add(order_id, amount, "Sayt orqali" if left else "Sayt orqali · to'liq yopildi")
    await notify_admins(
        request.app["bot"], db,
        f"💵 Sayt orqali to'lov: <b>{escape(o['client_name'])}</b> (№{order_id}) — {fmt_money(amount)}\n"
        + (f"Qolgan qarz: {fmt_money(left)}" if left else "✅ Qarz to'liq yopildi"),
    )
    raise web.HTTPSeeOther("/?m=ok")


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def start_web(bot: Bot, db: Database) -> web.AppRunner | None:
    if not WEB_PORT:
        return None
    app = web.Application()
    app["bot"], app["db"] = bot, db
    app.add_routes([
        web.get("/", index), web.post("/login", login), web.post("/logout", logout),
        web.post("/pay", pay), web.get("/health", health),
    ])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    log.info("Sayt ishga tushdi: port %s%s", WEB_PORT, "" if SITE_PIN else " (SITE_PIN yo'q — yopiq)")
    return runner
