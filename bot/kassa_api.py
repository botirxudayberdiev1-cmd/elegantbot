"""Elegant Kassa ilovasi (/kassa/) uchun JSON API — yozuvlar bot bazasida saqlanadi.

Ilova bot bilan bir manzildan ochilsa shu API'ga ulanadi; zakaz to'lovlari Studiya kirimida o'zi ko'rinadi.
Kirish — admin sayt bilan bir xil PIN (cookie). Oylik limit oshsa, adminlarga Telegram'da xabar boradi.
"""

from datetime import date
from pathlib import Path
from typing import Callable

from aiohttp import web

from .cash import BOOKS, DEFAULT_CATEGORY, fmt_cur, month_range
from .config import ORDER_CATEGORY
from .db import Database
from .utils import escape, notify_admins

KASSA_DIR = Path(__file__).resolve().parent.parent / "docs" / "kassa"
MAX_AMOUNT = 10 ** 12
MAX_IMPORT = 5000


def _entry(book: str, e: dict) -> dict:
    # 'c12' — qo'lda yozilgan (o'chirsa bo'ladi), 'o5' — zakaz to'lovi (faqat zakaz qismida)
    return {"id": ("c" if e["src"] == "cash" else "o") + str(e["id"]), "src": e["src"], "book": book,
            "kind": e["kind"], "amount": e["amount"], "currency": e["currency"], "category": e["category"],
            "note": e["note"] or "", "day": e["day"]}


def _clean(body: dict) -> dict | None:
    """Kelgan yozuvni tekshiradi; noto'g'ri bo'lsa None."""
    try:
        amount = int(body.get("amount") or 0)
        day = date.fromisoformat(str(body.get("day") or "")).isoformat()
    except (TypeError, ValueError):
        return None
    book, kind = body.get("book"), body.get("kind")
    if book not in BOOKS or kind not in ("kirim", "chiqim") or not 0 < amount < MAX_AMOUNT:
        return None
    category = str(body.get("category") or "").strip()[:40] or DEFAULT_CATEGORY[kind]
    if category == ORDER_CATEGORY:  # zakaz to'lovlari faqat zakaz qismidan yoziladi
        category = DEFAULT_CATEGORY[kind]
    return {"book": book, "kind": kind, "amount": amount, "currency": "USD" if body.get("currency") == "USD" else "UZS",
            "category": category, "note": str(body.get("note") or "").strip()[:200], "day": day}


async def _limit_alert(request: web.Request, e: dict) -> str:
    """Shu chiqim oylik limitdan oshirgan bo'lsa — adminlarga xabar; ilovaga ogohlantirish matni."""
    db: Database = request.app["db"]
    lim = await db.cash_limit_get(e["book"], e["category"], e["currency"])
    if e["kind"] != "chiqim" or not lim:
        return ""
    first, last = (d.isoformat() for d in month_range(date.fromisoformat(e["day"])))
    spent = await db.cash_spent(e["book"], e["category"], e["currency"], first, last)
    if spent <= lim["amount"]:
        return ""
    text = f'{e["category"]}: bu oy {fmt_cur(spent, e["currency"])}, limit {fmt_cur(lim["amount"], e["currency"])}'
    if spent - e["amount"] <= lim["amount"]:  # aynan shu yozuv limitdan oshirdi
        await notify_admins(request.app["bot"], db, f"⚠️ Oylik limit oshdi ({BOOKS[e['book']]}): <b>{escape(text)}</b>")
    return text


def add_kassa_routes(app: web.Application, authed: Callable[[web.Request], bool]) -> None:
    def guard(request: web.Request) -> None:
        if not authed(request):
            raise web.HTTPUnauthorized(text='{"error":"pin"}', content_type="application/json")

    async def state(request: web.Request) -> web.Response:
        guard(request)
        db: Database = request.app["db"]
        entries = [_entry(book, e) for book in BOOKS for e in await db.cash_entries(book)]
        limits = {f'{r["book"]}--{r["currency"]}--{r["category"].lower()}': dict(r)
                  for book in BOOKS for r in await db.cash_limits(book)}
        for v in limits.values():
            v.pop("id", None)
        return web.json_response({"entries": entries, "limits": limits, "orderCategory": ORDER_CATEGORY})

    async def add(request: web.Request) -> web.Response:
        guard(request)
        e = _clean(await request.json())
        if not e:
            return web.json_response({"error": "Summa yoki sana noto'g'ri."}, status=400)
        db: Database = request.app["db"]
        new_id = await db.cash_add(e["book"], e["kind"], e["amount"], e["currency"], e["category"],
                                   e["note"] or None, e["day"])
        return web.json_response({"id": f"c{new_id}", "src": "cash", **e, "warn": await _limit_alert(request, e)})

    async def delete(request: web.Request) -> web.Response:
        guard(request)
        entry_id = str((await request.json()).get("id", ""))
        if not entry_id.startswith("c") or not entry_id[1:].isdigit():
            return web.json_response({"error": "Zakaz to'lovini zakazlar bo'limidan o'zgartiring."}, status=400)
        await request.app["db"].cash_delete(int(entry_id[1:]))
        return web.json_response({"ok": True})

    async def limit(request: web.Request) -> web.Response:
        guard(request)
        body = await request.json()
        category = str(body.get("category") or "").strip()[:40]
        try:
            amount = int(body.get("amount"))
        except (TypeError, ValueError):
            amount = -1
        if body.get("book") not in BOOKS or not category or category == ORDER_CATEGORY or not 0 <= amount < MAX_AMOUNT:
            return web.json_response({"error": "Kategoriya va summani yozing."}, status=400)
        currency = "USD" if body.get("currency") == "USD" else "UZS"
        await request.app["db"].cash_limit_set(body["book"], category, currency, amount)
        return web.json_response({"ok": True})

    async def import_local(request: web.Request) -> web.Response:
        """Telefonda (eski ilovada) yozilganlarni bazaga ko'chirish; bir yozuv ikki marta qo'shilmaydi."""
        guard(request)
        body = await request.json()
        db: Database = request.app["db"]
        have = await db.cash_ext_ids()
        added = 0
        for raw in (body.get("entries") or [])[:MAX_IMPORT]:
            ext = str((raw or {}).get("id") or "")[:40]
            e = _clean(raw or {})
            if not ext or ext in have or not e:
                continue
            await db.cash_add(e["book"], e["kind"], e["amount"], e["currency"], e["category"],
                              e["note"] or None, e["day"], ext_id=ext)
            have.add(ext)
            added += 1
        for lim in (body.get("limits") or {}).values():
            try:
                if lim["book"] in BOOKS and lim["category"] and int(lim["amount"]) > 0:
                    await db.cash_limit_set(lim["book"], str(lim["category"])[:40],
                                            "USD" if lim.get("currency") == "USD" else "UZS", int(lim["amount"]))
            except (KeyError, TypeError, ValueError):
                continue
        return web.json_response({"added": added})

    async def index(request: web.Request) -> web.Response:
        return web.FileResponse(KASSA_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    async def to_slash(request: web.Request) -> web.Response:
        raise web.HTTPMovedPermanently("/kassa/")

    app.add_routes([
        web.get("/kassa", to_slash), web.get("/kassa/", index),
        web.get("/api/kassa", state), web.post("/api/kassa/add", add), web.post("/api/kassa/del", delete),
        web.post("/api/kassa/limit", limit), web.post("/api/kassa/import", import_local),
        web.static("/kassa", KASSA_DIR),
    ])
