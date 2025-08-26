import aiosqlite, os
from typing import Optional, List, Tuple

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

CREATE TABLE IF NOT EXISTS work_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  start_ts INTEGER NOT NULL,
  end_ts INTEGER DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_work_active ON work_sessions(chat_id, user_id, end_ts);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()

# ===== language / tz =====
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

# ===== checkins =====
async def add_checkin(chat_id: int, user_id: int, username: str, display_name: str, ts: int):
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
    FROM checkins
    WHERE chat_id=? AND (? IS NULL OR ts >= ?)
    GROUP BY user_id, name
    ORDER BY cnt DESC, name ASC
    LIMIT 30
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, (chat_id, since_ts, since_ts)) as cur:
            return await cur.fetchall()

async def user_stats(chat_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), MAX(ts) FROM checkins WHERE chat_id=? AND user_id=?", (chat_id, user_id)) as cur:
            row = await cur.fetchone()
            return (row[0] or 0, row[1])

# ===== breaks =====
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

# ===== work sessions =====
async def has_active_work(chat_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM work_sessions WHERE chat_id=? AND user_id=? AND end_ts IS NULL LIMIT 1",
            (chat_id, user_id),
        ) as cur:
            return await cur.fetchone() is not None

async def start_work(chat_id: int, user_id: int, start_ts: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM work_sessions WHERE chat_id=? AND user_id=? AND end_ts IS NULL LIMIT 1",
            (chat_id, user_id),
        ) as cur:
            if await cur.fetchone():
                return False
        await db.execute(
            "INSERT INTO work_sessions(chat_id, user_id, start_ts) VALUES(?,?,?)",
            (chat_id, user_id, start_ts),
        )
        await db.commit()
        return True

async def stop_work(chat_id: int, user_id: int, end_ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, start_ts FROM work_sessions WHERE chat_id=? AND user_id=? AND end_ts IS NULL ORDER BY id DESC LIMIT 1",
            (chat_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            wid, start_ts = row
        await db.execute("UPDATE work_sessions SET end_ts=? WHERE id=?", (end_ts, wid))
        await db.commit()
        minutes = max(0, (end_ts - start_ts) // 60)
        return minutes

async def work_minutes_between(chat_id: int, user_id: int, start_ts: int, end_ts: int) -> int:
    """统计某用户在区间内的累计上班分钟数（按区间裁剪）"""
    async with aiosqlite.connect(DB_PATH) as db:
        total = 0
        # 结束在区间内
        async with db.execute(
            "SELECT start_ts, COALESCE(end_ts, ?) FROM work_sessions "
            "WHERE chat_id=? AND user_id=? AND NOT (COALESCE(end_ts, ?) < ? OR start_ts > ?)",
            (end_ts, chat_id, user_id, end_ts, start_ts, end_ts),
        ) as cur:
            async for s, e in cur:
                s2 = max(s, start_ts)
                e2 = min(e, end_ts)
                if e2 > s2:
                    total += (e2 - s2) // 60
        return int(total)

# ===== summary for reports =====
async def summarize_between(chat_id: int, start_ts: int, end_ts: int):
    """返回：checkins数、smoke次数/分钟、toilet次数/分钟、Top3 打卡"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM checkins WHERE chat_id=? AND ts BETWEEN ? AND ?", (chat_id, start_ts, end_ts)) as cur:
            c = (await cur.fetchone())[0] or 0
        async with db.execute(
            "SELECT COUNT(*), SUM((COALESCE(end_ts, ?) - start_ts)/60) FROM breaks "
            "WHERE chat_id=? AND kind='smoke' AND start_ts BETWEEN ? AND ?",
            (end_ts, chat_id, start_ts, end_ts),
        ) as cur:
            s_cnt, s_min = await cur.fetchone()
        async with db.execute(
            "SELECT COUNT(*), SUM((COALESCE(end_ts, ?) - start_ts)/60) FROM breaks "
            "WHERE chat_id=? AND kind='toilet' AND start_ts BETWEEN ? AND ?",
            (end_ts, chat_id, start_ts, end_ts),
        ) as cur:
            t_cnt, t_min = await cur.fetchone()
        async with db.execute("""
            SELECT COALESCE(display_name, username, CAST(user_id AS TEXT)) as name, COUNT(*) as cnt
            FROM checkins
            WHERE chat_id=? AND ts BETWEEN ? AND ?
            GROUP BY user_id, name
            ORDER BY cnt DESC, name ASC LIMIT 3
        """, (chat_id, start_ts, end_ts)) as cur:
            top_rows = await cur.fetchall()
        return c, (s_cnt or 0), int(s_min or 0), (t_cnt or 0), int(t_min or 0), top_rows or []
