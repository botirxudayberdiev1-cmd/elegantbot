"""Xabar matnlari: buyurtma kartasi va operator uchun tadbir kartasi."""

from .utils import escape, fmt_date, fmt_money

STATUS_ICONS = {
    "kutilmoqda": "⏳",
    "qabul": "✅",
    "rad": "❌",
    "keldi": "📍",
    "tugatdi": "🏁",
}
STATUS_NAMES = {
    "kutilmoqda": "javob kutilmoqda",
    "qabul": "qabul qildi",
    "rad": "bora olmaydi",
    "keldi": "yetib keldi",
    "tugatdi": "tugatdi",
}


def order_text(d: dict, title: str) -> str:
    """d — qoralama (FSM) yoki Database.order_full() natijasi; ikkalasi bir xil tuzilishda."""
    lines = [title, ""]
    lines.append(f"👤 <b>{escape(d['client_name'])}</b>, {escape(d['client_phone'])}")

    lines.append("\n<b>Xizmatlar:</b>")
    total = 0
    for s in d["services"]:
        lines.append(f"• {escape(s['name'])} — {fmt_money(s['price'])}")
        total += s["price"]

    for i, ev in enumerate(d["events"], 1):
        lines.append(f"\n<b>{i}. {escape(ev['type_name'])}</b>")
        lines.append(f"📅 {fmt_date(ev['date'])}, ⏰ {ev['time']}")
        lines.append(f"📍 {escape(ev['address'])}" + (" (🗺 lokatsiya bor)" if ev.get("lat") else ""))
        if ev.get("decor_photo") or ev.get("decor_note"):
            photo = "🖼 rasm bor" if ev.get("decor_photo") else ""
            lines.append("🎀 Dekor: " + " · ".join(x for x in (photo, escape(ev.get("decor_note") or "")) if x))
        for op in ev["ops"]:
            icon = STATUS_ICONS.get(op.get("status"), "▫️")
            lines.append(f"   {icon} {escape(op['name'])} — {fmt_money(op['pay'])}")

    paid = d.get("paid", d.get("deposit", 0)) or 0
    lines.append("")
    lines.append(f"💵 Jami: <b>{fmt_money(total)}</b>")
    lines.append(f"✅ To'langan: {fmt_money(paid)}")
    lines.append(f"❗️ Qarz: <b>{fmt_money(total - paid)}</b>")
    if d.get("note"):
        lines.append(f"\n📝 {escape(d['note'])}")
    return "\n".join(lines)


def assignment_text(a, team) -> str:
    """Operatorga yuboriladigan tadbir kartasi. a — Database.assignment_info()."""
    others = [t["name"] for t in team if t["name"] != a["staff_name"]]
    lines = [
        f"🎬 <b>Tadbir: {escape(a['type_name'])}</b>",
        "",
        f"📅 {fmt_date(a['date'])}",
        f"⏰ {a['time']}",
        f"📍 {escape(a['address'])}",
        f"👤 Mijoz: {escape(a['client_name'])}, {escape(a['client_phone'])}",
    ]
    if others:
        lines.append(f"👥 Birga: {escape(', '.join(others))}")
    if a["role"] == "dekorator" and a["decor_note"]:
        lines.append(f"🎀 Qanday dekor: {escape(a['decor_note'])}")
    lines.append(f"💵 Ish haqingiz: <b>{fmt_money(a['pay'])}</b>")
    if a["note"]:
        lines.append(f"📝 {escape(a['note'])}")
    if a["status"] != "kutilmoqda":
        lines.append(f"\n{STATUS_ICONS[a['status']]} Javobingiz: <b>{STATUS_NAMES[a['status']]}</b>")
    return "\n".join(lines)
