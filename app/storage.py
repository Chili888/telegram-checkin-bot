import aiosqlite
import os
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
  work_start TEXT DEFAULT NULL,  -- 'HH:MM'
  work_end   TEXT DEFAULT NULL,  -- 'HH:MM'
  report_time TEXT DEFAULT NULL  -- 'HH:MM'
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

# --- settings ---
async def set_lang(chat_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(chat_id, lang) VALUES(?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET lang=excluded.lang",
            (chat_id, lang),
        )
        await db.commit()

async def get_lang(chat_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM settings WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "zh"

async def set_tz(chat_id: int, tz: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(chat_id, tz) VALUES(?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET tz=excluded.tz",
            (chat_id, tz),
        )
        await db.commit()

async def get_tz(chat_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT tz FROM settings WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "UTC"

async def set_workhours(chat_id: int, start: str, end: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(chat_id, work_start, work_end) VALUES(?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET work_start=excluded.work_start, work_end=excluded.work_end",
            (chat_id, start, end),
        )
        await db.commit()

async def get_workhours(chat_id: int) -> Tuple[Optional[str], Optional[str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT work_start, work_end FROM settings WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return (row[0], row[1]) if row else (None, None)

async def set_report_time(chat_id: int, time_hhmm: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(chat_id, report_time) VALUES(?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET report_time=excluded.report_time",
            (chat_id, time_hhmm),
        )
        await db.commit()

async def get_report_time(chat_id: int) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT report_time FROM settings WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

# --- checkins ---
async def add_checkin(chat_id: int, user_id: int, username: Optional[str], display_name: str, ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO checkins(chat_id, user_id, username, display_name, ts) VALUES(?,?,?,?,?)",
            (chat_id, user_id, username, display_name, ts),
        )
        await db.commit()

async def has_checkin_between(chat_id: int, user_id: int, start_ts: int, end_ts: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM checkins WHERE chat_id=? AND user_id=? AND ts BETWEEN ? AND ? LIMIT 1",
            (chat_id, user_id, start_ts, end_ts),
        ) as cur:
            return await cur.fetchone() is not None

async def leaderboard(chat_id: int, since_ts: Optional[int]):
    query = """
    SELECT user_id, COALESCE(display_name, username, CAST(user_id AS TEXT)) as name, COUNT(*) as cnt
    FROM checkins WHERE chat_id=? AND (? IS NULL OR ts >= ?)
    GROUP BY user_id, name
    ORDER BY cnt DESC, name ASC LIMIT 30
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, (chat_id, since_ts, since_ts)) as cur:
            return await cur.fetchall()

async def user_stats(chat_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), MAX(ts) FROM checkins WHERE chat_id=? AND user_id=?", (chat_id, user_id)) as cur:
            row = await cur.fetchone()
            return (row[0] or 0, row[1])

async def export_csv_rows(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT chat_id, user_id, COALESCE(username,''), COALESCE(display_name,''), ts FROM checkins WHERE chat_id=? ORDER BY ts DESC",
            (chat_id,)
        ) as cur:
            return await cur.fetchall()

# --- breaks ---
async def start_break(chat_id: int, user_id: int, kind: str, start_ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        # 如果已有未结束的同种break，先不重复插入
        await db.execute(
            "INSERT INTO breaks(chat_id, user_id, kind, start_ts) SELECT ?,?,?,? "
            "WHERE NOT EXISTS (SELECT 1 FROM breaks WHERE chat_id=? AND user_id=? AND kind=? AND end_ts IS NULL)",
            (chat_id, user_id, kind, start_ts, chat_id, user_id, kind),
        )
        await db.commit()

async def stop_break(chat_id: int, user_id: int, kind: str, end_ts: int) -> Optional[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE breaks SET end_ts=? WHERE chat_id=? AND user_id=? AND kind=? AND end_ts IS NULL",
            (end_ts, chat_id, user_id, kind),
        )
        await db.commit()
        # 计算持续时间（分钟）
        async with db.execute(
            "SELECT start_ts FROM breaks WHERE chat_id=? AND user_id=? AND kind=? ORDER BY id DESC LIMIT 1",
            (chat_id, user_id, kind),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return max(0, (end_ts - row[0]) // 60)
            return None

async def summarize_today(chat_id: int, start_ts: int, end_ts: int):
    # 返回：checkins数、smoke次数/时长、toilet次数/时长、Top前三
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM checkins WHERE chat_id=? AND ts BETWEEN ? AND ?", (chat_id, start_ts, end_ts)) as cur:
            c = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*), SUM((COALESCE(end_ts, ?) - start_ts)/60) FROM breaks WHERE chat_id=? AND kind='smoke' AND start_ts BETWEEN ? AND ?", (end_ts, chat_id, start_ts, end_ts)) as cur:
            s_cnt, s_min = await cur.fetchone()
        async with db.execute("SELECT COUNT(*), SUM((COALESCE(end_ts, ?) - start_ts)/60) FROM breaks WHERE chat_id=? AND kind='toilet' AND start_ts BETWEEN ? AND ?", (end_ts, chat_id, start_ts, end_ts)) as cur:
            t_cnt, t_min = await cur.fetchone()
        async with db.execute("""
            SELECT COALESCE(display_name, username, CAST(user_id AS TEXT)) as name, COUNT(*) as cnt
            FROM checkins WHERE chat_id=? AND ts BETWEEN ? AND ? GROUP BY user_id, name ORDER BY cnt DESC, name ASC LIMIT 3
        """, (chat_id, start_ts, end_ts)) as cur:
            top_rows = await cur.fetchall()
        return c or 0, s_cnt or 0, s_min or 0, t_cnt or 0, t_min or 0, top_rows or []
