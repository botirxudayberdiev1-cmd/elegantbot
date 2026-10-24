import os
import secrets

import aiosqlite

from .config import ADMIN_IDS, DEFAULT_EVENT_TYPES

# Barcha 8 ta jadval birdaniga yaratiladi, keyingi bosqichlarda bazani o'zgartirish shart bo'lmaydi.
SCHEMA = """
-- 1. Xodimlar
CREATE TABLE IF NOT EXISTS staff (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'montajchi')),
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
    address       TEXT
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
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON")
        await self.conn.executescript(SCHEMA)
        async with self.conn.execute("SELECT COUNT(*) FROM event_types") as cur:
            (count,) = await cur.fetchone()
        if count == 0:
            await self.conn.executemany(
                "INSERT INTO event_types (name) VALUES (?)", [(n,) for n in DEFAULT_EVENT_TYPES]
            )
        await self.conn.commit()

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
        return await self._all(
            "SELECT * FROM staff WHERE active = 1 AND role = 'operator' ORDER BY name"
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
                    "INSERT INTO events (order_id, event_type_id, date, time, address) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (order_id, ev["type_id"], ev["date"], ev["time"], ev["address"]),
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
            "SELECT a.*, s.name AS staff_name, s.tg_id AS staff_tg_id, "
            "  e.date, e.time, e.address, e.order_id, t.name AS type_name, "
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

    async def assignment_respond(self, asg_id: int, status: str) -> None:
        await self.conn.execute(
            "UPDATE assignments SET status = ?, responded_at = datetime('now', 'localtime') "
            "WHERE id = ?",
            (status, asg_id),
        )
        await self.conn.commit()
