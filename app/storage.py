import aiosqlite, os
from typing import Optional, List, Tuple
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "./data/checkins.sqlite")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS checkins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  username TEXT,
  display_name TEXT,
  ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkins_chat_ts ON checkins(chat_id, ts);
CREATE INDEX IF NOT EXISTS idx_checkins_user_ts ON checkins(user_id, ts);

CREATE TABLE IF NOT EXISTS settings (
  chat_id INTEGER PRIMARY KEY,
  tz TEXT NOT NULL DEFAULT 'UTC',
  lang TEXT NOT NULL DEFAULT 'zh',
  work_start TEXT DEFAULT NULL,
  work_end   TEXT DEFAULT NULL,
  report_time TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS breaks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  kind TEXT NOT NULL,  -- 'smoke' | 'toilet'
  start_ts INTEGER NOT NULL,
  end_ts INTEGER DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_breaks_active ON breaks(chat_id, user_id, kind, end_ts);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()

# ----- settings / language / timezone -----
async def get_lang(chat_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM settings WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "zh"

async def get_tz(chat_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT tz FROM settings WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "UTC"

# ----- breaks -----
async def start_break(chat_id: int, user_id: int, kind: str, start_ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO breaks(chat_id, user_id, kind, start_ts) "
            "SELECT ?,?,?,? WHERE NOT EXISTS ("
            "SELECT 1 FROM breaks WHERE chat_id=? AND user_id=? AND kind=? AND end_ts IS NULL)",
            (chat_id, user_id, kind, start_ts, chat_id, user_id, kind),
        )
        await db.commit()

async def stop_break(chat_id: int, user_id: int, kind: str, end_ts: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        # 找到最近一次未结束的
        async with db.execute(
            "SELECT id, start_ts FROM breaks WHERE chat_id=? AND user_id=? AND kind=? AND end_ts IS NULL ORDER BY id DESC LIMIT 1",
            (chat_id, user_id, kind),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            bid, start_ts = row
        await db.execute("UPDATE breaks SET end_ts=? WHERE id=?", (end_ts, bid))
        await db.commit()
        return max(0, (end_ts - start_ts) // 60)

async def count_breaks_between(chat_id: int, user_id: int, kind: str, start_ts: int, end_ts: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM breaks WHERE chat_id=? AND user_id=? AND kind=? AND start_ts BETWEEN ? AND ?",
            (chat_id, user_id, kind, start_ts, end_ts),
        ) as cur:
            (n,) = await cur.fetchone()
            return n or 0

async def has_active_break(chat_id: int, user_id: int, kind: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM breaks WHERE chat_id=? AND user_id=? AND kind=? AND end_ts IS NULL LIMIT 1",
            (chat_id, user_id, kind),
        ) as cur:
            return await cur.fetchone() is not None
