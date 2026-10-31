import os
import re
import secrets

import aiosqlite

from .config import ADMIN_IDS, DEFAULT_EVENT_TYPES, FIELD_ROLES, ORDER_CATEGORY, ROLES

EVENT_NEW_COLUMNS = {"lat": "REAL", "lon": "REAL", "decor_photo": "TEXT", "decor_note": "TEXT"}

ROLE_CHECK = "CHECK (role IN (" + ", ".join(f"'{r}'" for r in ROLES) + "))"

# Jadvallar IF NOT EXISTS bilan yaratiladi: eski bazaga yangilari o'zi qo'shiladi, ma'lumotlar saqlanadi.
SCHEMA = """
-- 1. Xodimlar
CREATE TABLE IF NOT EXISTS staff (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL """ + ROLE_CHECK + """,
    phone        TEXT,
    tg_id        INTEGER UNIQUE,
    invite_token TEXT NOT NULL UNIQUE,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 2. Tadbir turlari
CREATE TABLE IF NOT EXISTS event_types (
    id     INTEGER PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    active INTEGER NOT NULL DEFAULT 1
);

-- 3. Buyurtmalar
CREATE TABLE IF NOT EXISTS orders (
    id                INTEGER PRIMARY KEY,
    client_name       TEXT NOT NULL,
    client_phone      TEXT,
    client_tg_id      INTEGER,
    client_token      TEXT NOT NULL UNIQUE,
    note              TEXT,
    editor_id         INTEGER REFERENCES staff(id),  -- montajchi
    editing_taken_at  TEXT,                          -- montajchi olgan sana
    editing_done_at   TEXT,                          -- montajchi topshirgan sana
    ready_notified_at TEXT,                          -- mijozga "to'y tayyor" yuborilgan
    delivered_at      TEXT,                          -- mijozga topshirilgan
    created_by        INTEGER,                       -- admin Telegram ID
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 4. Xizmatlar (buyurtma ichida)
CREATE TABLE IF NOT EXISTS services (
    id       INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    name     TEXT NOT NULL,
    price    INTEGER NOT NULL DEFAULT 0
);

-- 5. Tadbirlar (buyurtmaning har bir tadbiri)
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    event_type_id INTEGER NOT NULL REFERENCES event_types(id),
    date          TEXT NOT NULL,  -- YYYY-MM-DD
    time          TEXT,           -- HH:MM
    address       TEXT,
    lat           REAL,           -- Telegram lokatsiyasi
    lon           REAL,
    decor_photo   TEXT,           -- dekor rasmi (Telegram file_id)
    decor_note    TEXT            -- qanday dekor qo'yish kerak
);

-- 6. Biriktirishlar (tadbirga operator)
CREATE TABLE IF NOT EXISTS assignments (
    id               INTEGER PRIMARY KEY,
    event_id         INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    staff_id         INTEGER NOT NULL REFERENCES staff(id),
    pay              INTEGER NOT NULL DEFAULT 0,  -- ish haqi
    status           TEXT NOT NULL DEFAULT 'kutilmoqda'
                     CHECK (status IN ('kutilmoqda', 'qabul', 'rad', 'keldi', 'tugatdi')),
    responded_at     TEXT,
    arrived_at       TEXT,
    finished_at      TEXT,
    flash_cleared_at TEXT,
    UNIQUE (event_id, staff_id)
);

-- 7. To'lovlar
CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    amount      INTEGER NOT NULL,
    paid_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    received_by INTEGER REFERENCES staff(id),  -- kim oldi
    note        TEXT
);

-- 8. Eslatmalar (bir xil eslatma ikki marta ketmasligi uchun)
CREATE TABLE IF NOT EXISTS reminders (
    id      INTEGER PRIMARY KEY,
    kind    TEXT NOT NULL,     -- masalan: 'kun_oldin', 'soat_oldin', 'fleshka'
    ref_id  INTEGER NOT NULL,  -- tadbir yoki biriktirish ID
    sent_on TEXT NOT NULL,     -- YYYY-MM-DD
    sent_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (kind, ref_id, sent_on)
);

-- Yarim yozilgan jarayonlar (bot qayta ishga tushsa ham saqlanadi)
CREATE TABLE IF NOT EXISTS fsm (
    key   TEXT PRIMARY KEY,
    state TEXT,
    data  TEXT
);

-- Ochiq saytdan kelgan so'rovlar (tanlangan dekor/taklifnoma/albom yoki paketli buyurtma)
CREATE TABLE IF NOT EXISTS site_requests (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,                  -- 'tanlov' yoki 'buyurtma'
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL,
    data       TEXT NOT NULL,                  -- JSON: tanlovlar, paket, tadbirlar, izoh
    status     TEXT NOT NULL DEFAULT 'yangi',  -- 'yangi' yoki 'qabul'
    taken_by   TEXT,
    taken_at   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 9. Kirim-chiqim (qo'lda yoziladi; zakaz to'lovlari payments'dan o'zi qo'shiladi)
CREATE TABLE IF NOT EXISTS cash (
    id         INTEGER PRIMARY KEY,
    book       TEXT NOT NULL CHECK (book IN ('biznes', 'shaxsiy')),
    kind       TEXT NOT NULL CHECK (kind IN ('kirim', 'chiqim')),
    amount     INTEGER NOT NULL CHECK (amount > 0),
    currency   TEXT NOT NULL DEFAULT 'UZS' CHECK (currency IN ('UZS', 'USD')),
    category   TEXT NOT NULL,
    note       TEXT,
    day        TEXT NOT NULL,  -- YYYY-MM-DD
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 10. Oylik limitlar (chiqim kategoriyasi bo'yicha)
CREATE TABLE IF NOT EXISTS cash_limits (
    id       INTEGER PRIMARY KEY,
    book     TEXT NOT NULL,
    category TEXT NOT NULL COLLATE NOCASE,
    currency TEXT NOT NULL,
    amount   INTEGER NOT NULL,
    UNIQUE (book, category, currency)
);

CREATE INDEX IF NOT EXISTS idx_cash_day ON cash(book, day);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE INDEX IF NOT EXISTS idx_assignments_staff ON assignments(staff_id);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
"""


def new_token() -> str:
    return secrets.token_urlsafe(9)


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        if os.path.exists(self.path + ".restore"):  # /restore orqali yuborilgan baza
            os.replace(self.path + ".restore", self.path)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self._migrate_staff_roles()
        await self._add_missing_columns("events", EVENT_NEW_COLUMNS)
        await self._add_missing_columns("cash", {"ext_id": "TEXT"})  # Kassa ilovasidan ko'chirilgan yozuv ID
        await self.conn.execute("PRAGMA foreign_keys = ON")
        async with self.conn.execute("SELECT COUNT(*) FROM event_types") as cur:
            (count,) = await cur.fetchone()
        if count == 0:
            await self.conn.executemany(
                "INSERT INTO event_types (name) VALUES (?)", [(n,) for n in DEFAULT_EVENT_TYPES]
            )
        await self.conn.commit()

    async def _add_missing_columns(self, table: str, columns: dict[str, str]) -> None:
        """Eski bazaga keyin qo'shilgan ustunlarni qo'shadi (ma'lumotlar saqlanadi)."""
        have = {r["name"] for r in await self._all(f"PRAGMA table_info({table})")}
        for name, sql_type in columns.items():
            if name not in have:
                await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
        await self.conn.commit()

    async def _migrate_staff_roles(self) -> None:
        """Eski bazada staff jadvalidagi lavozimlar ro'yxati (CHECK) yangilanadi.

        SQLite CHECK'ni o'zgartira olmaydi, shuning uchun jadval yangidan quriladi.
        Ma'lumotlar va ID'lar saqlanadi. foreign_keys o'chiq paytda chaqiriladi.
        """
        row = await self._one("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'staff'")
        if ROLE_CHECK in row["sql"]:
            return
        new_sql = re.sub(r"CHECK \(role IN \([^)]*\)\)", ROLE_CHECK, row["sql"], count=1)
        new_sql = new_sql.replace("CREATE TABLE staff", "CREATE TABLE staff_new", 1)
        await self.conn.executescript(
            "BEGIN;"
            + new_sql + ";"
            "INSERT INTO staff_new SELECT * FROM staff;"
            "DROP TABLE staff;"
            "ALTER TABLE staff_new RENAME TO staff;"
            "COMMIT;"
        )

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def _one(self, sql: str, params: tuple = ()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, params: tuple = ()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    # ---------- Xodimlar ----------

    async def staff_add(self, name: str, role: str, phone: str | None) -> int:
        cur = await self.conn.execute(
            "INSERT INTO staff (name, role, phone, invite_token) VALUES (?, ?, ?, ?)",
            (name, role, phone, new_token()),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def staff_list(self):
        return await self._all(
            "SELECT * FROM staff WHERE active = 1 "
            "ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'operator' THEN 1 ELSE 2 END, name"
        )

    async def staff_get(self, staff_id: int):
        return await self._one("SELECT * FROM staff WHERE id = ? AND active = 1", (staff_id,))

    async def staff_by_token(self, token: str):
        return await self._one(
            "SELECT * FROM staff WHERE invite_token = ? AND active = 1", (token,)
        )

    async def staff_by_tg(self, tg_id: int):
        return await self._one("SELECT * FROM staff WHERE tg_id = ? AND active = 1", (tg_id,))

    async def staff_link(self, staff_id: int, tg_id: int) -> None:
        await self.conn.execute("UPDATE staff SET tg_id = ? WHERE id = ?", (tg_id, staff_id))
        await self.conn.commit()

    async def staff_new_token(self, staff_id: int) -> None:
        """Yangi havola: eskisi ishlamay qoladi va xodim Telegramdan uziladi."""
        await self.conn.execute(
            "UPDATE staff SET invite_token = ?, tg_id = NULL WHERE id = ?",
            (new_token(), staff_id),
        )
        await self.conn.commit()

    async def staff_deactivate(self, staff_id: int) -> None:
        # Eski buyurtmalardagi yozuvlar saqlanib qolishi uchun o'chirmaymiz, faqat yashiramiz.
        await self.conn.execute(
            "UPDATE staff SET active = 0, tg_id = NULL WHERE id = ?", (staff_id,)
        )
        await self.conn.commit()

    async def admin_tg_ids(self) -> set[int]:
        rows = await self._all(
            "SELECT tg_id FROM staff WHERE role = 'admin' AND active = 1 AND tg_id IS NOT NULL"
        )
        return ADMIN_IDS | {r["tg_id"] for r in rows}

    async def is_admin(self, tg_id: int) -> bool:
        return tg_id in await self.admin_tg_ids()

    # ---------- Tadbir turlari ----------

    async def event_types_list(self):
        return await self._all("SELECT * FROM event_types WHERE active = 1 ORDER BY id")

    async def event_type_get(self, type_id: int):
        return await self._one(
            "SELECT * FROM event_types WHERE id = ? AND active = 1", (type_id,)
        )

    async def event_type_add(self, name: str) -> bool:
        """False qaytaradi, agar shu nomli tur allaqachon bo'lsa."""
        row = await self._one("SELECT * FROM event_types WHERE name = ?", (name,))
        if row and row["active"]:
            return False
        if row:
            await self.conn.execute("UPDATE event_types SET active = 1 WHERE id = ?", (row["id"],))
        else:
            await self.conn.execute("INSERT INTO event_types (name) VALUES (?)", (name,))
        await self.conn.commit()
        return True

    async def event_type_deactivate(self, type_id: int) -> None:
        await self.conn.execute("UPDATE event_types SET active = 0 WHERE id = ?", (type_id,))
        await self.conn.commit()

    # ---------- Buyurtmalar ----------

    async def operators_list(self):
        """Tadbirga boradigan xodimlar: operatorlar, fotograflar, dekoratorlar."""
        marks = ", ".join("?" * len(FIELD_ROLES))
        order = " ".join(f"WHEN '{r}' THEN {i}" for i, r in enumerate(FIELD_ROLES))
        return await self._all(
            f"SELECT * FROM staff WHERE active = 1 AND role IN ({marks}) "
            f"ORDER BY CASE role {order} END, name",
            FIELD_ROLES,
        )

    async def staff_busy_on(self, day: str) -> dict[int, list[str]]:
        """Shu kuni qaysi operator qaysi soatda band: {staff_id: ['18:00', ...]}."""
        rows = await self._all(
            "SELECT a.staff_id, e.time FROM assignments a JOIN events e ON e.id = a.event_id "
            "WHERE e.date = ? AND a.status != 'rad'",
            (day,),
        )
        busy: dict[int, list[str]] = {}
        for r in rows:
            busy.setdefault(r["staff_id"], []).append(r["time"] or "?")
        return busy

    async def order_create(self, d: dict, created_by: int) -> tuple[int, list[int]]:
        """Qoralamani bitta tranzaksiyada saqlaydi. (buyurtma_id, [biriktirish_id...]) qaytaradi."""
        asg_ids: list[int] = []
        try:
            cur = await self.conn.execute(
                "INSERT INTO orders (client_name, client_phone, client_token, note, created_by) "
                "VALUES (?, ?, ?, ?, ?)",
                (d["client_name"], d["client_phone"], new_token(), d.get("note"), created_by),
            )
            order_id = cur.lastrowid
            await self.conn.executemany(
                "INSERT INTO services (order_id, name, price) VALUES (?, ?, ?)",
                [(order_id, s["name"], s["price"]) for s in d["services"]],
            )
            for ev in d["events"]:
                cur = await self.conn.execute(
                    "INSERT INTO events (order_id, event_type_id, date, time, address, "
                    "  lat, lon, decor_photo, decor_note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (order_id, ev["type_id"], ev["date"], ev["time"], ev["address"],
                     ev.get("lat"), ev.get("lon"), ev.get("decor_photo"), ev.get("decor_note")),
                )
                event_id = cur.lastrowid
                for op in ev["ops"]:
                    cur = await self.conn.execute(
                        "INSERT INTO assignments (event_id, staff_id, pay) VALUES (?, ?, ?)",
                        (event_id, op["id"], op["pay"]),
                    )
                    asg_ids.append(cur.lastrowid)
            if d.get("deposit"):
                await self.conn.execute(
                    "INSERT INTO payments (order_id, amount, note) VALUES (?, ?, 'Zakalat')",
                    (order_id, d["deposit"]),
                )
            await self.conn.commit()
        except Exception:
            await self.conn.rollback()
            raise
        return order_id, asg_ids

    async def order_full(self, order_id: int) -> dict | None:
        """Buyurtma barcha ma'lumotlari bilan — cards.order_text() uchun."""
        order = await self._one("SELECT * FROM orders WHERE id = ?", (order_id,))
        if not order:
            return None
        services = await self._all(
            "SELECT name, price FROM services WHERE order_id = ? ORDER BY id", (order_id,)
        )
        events = await self._all(
            "SELECT e.*, t.name AS type_name FROM events e "
            "JOIN event_types t ON t.id = e.event_type_id "
            "WHERE e.order_id = ? ORDER BY e.date, e.time",
            (order_id,),
        )
        ev_list = []
        for e in events:
            ops = await self._all(
                "SELECT s.id, s.name, a.pay, a.status FROM assignments a "
                "JOIN staff s ON s.id = a.staff_id WHERE a.event_id = ? ORDER BY a.id",
                (e["id"],),
            )
            ev_list.append({**dict(e), "ops": [dict(o) for o in ops]})
        (paid,) = await self._one(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE order_id = ?", (order_id,)
        )
        return {
            **dict(order),
            "services": [dict(s) for s in services],
            "events": ev_list,
            "paid": paid,
        }

    async def orders_recent(self, limit: int = 15):
        return await self._all(
            "SELECT o.id, o.client_name, "
            "  (SELECT MIN(date) FROM events WHERE order_id = o.id) AS first_date, "
            "  (SELECT COALESCE(SUM(price), 0) FROM services WHERE order_id = o.id) AS total, "
            "  (SELECT COALESCE(SUM(amount), 0) FROM payments WHERE order_id = o.id) AS paid "
            "FROM orders o ORDER BY o.id DESC LIMIT ?",
            (limit,),
        )

    # ---------- Biriktirishlar ----------

    async def assignment_info(self, asg_id: int):
        return await self._one(
            "SELECT a.*, s.name AS staff_name, s.role, s.tg_id AS staff_tg_id, "
            "  e.date, e.time, e.address, e.order_id, e.lat, e.lon, e.decor_photo, e.decor_note, "
            "  t.name AS type_name, "
            "  o.client_name, o.client_phone, o.note "
            "FROM assignments a "
            "JOIN staff s ON s.id = a.staff_id "
            "JOIN events e ON e.id = a.event_id "
            "JOIN event_types t ON t.id = e.event_type_id "
            "JOIN orders o ON o.id = e.order_id "
            "WHERE a.id = ?",
            (asg_id,),
        )

    async def event_team(self, event_id: int):
        return await self._all(
            "SELECT s.name, a.status FROM assignments a JOIN staff s ON s.id = a.staff_id "
            "WHERE a.event_id = ? ORDER BY a.id",
            (event_id,),
        )

    # ---------- Sayt ----------

    async def orders_overview(self) -> list[dict]:
        """Sayt uchun: har buyurtma — jami, to'langan, xizmatlar, tadbirlar (jamoasi bilan), to'lovlar."""
        orders = await self._all(
            "SELECT o.id, o.client_name, o.client_phone, o.note, o.created_at, o.client_tg_id, "
            "  o.client_token, o.editor_id, o.editing_taken_at, o.editing_done_at, "
            "  o.ready_notified_at, o.delivered_at, ed.name AS editor_name, "
            "  (SELECT COALESCE(SUM(price), 0) FROM services WHERE order_id = o.id) AS total, "
            "  (SELECT COALESCE(SUM(amount), 0) FROM payments WHERE order_id = o.id) AS paid, "
            "  (SELECT GROUP_CONCAT(name, ', ') FROM services WHERE order_id = o.id) AS services "
            "FROM orders o LEFT JOIN staff ed ON ed.id = o.editor_id ORDER BY o.id DESC"
        )
        events = await self._all(
            "SELECT e.order_id, e.date, e.time, e.address, t.name AS type_name, "
            "  (SELECT GROUP_CONCAT(s.name, ', ') FROM assignments a JOIN staff s ON s.id = a.staff_id "
            "   WHERE a.event_id = e.id AND a.status != 'rad') AS team "
            "FROM events e JOIN event_types t ON t.id = e.event_type_id ORDER BY e.date, e.time"
        )
        payments = await self._all(
            "SELECT order_id, amount, paid_at, note FROM payments ORDER BY id"
        )
        by_id = {o["id"]: {**dict(o), "events": [], "payments": []} for o in orders}
        for e in events:
            if e["order_id"] in by_id:
                by_id[e["order_id"]]["events"].append(dict(e))
        for p in payments:
            if p["order_id"] in by_id:
                by_id[p["order_id"]]["payments"].append(dict(p))
        return list(by_id.values())

    # ---------- Montaj va mijoz ----------

    ORDER_STAMPS = {"editing_taken_at", "editing_done_at", "ready_notified_at", "delivered_at"}

    async def order_brief(self, order_id: int):
        """Buyurtma + birinchi tadbir + qarz: montajchi va mijoz xabarlari uchun."""
        return await self._one(
            "SELECT o.*, ed.name AS editor_name, ed.tg_id AS editor_tg_id, "
            "  (SELECT MIN(date) FROM events WHERE order_id = o.id) AS first_date, "
            "  (SELECT GROUP_CONCAT(t.name, ', ') FROM events e JOIN event_types t "
            "   ON t.id = e.event_type_id WHERE e.order_id = o.id) AS types, "
            "  (SELECT GROUP_CONCAT(name, ', ') FROM services WHERE order_id = o.id) AS services, "
            "  (SELECT COALESCE(SUM(price), 0) FROM services WHERE order_id = o.id) - "
            "  (SELECT COALESCE(SUM(amount), 0) FROM payments WHERE order_id = o.id) AS debt "
            "FROM orders o LEFT JOIN staff ed ON ed.id = o.editor_id WHERE o.id = ?",
            (order_id,),
        )

    async def order_set_editor(self, order_id: int, staff_id: int) -> None:
        await self.conn.execute(
            "UPDATE orders SET editor_id = ?, editing_taken_at = datetime('now', 'localtime'), "
            "editing_done_at = NULL, ready_notified_at = NULL WHERE id = ?",
            (staff_id, order_id),
        )
        await self.conn.commit()

    async def order_stamp(self, order_id: int, field: str) -> None:
        """Bosqich vaqtini yozadi: montaj tugadi, mijozga xabar berildi, topshirildi."""
        assert field in self.ORDER_STAMPS
        await self.conn.execute(
            f"UPDATE orders SET {field} = datetime('now', 'localtime') WHERE id = ?", (order_id,)
        )
        await self.conn.commit()

    async def order_by_client_token(self, token: str):
        return await self._one("SELECT * FROM orders WHERE client_token = ?", (token,))

    async def order_link_client(self, order_id: int, tg_id: int) -> None:
        await self.conn.execute("UPDATE orders SET client_tg_id = ? WHERE id = ?", (tg_id, order_id))
        await self.conn.commit()

    async def staff_jobs(self, staff_id: int, from_day: str):
        """Xodimning shu kundan keyingi tadbirlari (bora olmayman deganlari bundan mustasno)."""
        return await self._all(
            "SELECT a.id, a.event_id, a.status, a.pay, e.date, e.time, e.address, e.lat, e.lon, "
            "  e.decor_note, t.name AS type_name, o.id AS order_id, o.client_name, o.client_phone, o.note "
            "FROM assignments a "
            "JOIN events e ON e.id = a.event_id "
            "JOIN event_types t ON t.id = e.event_type_id "
            "JOIN orders o ON o.id = e.order_id "
            "WHERE a.staff_id = ? AND e.date >= ? AND a.status != 'rad' "
            "ORDER BY e.date, e.time",
            (staff_id, from_day),
        )

    async def editor_jobs(self, staff_id: int):
        """Montajchiga berilgan, hali tayyor bo'lmagan to'ylar."""
        return await self._all(
            "SELECT o.id, o.client_name, o.editing_taken_at, "
            "  (SELECT MIN(date) FROM events WHERE order_id = o.id) AS first_date, "
            "  (SELECT GROUP_CONCAT(t.name, ', ') FROM events e JOIN event_types t "
            "   ON t.id = e.event_type_id WHERE e.order_id = o.id) AS types "
            "FROM orders o WHERE o.editor_id = ? AND o.editing_done_at IS NULL ORDER BY o.editing_taken_at",
            (staff_id,),
        )

    async def payment_add(self, order_id: int, amount: int, note: str) -> None:
        await self.conn.execute(
            "INSERT INTO payments (order_id, amount, note) VALUES (?, ?, ?)", (order_id, amount, note)
        )
        await self.conn.commit()

    # ---------- Kirim-chiqim ----------

    async def cash_add(self, book: str, kind: str, amount: int, currency: str, category: str,
                       note: str | None, day: str, ext_id: str | None = None) -> int:
        cur = await self.conn.execute(
            "INSERT INTO cash (book, kind, amount, currency, category, note, day, ext_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (book, kind, amount, currency, category, note, day, ext_id),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def cash_ext_ids(self) -> set[str]:
        return {r["ext_id"] for r in await self._all("SELECT ext_id FROM cash WHERE ext_id IS NOT NULL")}

    async def cash_delete(self, entry_id: int) -> None:
        await self.conn.execute("DELETE FROM cash WHERE id = ?", (entry_id,))
        await self.conn.commit()

    async def cash_entries(self, book: str, first: str = "0000-00-00", last: str = "9999-12-31") -> list[dict]:
        """Qo'lda yozilganlar + (Studiya uchun) zakaz to'lovlari, yangisi birinchi.

        src = 'cash' (o'chirsa bo'ladi) yoki 'order' (zakaz to'lovi, saytning zakaz qismida).
        """
        rows = await self._all(
            "SELECT id, 'cash' AS src, kind, amount, currency, category, note, day FROM cash "
            "WHERE book = ? AND day BETWEEN ? AND ? "
            "UNION ALL "
            "SELECT p.id, 'order', 'kirim', p.amount, 'UZS', ?, "
            "  '№' || p.order_id || ' · ' || o.client_name || COALESCE(' · ' || p.note, ''), "
            "  substr(p.paid_at, 1, 10) "
            "FROM payments p JOIN orders o ON o.id = p.order_id "
            "WHERE ? = 'biznes' AND substr(p.paid_at, 1, 10) BETWEEN ? AND ? "
            "ORDER BY day DESC, src, id DESC",
            (book, first, last, ORDER_CATEGORY, book, first, last),
        )
        return [dict(r) for r in rows]

    async def cash_categories_used(self, book: str, kind: str) -> list[str]:
        rows = await self._all(
            "SELECT category FROM cash WHERE book = ? AND kind = ? "
            "GROUP BY category COLLATE NOCASE ORDER BY COUNT(*) DESC",
            (book, kind),
        )
        return [r["category"] for r in rows]

    async def cash_spent(self, book: str, category: str, currency: str, first: str, last: str) -> int:
        (spent,) = await self._one(
            "SELECT COALESCE(SUM(amount), 0) FROM cash WHERE book = ? AND kind = 'chiqim' "
            "AND category = ? COLLATE NOCASE AND currency = ? AND day BETWEEN ? AND ?",
            (book, category, currency, first, last),
        )
        return spent

    async def cash_limits(self, book: str):
        return await self._all("SELECT * FROM cash_limits WHERE book = ? ORDER BY category", (book,))

    async def cash_limit_get(self, book: str, category: str, currency: str):
        return await self._one(
            "SELECT * FROM cash_limits WHERE book = ? AND category = ? AND currency = ?",
            (book, category, currency),
        )

    async def cash_limit_set(self, book: str, category: str, currency: str, amount: int) -> None:
        """amount = 0 bo'lsa limit o'chiriladi."""
        if amount:
            await self.conn.execute(
                "INSERT INTO cash_limits (book, category, currency, amount) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (book, category, currency) DO UPDATE SET amount = excluded.amount",
                (book, category, currency, amount),
            )
        else:
            await self.conn.execute(
                "DELETE FROM cash_limits WHERE book = ? AND category = ? AND currency = ?",
                (book, category, currency),
            )
        await self.conn.commit()

    # ---------- Eslatmalar ----------

    async def assignments_between(self, first: str, last: str):
        """Sanasi first..last oralig'idagi tadbirlarning barcha biriktirishlari (rad etilganlar ham)."""
        return await self._all(
            "SELECT a.*, s.name AS staff_name, s.role, s.tg_id AS staff_tg_id, "
            "  e.date, e.time, e.address, e.order_id, e.lat, e.lon, e.decor_photo, e.decor_note, "
            "  t.name AS type_name, "
            "  o.client_name, o.client_phone, o.note "
            "FROM assignments a "
            "JOIN staff s ON s.id = a.staff_id "
            "JOIN events e ON e.id = a.event_id "
            "JOIN event_types t ON t.id = e.event_type_id "
            "JOIN orders o ON o.id = e.order_id "
            "WHERE e.date BETWEEN ? AND ? AND s.active = 1 "
            "ORDER BY e.date, e.time, a.id",
            (first, last),
        )

    async def flash_pending(self, first: str, last: str):
        """Tadbirdan keyin fleshkasini topshirmagan operator/fotograflar (rad etganlar hisobga olinmaydi)."""
        return await self._all(
            "SELECT a.id, a.event_id, s.name AS staff_name, s.tg_id AS staff_tg_id, s.role, "
            "  e.date, e.time, e.order_id, t.name AS type_name, o.client_name "
            "FROM assignments a JOIN staff s ON s.id = a.staff_id JOIN events e ON e.id = a.event_id "
            "JOIN event_types t ON t.id = e.event_type_id JOIN orders o ON o.id = e.order_id "
            "WHERE e.date BETWEEN ? AND ? AND a.status != 'rad' AND a.flash_cleared_at IS NULL "
            "  AND s.role IN ('operator', 'fotograf') AND s.active = 1 "
            "ORDER BY e.date, e.time, a.id",
            (first, last),
        )

    async def assignment_flash_done(self, asg_id: int) -> bool:
        cur = await self.conn.execute(
            "UPDATE assignments SET flash_cleared_at = datetime('now', 'localtime') "
            "WHERE id = ? AND flash_cleared_at IS NULL",
            (asg_id,),
        )
        await self.conn.commit()
        return cur.rowcount == 1

    async def reminder_claim(self, kind: str, ref_id: int, day: str) -> bool:
        """Eslatmani "yuborildi" deb belgilaydi. Avval belgilangan bo'lsa — False."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO reminders (kind, ref_id, sent_on) VALUES (?, ?, ?)",
            (kind, ref_id, day),
        )
        await self.conn.commit()
        return cur.rowcount == 1

    async def assignment_respond(self, asg_id: int, status: str) -> None:
        await self.conn.execute(
            "UPDATE assignments SET status = ?, responded_at = datetime('now', 'localtime') "
            "WHERE id = ?",
            (status, asg_id),
        )
        await self.conn.commit()

    # ---------- Saytdan kelgan so'rovlar ----------

    async def site_request_add(self, kind: str, name: str, phone: str, data: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO site_requests (kind, name, phone, data) VALUES (?, ?, ?, ?)",
            (kind, name, phone, data),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def site_requests(self, limit: int = 50):
        return await self._all(
            "SELECT * FROM site_requests ORDER BY status = 'qabul', id DESC LIMIT ?", (limit,)
        )

    async def site_request_get(self, req_id: int):
        return await self._one("SELECT * FROM site_requests WHERE id = ?", (req_id,))

    async def site_request_take(self, req_id: int, who: str) -> bool:
        """Birinchi qabul qilgan yutadi; allaqachon olingan bo'lsa False."""
        cur = await self.conn.execute(
            "UPDATE site_requests SET status = 'qabul', taken_by = ?, taken_at = datetime('now', 'localtime') "
            "WHERE id = ? AND status = 'yangi'",
            (who, req_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0
