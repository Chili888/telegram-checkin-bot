import aiosqlite, os
from typing import List, Tuple, Optional

DB_PATH = os.getenv("DB_PATH","./data/checkins.sqlite")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS checkins(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER, username TEXT, display_name TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS settings(chat_id INTEGER PRIMARY KEY, tz TEXT DEFAULT 'UTC', lang TEXT DEFAULT 'zh', work_start TEXT, work_end TEXT, report_time TEXT);
CREATE TABLE IF NOT EXISTS breaks(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER, kind TEXT, start_ts INTEGER, end_ts INTEGER);
CREATE TABLE IF NOT EXISTS triggers(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, keyword TEXT NOT NULL, action TEXT NOT NULL,
    UNIQUE(chat_id, keyword) ON CONFLICT IGNORE
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA); await db.commit()

# triggers
async def add_trigger(chat_id:int, keyword:str, action:str)->bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT OR IGNORE INTO triggers(chat_id, keyword, action) VALUES(?,?,?)", (chat_id, keyword, action))
        await db.commit()
        return cur.rowcount > 0

async def del_trigger(chat_id:int, keyword:str)->bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM triggers WHERE chat_id=? AND keyword=?", (chat_id, keyword))
        await db.commit()
        return cur.rowcount > 0

async def list_triggers(chat_id:int)->List[Tuple[str,str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT keyword, action FROM triggers WHERE chat_id=? ORDER BY keyword ASC", (chat_id,)) as cur:
            return await cur.fetchall()

# simple settings/lang
async def get_lang(chat_id:int)->str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM settings WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "zh"
