"""FSM holatini (yarim yozilgan buyurtma va h.k.) SQLite'da saqlash.
Bot qayta ishga tushsa ham admin qolgan joyidan davom etadi."""

import json
from typing import Any, Mapping

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from .db import Database


def _key(key: StorageKey) -> str:
    return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{key.thread_id or 0}:{key.destiny}"


class SQLiteStorage(BaseStorage):
    def __init__(self, db: Database):
        self.db = db

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        await self.db.conn.execute(
            "INSERT INTO fsm (key, state) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET state = excluded.state",
            (_key(key), value),
        )
        await self.db.conn.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        row = await self.db._one("SELECT state FROM fsm WHERE key = ?", (_key(key),))
        return row["state"] if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await self.db.conn.execute(
            "INSERT INTO fsm (key, data) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET data = excluded.data",
            (_key(key), json.dumps(dict(data), ensure_ascii=False)),
        )
        await self.db.conn.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        row = await self.db._one("SELECT data FROM fsm WHERE key = ?", (_key(key),))
        return json.loads(row["data"]) if row and row["data"] else {}

    async def close(self) -> None:
        pass  # ulanishni Database o'zi yopadi
