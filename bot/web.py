"""Zakaz, montaj va qarzdorlar sayti — bot bilan bir jarayonda, bitta bazadan ishlaydi.

PORT (Railway beradi) yoki WEB_PORT bo'lsa ishga tushadi. Kirish — SITE_PIN bilan.
Zakaz saytda yoziladi; bot xodimlarga karta, montajchiga to'y va mijozga «tayyor» xabarini yuboradi.
"""

import hashlib
import hmac
import logging
import time
from datetime import date
from urllib.parse import urlencode

from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiohttp import web

from .cash import BOOKS, CATEGORIES, CURRENCIES, PERIODS, fmt_cur, month_range, parse_quick, period_range
from .config import ADMIN_IDS, BOT_TOKEN, FIELD_ROLES, ORDER_CATEGORY, ROLES, SITE_PIN, WEB_PORT
from .db import Database
from .montaj import client_ready_text, send_to_client, send_to_editor
from .notify import send_assignment
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
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 "Golos Text",system-ui,-apple-system,"Segoe UI",sans-serif}
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
.tabs{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:4px}
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
button,.btn{cursor:pointer;font-weight:500;width:auto;display:inline-block;text-decoration:none;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:9px 14px}
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
.cashform:has(input[name=kind][value=kirim]:checked) .cats-chiqim,
.cashform:has(input[name=kind][value=chiqim]:checked) .cats-kirim{display:none}
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
    left = o["total"] - o["paid"]
    pct = min(100, round(o["paid"] * 100 / o["total"])) if o["total"] else 100
    events = "".join(
        f'<div class="ev"><b>{escape(e["type_name"])}</b> · {fmt_date(e["date"])}'
        f'{", " + escape(e["time"]) if e["time"] else ""} {_when(e["date"])}<br>'
        f'<span class="meta">📍 {escape(e["address"] or "—")}'
        f'{" · 👥 " + escape(e["team"]) if e["team"] else " · 👥 xodim yo&#39;q"}</span></div>'
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
<form class="inline" method="post" action="/pay">
  <input type="hidden" name="order" value="{o['id']}">
  <input name="amount" inputmode="numeric" placeholder="To'lov (masalan 500 ming)" required>
  <button class="primary" type="submit">To'lov</button>
</form>
<form method="post" action="/pay" onsubmit="return confirm('Qolgan {fmt_money(left)} to\\'liq to\\'landimi?')">
  <input type="hidden" name="order" value="{o['id']}"><input type="hidden" name="amount" value="{left}">
  <button type="submit">✓ To'liq to'landi</button>
</form>"""
    client = ('<span class="meta">🤖 Mijoz botga ulangan</span>' if o["client_tg_id"] else
              f'<details><summary class="meta">🔗 Mijoz havolasi (tayyor bo\'lganda bot o\'zi xabar beradi)</summary>'
              f'<input readonly onclick="this.select()" value="https://t.me/{attr(bot_username)}?start=o_{attr(o["client_token"])}">'
              f'</details>')
    return f"""
<article class="row">
  <div class="top"><div><div class="name">№{o['id']} · {escape(o['client_name'])}</div>
    <div class="meta">{escape(o['services'] or '')}</div>
    <div class="meta num">{escape(o['client_phone'] or '')}</div></div>
    <div class="owe{' ok' if left <= 0 else ''}">{fmt_money(max(left, 0))}<small>{fmt_money(o['total'])} dan</small></div></div>
  <div class="actions">{'<span class="pill ok">To&#39;liq to&#39;langan</span>' if left <= 0 else '<span class="pill">Qarzda</span>'}
    <span class="meta">{pct}% to'landi</span></div>
  <div class="progress"><span style="width:{pct}%"></span></div>
  {events}
  {f'<div class="meta">📝 {escape(o["note"])}</div>' if o["note"] else ''}
  {stage_block(o, editors, bot_username) if show_stage else ''}
  {client}
  <div class="actions">{pay}</div>
  {f'<div class="pays">{pays}</div>' if pays else ''}
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

    if tab == "debts":
        summary = (f'<div><div class="eyebrow">Jami qolgan qarz</div>'
                   f'<div class="big">{fmt_money(sum(o["total"] - o["paid"] for o in debts))}</div></div>'
                   f'<div class="side">{len(debts)} nafar qarzdor<br>'
                   f'To\'langan: {fmt_money(sum(o["paid"] for o in orders))}</div>')
        items = "".join(order_card(o, editors, username, True) for o in debts) or '<div class="empty">Qarzdor yo\'q 🎉</div>'
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
  <header><div><div class="eyebrow">Elegant Media</div><h1>Zakaz va qarzlar</h1></div>
    <div class="actions"><a class="btn primary" href="/new">+ Yangi zakaz</a>
    <a class="btn" href="/cash">💰 Kirim-chiqim</a>
    <form method="post" action="/logout"><button type="submit">Chiqish</button></form></div></header>
  <nav class="tabs">
    <a href="/?tab=orders"{cur if tab == 'orders' else ''}>Zakazlar · {len(upcoming)}</a>
    <a href="/?tab=montaj"{cur if tab == 'montaj' else ''}>Montaj · {len(montaj)}</a>
    <a href="/?tab=debts"{cur if tab == 'debts' else ''}>Qarzdorlar · {len(debts)}</a></nav>
  <section class="total">{summary}</section>
  {msg_html}
  {items}
</div>""")


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


def event_fieldset(i, ev: dict, staff: list) -> str:
    chosen = {str(x) for x in ev.get("staff", [])}
    chips = "".join(
        f'<label class="chip"><input type="checkbox" name="ev_staff_{i}" value="{s["id"]}"'
        f'{" checked" if str(s["id"]) in chosen else ""}><span>{escape(s["name"])}'
        f'<small>{escape(ROLES[s["role"]].lower())}{"" if s["tg_id"] else " · ulanmagan"}</small></span></label>'
        for s in staff
    ) or '<span class="meta">Botda hali xodim yo\'q — «👥 Xodimlar» bo\'limidan qo\'shing.</span>'
    n = i + 1 if isinstance(i, int) else "__N__"
    return f"""
<fieldset><legend>{n}-tadbir</legend>
  <div class="grid2">
    <label>Tadbir turi<input name="ev_type_{i}" list="types" value="{attr(ev.get('type'))}" placeholder="Nikoh, Bazm..." required></label>
    <label>To'yxona / manzil<input name="ev_address_{i}" value="{attr(ev.get('address'))}" placeholder="Yakkasaroy" required></label>
    <label>Sana<input type="date" name="ev_date_{i}" value="{attr(ev.get('date'))}" required></label>
    <label>Soat<input type="time" name="ev_time_{i}" value="{attr(ev.get('time'))}" required></label>
  </div>
  <div><div class="meta" style="margin-bottom:6px">Kim boradi</div><div class="chips">{chips}</div></div>
  <label>Dekor (qanday bo'lishi kerak)<input name="ev_decor_{i}" value="{attr(ev.get('decor'))}" placeholder="Saraylik max"></label>
  <label>Dekor rasmi (dekoratorga boradi)<input type="file" name="ev_photo_{i}" accept="image/*"></label>
</fieldset>"""


async def form_page(request: web.Request, values: dict | None = None, errors: list | None = None) -> web.Response:
    db: Database = request.app["db"]
    v = values or {}
    staff = [s for s in await db.staff_list() if s["role"] in FIELD_ROLES]
    types = "".join(f'<option value="{attr(t["name"])}">' for t in await db.event_types_list())
    events = v.get("events") or [{}]
    err = ('<div class="msg err">❗️ ' + "<br>".join(escape(e) for e in errors) + '</div>') if errors else ""
    return page("Yangi zakaz", f"""
<div class="wrap">
  <header><div><div class="eyebrow">Elegant Media</div><h1>Yangi zakaz</h1></div>
    <a class="btn" href="/">← Orqaga</a></header>
  {err}
  <form class="card" method="post" action="/new" enctype="multipart/form-data">
    <fieldset><legend>Mijoz</legend><div class="grid2">
      <label>Ism<input name="name" value="{attr(v.get('name'))}" required placeholder="Botir"></label>
      <label>Telefon<input name="phone" value="{attr(v.get('phone'))}" inputmode="tel" required placeholder="91 943 76 76"></label>
    </div></fieldset>
    <fieldset><legend>Xizmat va narx</legend>
      <label>Xizmatlar<input name="services" value="{attr(v.get('services'))}" required placeholder="Video, foto, dekor"></label>
      <div class="grid2">
        <label>Dogovor (umumiy narx)<input name="total" value="{attr(v.get('total'))}" inputmode="numeric" required placeholder="2 500 000"></label>
        <label>Avans<input name="deposit" value="{attr(v.get('deposit'))}" inputmode="numeric" placeholder="1 500 000"></label>
      </div>
    </fieldset>
    <div id="events" style="display:flex;flex-direction:column;gap:12px">
      {"".join(event_fieldset(i, ev, staff) for i, ev in enumerate(events))}
    </div>
    <button type="button" id="add-ev">+ Yana tadbir</button>
    <label>Izoh<textarea name="note" rows="2" placeholder="Dron kerak...">{escape(v.get('note') or '')}</textarea></label>
    <button class="primary" type="submit">Saqlash va xodimlarga yuborish</button>
  </form>
  <datalist id="types">{types}</datalist>
  <template id="ev-tpl">{event_fieldset("__I__", {}, staff)}</template>
</div>{EVENT_JS}""")


async def new_form(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    return await form_page(request)


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
    if not values["services"]:
        errors.append("Xizmatlarni yozing.")
    if not total:
        errors.append("Dogovor summasini yozing. Masalan: 2 500 000")
    if deposit is None or (total and deposit > total):
        errors.append("Avans noto'g'ri yoki dogovordan katta.")
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

    data = {"client_name": values["name"], "client_phone": phone, "deposit": deposit,
            "services": [{"name": values["services"][:100], "price": total}],
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
    "bad": ("err", "Summani tushunmadim. Masalan: -150000 benzin, +2 mln to'y Aliyev, -$50 reklama"),
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


def _cat_chips(kind: str, names: list[str]) -> str:
    return "".join(
        f'<label class="chip"><input type="radio" name="cat_{kind}" value="{attr(n)}"'
        f'{" checked" if i == 0 else ""}><span>{escape(n)}</span></label>'
        for i, n in enumerate(names)
    )


async def cash_page(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    db: Database = request.app["db"]
    q = request.query
    book, period = _book_period(q)
    first, last = period_range(period, today())
    entries = await db.cash_entries(book, first.isoformat(), last.isoformat())
    totals, overall = _totals(entries), _totals(await db.cash_entries(book))
    cats = await _cash_categories(db, book)
    limits = await _limits_state(db, book)

    summary = ""
    for cur in [c for c in CURRENCIES if c == "UZS" or c in overall]:
        t = totals.get(cur, {"kirim": 0, "chiqim": 0})
        o = overall.get(cur, {"kirim": 0, "chiqim": 0})
        summary += (f'<div><div class="eyebrow">{PERIODS[period]} · qoldiq · {CURRENCIES[cur]}</div>'
                    f'<div class="big">{fmt_cur(t["kirim"] - t["chiqim"], cur)}</div></div>'
                    f'<div class="side">Kirim: +{fmt_cur(t["kirim"], cur)}<br>Chiqim: −{fmt_cur(t["chiqim"], cur)}'
                    f'<br>Jami qoldiq: {fmt_cur(o["kirim"] - o["chiqim"], cur)}</div>')

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
    cat_options = "".join(f'<option value="{attr(n)}">' for n in cats["chiqim"])
    cur_options = "".join(f'<option value="{c}">{label}</option>' for c, label in CURRENCIES.items())
    cur = ' aria-current="page"'
    book_tabs = "".join(f'<a href="/cash?book={b}&p={period}"{cur if b == book else ""}>{label}</a>'
                        for b, label in BOOKS.items())
    period_tabs = "".join(f'<a href="/cash?book={book}&p={p}"{cur if p == period else ""}>{label}</a>'
                          for p, label in PERIODS.items())
    span = fmt_date(first.isoformat()) if period == "day" else f"{first:%d.%m} – {last:%d.%m.%Y}"
    biz_note = "Zakaz to&#39;lovlari kirimga o&#39;zi tushadi." if book == "biznes" else ""
    return page("Kirim-chiqim", f"""
<div class="wrap">
  <header><div><div class="eyebrow">Elegant Media</div><h1>Kirim-chiqim</h1></div>
    <a class="btn" href="/">← Zakazlar</a></header>
  <nav class="tabs two">{book_tabs}</nav>
  <nav class="tabs">{period_tabs}</nav>
  <section class="total">{summary}</section>
  {msg_html}
  <form class="inline" method="post" action="/cash/quick">{hidden}
    <input name="text" required autocomplete="off" aria-label="Tezkor yozish"
      placeholder="-150000 benzin  ·  +2 mln to'y Aliyev">
    <button class="primary" type="submit">Yozish</button></form>
  <div class="meta">Boshida <b>−</b> chiqim, <b>+</b> kirim. Dollar: <b>-$50 reklama</b>.
    {biz_note}</div>
  <details class="row"><summary><b>➕ ➖ Tugmalar bilan yozish</b></summary>
  <form class="card cashform" method="post" action="/cash/add">{hidden}
    <div class="chips">
      <label class="chip"><input type="radio" name="kind" value="chiqim" checked><span>➖ Chiqim</span></label>
      <label class="chip"><input type="radio" name="kind" value="kirim"><span>➕ Kirim</span></label></div>
    <div class="grid2">
      <label>Summa<input name="amount" inputmode="numeric" required placeholder="150 000"></label>
      <label>Valyuta<select name="currency">{cur_options}</select></label></div>
    <div class="cats-chiqim"><div class="meta" style="margin-bottom:6px">Kategoriya</div>
      <div class="chips">{_cat_chips("chiqim", cats["chiqim"])}</div></div>
    <div class="cats-kirim"><div class="meta" style="margin-bottom:6px">Kategoriya</div>
      <div class="chips">{_cat_chips("kirim", cats["kirim"])}</div></div>
    <label>Yoki o'zingiz yozing (yangi kategoriya)<input name="cat_custom" maxlength="40"
      placeholder="Masalan: Gaz, Svet, Internet"></label>
    <div class="grid2">
      <label>Sana<input type="date" name="day" value="{today().isoformat()}" required></label>
      <label>Izoh<input name="note" maxlength="200" placeholder="Nexia, 20 litr"></label></div>
    <button class="primary" type="submit">Saqlash</button>
  </form></details>
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
  <h2>{PERIODS[period]}: {span}</h2>
  {ledger}
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


async def cash_quick(request: web.Request) -> web.Response:
    if not _authed(request):
        raise web.HTTPSeeOther("/")
    form = await request.post()
    book, period = _book_period(form)
    e = parse_quick(str(form.get("text", ""))[:300], await _cash_categories(request.app["db"], book))
    if not e:
        raise _cash_back(book, period, m="bad")
    e["category"], e["note"], e["day"] = e["category"][:40], e["note"][:200], today().isoformat()
    await _cash_save(request, book, period, e)


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
        raise _cash_back(book, period, m="bad")
    category = (get("cat_custom") or get(f"cat_{kind}") or ("Boshqa kirim" if kind == "kirim" else "Boshqa"))[:40]
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


# ---------- Kirish ----------

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


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app(bot: Bot, db: Database, bot_username: str) -> web.Application:
    app = web.Application(client_max_size=15 * 1024 * 1024)  # dekor rasmlari uchun
    app["bot"], app["db"], app["bot_username"] = bot, db, bot_username
    app.add_routes([
        web.get("/", index), web.get("/new", new_form), web.post("/new", new_save),
        web.post("/login", login), web.post("/logout", logout), web.post("/pay", pay),
        web.post("/editor", set_editor), web.post("/stage", stage), web.get("/health", health),
        web.get("/cash", cash_page), web.post("/cash/quick", cash_quick), web.post("/cash/add", cash_add),
        web.post("/cash/del", cash_del), web.post("/cash/limit", cash_limit),
    ])
    return app


async def start_web(bot: Bot, db: Database) -> web.AppRunner | None:
    if not WEB_PORT:
        return None
    runner = web.AppRunner(build_app(bot, db, (await bot.me()).username), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    log.info("Sayt ishga tushdi: port %s%s", WEB_PORT, "" if SITE_PIN else " (SITE_PIN yo'q — yopiq)")
    return runner
