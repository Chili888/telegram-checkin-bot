import aiosqlite, os
DB_PATH = os.getenv("DB_PATH","./data/checkins.sqlite")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkins(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    user_id INTEGER,
    username TEXT,
    display_name TEXT,
    ts INTEGER
);
CREATE TABLE IF NOT EXISTS settings(
    chat_id INTEGER PRIMARY KEY,
    tz TEXT DEFAULT 'UTC',
    lang TEXT DEFAULT 'zh',
    work_start TEXT,
    work_end TEXT,
    report_time TEXT
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()

async def get_lang(chat_id:int)->str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM settings WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "zh"
