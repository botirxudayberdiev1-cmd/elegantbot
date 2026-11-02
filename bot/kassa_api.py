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
from .utils import escape, notify_admins, today

KASSA_DIR = Path(__file__).resolve().parent.parent / "docs" / "kassa"
MAX_AMOUNT = 10 ** 12
MAX_IMPORT = 5000
MAX_QTY = 10 ** 7
UNITS = ("dona", "list", "pachka", "rulon")


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


def _item(r) -> dict:
    return {"id": f"i{r['id']}", "name": r["name"], "unit": r["unit"], "min": r["min_qty"]}


def _move(r) -> dict:
    return {"id": f"m{r['id']}", "itemId": f"i{r['item_id']}", "kind": r["kind"], "qty": r["qty"],
            "note": r["note"] or "", "day": r["day"], "createdAt": r["id"]}


def _num_id(value, prefix: str) -> int | None:
    value = str(value or "")
    return int(value[1:]) if value.startswith(prefix) and value[1:].isdigit() else None


def _qty(value) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n < MAX_QTY else None


async def _low_alert(request: web.Request, item, before: int, after: int) -> None:
    """Ishlatilgandan keyin qoldiq chegaradan pastga tushsa — adminlarga bir marta xabar."""
    if item["min_qty"] and after <= item["min_qty"] < before:
        await notify_admins(request.app["bot"], request.app["db"],
                            f"📦 Omborda kam qoldi: <b>{escape(item['name'])}</b> — {after} {item['unit']}")


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
        return web.json_response({"entries": entries, "limits": limits, "orderCategory": ORDER_CATEGORY,
                                  "items": [_item(r) for r in await db.stock_items()],
                                  "moves": [_move(r) for r in await db.stock_moves()]})

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

    async def stock_item(request: web.Request) -> web.Response:
        guard(request)
        body = await request.json()
        db: Database = request.app["db"]
        name = str(body.get("name") or "").strip()[:40]
        start, min_qty = _qty(body.get("start") or 0), _qty(body.get("min") or 0)
        if not name or start is None or min_qty is None:
            return web.json_response({"error": "Nomi va sonlarni to'g'ri yozing."}, status=400)
        if await db.stock_item_by_name(name):
            return web.json_response({"error": f"«{name}» allaqachon bor."}, status=400)
        unit = body.get("unit") if body.get("unit") in UNITS else "dona"
        item_id = await db.stock_item_add(name, unit, min_qty)
        if start:
            await db.stock_move_add(item_id, "in", start, "Boshlang'ich qoldiq", today().isoformat())
        return web.json_response({"ok": True})

    async def stock_item_del(request: web.Request) -> web.Response:
        guard(request)
        item_id = _num_id((await request.json()).get("id"), "i")
        if item_id is None:
            return web.json_response({"error": "Mahsulot topilmadi."}, status=400)
        await request.app["db"].stock_item_delete(item_id)
        return web.json_response({"ok": True})

    async def stock_move(request: web.Request) -> web.Response:
        guard(request)
        body = await request.json()
        db: Database = request.app["db"]
        item_id = _num_id(body.get("itemId"), "i")
        item = await db.stock_item_get(item_id) if item_id is not None else None
        qty, kind = _qty(body.get("qty")), body.get("kind")
        try:
            day = date.fromisoformat(str(body.get("day") or "")).isoformat()
        except ValueError:
            day = None
        if not item or not qty or kind not in ("in", "out") or not day:
            return web.json_response({"error": "Sonini to'g'ri yozing."}, status=400)
        before = item["left_qty"]
        if kind == "out" and qty > before:
            return web.json_response({"error": f"Omborda faqat {before} {item['unit']} bor."}, status=400)
        note = str(body.get("note") or "").strip()[:200]
        await db.stock_move_add(item["id"], kind, qty, note or None, day)
        price = _qty(body.get("price")) if kind == "in" else None
        if price:  # tovar puli Kassaga Studiya chiqimi bo'lib tushadi
            await db.cash_add("biznes", "chiqim", price, "UZS", item["name"][:40],
                              f"{qty} {item['unit']} keldi" + (f" · {note}" if note else ""), day)
        if kind == "out":
            await _low_alert(request, item, before, before - qty)
        return web.json_response({"ok": True})

    async def stock_move_del(request: web.Request) -> web.Response:
        guard(request)
        move_id = _num_id((await request.json()).get("id"), "m")
        if move_id is None:
            return web.json_response({"error": "Yozuv topilmadi."}, status=400)
        await request.app["db"].stock_move_delete(move_id)
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
        # Ombor: mahsulot nomi bo'yicha birlashtiriladi, harakat ikki marta qo'shilmaydi
        item_ids: dict[str, int] = {}
        for raw in (body.get("items") or [])[:MAX_IMPORT]:
            name = str((raw or {}).get("name") or "").strip()[:40]
            if not name:
                continue
            row = await db.stock_item_by_name(name)
            item_ids[str(raw.get("id"))] = row["id"] if row else await db.stock_item_add(
                name, raw.get("unit") if raw.get("unit") in UNITS else "dona", _qty(raw.get("min")) or 0)
        have_moves = await db.stock_ext_ids()
        for raw in (body.get("moves") or [])[:MAX_IMPORT]:
            raw = raw or {}
            ext, item_id, qty = str(raw.get("id") or "")[:40], item_ids.get(str(raw.get("itemId"))), _qty(raw.get("qty"))
            try:
                day = date.fromisoformat(str(raw.get("day") or "")).isoformat()
            except ValueError:
                continue
            if not ext or ext in have_moves or item_id is None or not qty or raw.get("kind") not in ("in", "out"):
                continue
            await db.stock_move_add(item_id, raw["kind"], qty, str(raw.get("note") or "")[:200] or None, day, ext_id=ext)
            have_moves.add(ext)
            added += 1
        return web.json_response({"added": added})

    async def index(request: web.Request) -> web.Response:
        return web.FileResponse(KASSA_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    async def to_slash(request: web.Request) -> web.Response:
        raise web.HTTPMovedPermanently("/kassa/")

    app.add_routes([
        web.get("/kassa", to_slash), web.get("/kassa/", index),
        web.get("/api/kassa", state), web.post("/api/kassa/add", add), web.post("/api/kassa/del", delete),
        web.post("/api/kassa/limit", limit), web.post("/api/kassa/import", import_local),
        web.post("/api/kassa/stock/item", stock_item), web.post("/api/kassa/stock/item/del", stock_item_del),
        web.post("/api/kassa/stock/move", stock_move), web.post("/api/kassa/stock/move/del", stock_move_del),
        web.static("/kassa", KASSA_DIR),
    ])
