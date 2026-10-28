"""Buyurtmani bitta xabardan (shablondan) o'qish.

Natija — orders.py dagi qoralama bilan bir xil tuzilish, shuning uchun tekshirish
va saqlash (show_confirm, save) o'zgarishsiz ishlaydi.
"""

import re
from datetime import date

from .config import FIELD_ROLES
from .utils import fmt_money, normalize_phone, parse_date, parse_money, parse_time, today

TEMPLATE = """Ism:
Telefon:
Xizmatlar:
Dogovor:
Tadbir:
Sana:
Soat:
Manzil:
Xodimlar:
Dekor:
Avans:
Izoh:"""

EXAMPLE = """Ism: BOTIR
Telefon: 919437676
Xizmatlar: VIDEO FOTO DECOR
Dogovor: 2500000
Tadbir: NIKOH BAZM
Sana: 12.11.2026
Soat: 18:00
Manzil: YAKKASAROY
Xodimlar: ORIF USMON
Dekor: SARAYLIK MAX
Avans: 1500000
Izoh:"""

# Qator boshidagi so'z -> maydon. Bir nechta yozilishi ham qabul qilinadi.
KEYS = {
    "ism": "name", "mijoz": "name",
    "telefon": "phone", "tel": "phone", "raqam": "phone", "raqami": "phone",
    "xizmat": "services", "xizmatlar": "services",
    "tadbir": "event", "tadbir turi": "event",
    "sana": "date",
    "soat": "time", "vaqt": "time", "vaqti": "time",
    "manzil": "address", "to'yxona": "address", "manzili": "address",
    "xodim": "staff", "xodimlar": "staff", "kim boradi": "staff",
    "dekor": "decor", "dekoratsiya": "decor",
    "avans": "deposit", "zakalat": "deposit",
    "dogovor": "total", "docovor": "total", "shartnoma": "total", "jami": "total",
    "narx": "total", "umumiy narx": "total",
    "izoh": "note",
}
EVENT_FIELDS = {"date", "time", "address", "staff", "decor"}

_APOSTROPHES = str.maketrans({c: "'" for c in "’‘`ʻʼ"})
_ITEM = re.compile(
    r"^(?P<name>.*?[^\d\s.,\-—:])\s*[-—:]?\s*"
    r"(?P<amount>\d[\d\s.,]*\s*(?:mln|million|ming|k|m)?)\s*(?:so'm|som|sum)?\.?$",
    re.IGNORECASE,
)


def norm(text: str) -> str:
    return " ".join(text.translate(_APOSTROPHES).lower().split())


def split_items(text: str) -> list[str]:
    """'Video 5,5 mln, Foto 2 mln; Albom 1 mln' -> 3 ta. '5,5' dagi vergul bo'linmaydi."""
    parts = re.split(r"[;\n]|,\s*(?=[^\d\s])", text)
    return [p.strip() for p in parts if p.strip()]


def parse_item(text: str) -> tuple[str, int | None]:
    """'Video 5 mln' -> ('Video', 5000000); narx yo'q bo'lsa -> ('Video', None)."""
    m = _ITEM.match(text.strip())
    if not m:
        return text.strip(), None
    return m["name"].strip(), parse_money(m["amount"])


def match_staff(query: str, staff) -> list:
    q = norm(query)
    exact = [s for s in staff if norm(s["name"]) == q]
    if exact:
        return exact
    return [s for s in staff if any(w.startswith(q) for w in [norm(s["name"])] + norm(s["name"]).split())]


def staff_entries(text: str, staff) -> list[tuple[str, int | None]]:
    """'Orif 300 ming, Dilnoza' -> vergul bilan. 'ORIF USMON' (vergulsiz, summasiz) -> so'zma-so'z,
    'Orif Rahmatov' kabi to'liq ism bo'lsa — bitta odam."""
    items = split_items(text)
    if len(items) != 1 or re.search(r"\d", items[0]):
        return [parse_item(x) for x in items]
    words = items[0].split()
    full = {norm(s["name"]) for s in staff}
    out, i = [], 0
    while i < len(words):
        for n in (3, 2, 1):  # avval to'liq ism (2–3 so'z), keyin bitta so'z
            chunk = " ".join(words[i:i + n])
            if n == 1 or norm(chunk) in full:
                out.append((chunk, None))
                i += n
                break
    return out


def parse_order(text: str, event_types, staff, photo_id: str | None = None) -> tuple[dict, list[str]]:
    """(qoralama, xatolar). Xato bo'lsa, qoralama to'liq bo'lmasligi mumkin.
    Ogohlantirishlar (to'xtatmaydigan) qoralamaning "warnings" kalitida."""
    errors: list[str] = []
    warnings: list[str] = []
    fields: dict[str, str] = {}
    events: list[dict] = []
    last = None  # davomi keyingi qatorga o'tgan izoh/dekor uchun

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^([^:]{1,20}):\s*(.*)$", line)
        key = KEYS.get(norm(m[1])) if m else None
        if not key:
            m = re.match(r"^(\S+)\s+(.+)$", line)
            key = KEYS.get(norm(m[1])) if m else None
        if not key:
            if last in ("note", "decor"):
                target = events[-1] if last == "decor" else fields
                target[last] = (target.get(last, "") + " " + line).strip()
                continue
            errors.append(f"Bu qatorni tushunmadim: «{line[:40]}»")
            continue
        value = m[2].strip()
        last = key
        if key == "event":
            events.append({"event": value})
        elif key in EVENT_FIELDS:
            if not events:
                events.append({})
            events[-1][key] = value
        else:
            fields[key] = value

    types = {norm(t["name"]): t for t in event_types}
    field_staff = [s for s in staff if s["role"] in FIELD_ROLES]

    # --- Mijoz ---
    name = fields.get("name", "")
    if not 2 <= len(name) <= 64:
        errors.append("Ism: mijozning ismini yozing (2–64 belgi).")
    phone = normalize_phone(fields.get("phone", ""))
    if not phone:
        errors.append("Telefon: raqam noto'g'ri yoki yozilmagan. Masalan: 90 123 45 67")

    # --- Xizmatlar ---
    contract = None
    if fields.get("total"):
        contract = parse_money(fields["total"])
        if contract is None:
            errors.append("Dogovor: summani tushunmadim. Masalan: 2 500 000 yoki 2,5 mln")
    items = [parse_item(x) for x in split_items(fields.get("services", ""))]
    services = []
    if contract is not None and all(price is None for _, price in items):
        # Xizmatlar narxsiz, umumiy narx Dogovor qatorida — bitta xizmat qilib saqlanadi
        names = ", ".join(n for n, _ in items) or "Xizmatlar"
        services.append({"name": names[:100], "price": contract})
    else:
        for svc, price in items:
            if price is None:
                errors.append(
                    f"Xizmatlar: «{svc}» narxini yozing (Video 5 mln) yoki umumiy narxni "
                    "«Dogovor:» qatoriga yozing."
                )
            else:
                services.append({"name": svc[:100], "price": price})
        if contract is not None and services and sum(s["price"] for s in services) != contract:
            errors.append(
                f"Xizmatlar narxlari yig'indisi ({fmt_money(sum(s['price'] for s in services))}) "
                f"Dogovorga ({fmt_money(contract)}) teng emas."
            )
    if not services and not any(e.startswith(("Xizmatlar", "Dogovor")) for e in errors):
        errors.append("Xizmatlar: xizmatlarni va Dogovor (umumiy narx) ni yozing.")
    total = sum(s["price"] for s in services)

    # --- Tadbirlar ---
    if not events:
        errors.append("Tadbir: tadbir turi, sana, soat va manzilni yozing.")
    out_events = []
    for i, ev in enumerate(events, 1):
        p = f"{i}-tadbir" if len(events) > 1 else "Tadbir"
        t = types.get(norm(ev.get("event", "")))
        new_type = None
        words = norm(ev.get("event", "")).split()
        if not t and len(words) > 1 and all(w in types for w in words):
            # "NIKOH BAZM" — mavjud turlardan tuzilgan qo'shma tur; saqlashda yangi tur sifatida qo'shiladi
            new_type = " ".join(types[w]["name"] for w in words)
        elif not t:
            names = ", ".join(x["name"] for x in event_types)
            errors.append(
                f"{p}: «{ev.get('event', '')}» — turini bittasini yozing ({names}). "
                "Ikkita tadbir bo'lsa, ikkinchisini alohida «Tadbir:» qatoridan boshlang."
            )
        d = parse_date(ev.get("date", ""))
        if not d:
            errors.append(f"{p}: sanani tushunmadim. Masalan: 15.11 yoki 15.11.2026")
        elif d < today():
            errors.append(f"{p}: {d:%d.%m.%Y} sanasi o'tib ketgan.")
        tm = parse_time(ev.get("time", ""))
        if not tm:
            errors.append(f"{p}: soatni tushunmadim. Masalan: 18:00")
        address = ev.get("address", "")
        if len(address) < 2:
            errors.append(f"{p}: manzilni yozing (to'yxona nomi).")

        ops = []
        known = ", ".join(s["name"] for s in field_staff) or "hali hech kim yo'q"
        for who, pay in staff_entries(ev.get("staff", ""), field_staff):
            found = match_staff(who, field_staff)
            if not found:
                warnings.append(f"{p}: «{who}» botda yo'q — zakazga qo'shilmadi. Bor xodimlar: {known}")
                continue
            if len(found) > 1:
                errors.append(f"{p}: «{who}» bir nechta odamga to'g'ri keladi, to'liq yozing. Xodimlar: {known}")
                continue
            s = found[0]
            if any(o["id"] == s["id"] for o in ops):
                warnings.append(f"{p}: {s['name']} ikki marta yozilgan — bir marta qo'shildi.")
                continue
            ops.append({"id": s["id"], "name": s["name"], "role": s["role"], "pay": pay or 0})

        out_events.append({
            "type_id": t["id"] if t else None,
            "type_name": t["name"] if t else new_type or "",
            "new_type": new_type,
            "date": d.isoformat() if isinstance(d, date) else None,
            "time": tm,
            "address": address[:200],
            "lat": None,
            "lon": None,
            "decor_photo": photo_id,
            "decor_note": (ev.get("decor") or "")[:500] or None,
            "ops": ops,
        })

    # Dekor rasmi dekoratori bor tadbir(lar)ga; hech birida dekorator bo'lmasa — hammasiga qoladi
    with_dekor = [e for e in out_events if any(o["role"] == "dekorator" for o in e["ops"])]
    if photo_id and with_dekor:
        for e in out_events:
            if e not in with_dekor:
                e["decor_photo"] = None

    # --- Avans va izoh ---
    deposit = 0
    if fields.get("deposit"):
        deposit = parse_money(fields["deposit"])
        if deposit is None:
            errors.append("Avans: summani tushunmadim. Masalan: 1 mln yoki 500 ming")
            deposit = 0
        elif services and deposit > total:
            errors.append(f"Avans jami summadan ({fmt_money(total)}) ko'p bo'lishi mumkin emas.")

    data = {
        "client_name": name,
        "client_phone": phone,
        "services": services,
        "events": out_events,
        "deposit": deposit,
        "note": (fields.get("note") or "")[:500] or None,
        "warnings": warnings,
    }
    return data, errors
