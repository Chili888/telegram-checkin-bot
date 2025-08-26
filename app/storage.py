# app/storage.py
import os
import aiosqlite
from typing import List, Tuple, Optional

DB_PATH = os.getenv("DB_PATH", "data.db")

# ========= 基础：初始化 =========
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS chat_lang (
            chat_id    INTEGER PRIMARY KEY,
            lang       TEXT NOT NULL
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS checkins (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id      INTEGER NOT NULL,
            user_id      INTEGER NOT NULL,
            username     TEXT,
            display_name TEXT,
            ts           INTEGER NOT NULL
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS work_sessions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER NOT NULL,
            user_id   INTEGER NOT NULL,
            start_ts  INTEGER NOT NULL,
            end_ts    INTEGER
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS breaks (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER NOT NULL,
            user_id   INTEGER NOT NULL,
            kind      TEXT    NOT NULL,    -- 'smoke' | 'toilet' | 'takeout'
            start_ts  INTEGER NOT NULL,
            end_ts    INTEGER
        );
        """)
        # 索引
        await db.execute("CREATE INDEX IF NOT EXISTS idx_checkins_chat_ts ON checkins(chat_id, ts);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_checkins_user_ts ON checkins(user_id, ts);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_work_chat_user_start ON work_sessions(chat_id, user_id, start_ts);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_work_chat_user_end   ON work_sessions(chat_id, user_id, end_ts);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_breaks_chat_user_kind_start ON breaks(chat_id, user_id, kind, start_ts);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_breaks_chat_user_end ON breaks(chat_id, user_id, end_ts);")
        await db.commit()

# ========= 语言 =========
async def get_lang(chat_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM chat_lang WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "zh"

# ========= 签到 =========
async def add_checkin(chat_id: int, user_id: int, username: str, display_name: str, ts: int) -> None:
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

# ========= 上/下班 =========
async def _get_active_work_id(db: aiosqlite.Connection, chat_id: int, user_id: int) -> Optional[int]:
    async with db.execute(
        "SELECT id FROM work_sessions WHERE chat_id=? AND user_id=? AND end_ts IS NULL ORDER BY id DESC LIMIT 1",
        (chat_id, user_id),
    ) as cur:
        r = await cur.fetchone()
        return r[0] if r else None

async def start_work(chat_id: int, user_id: int, start_ts: int) -> bool:
    """
    开始上班。若已在上班中返回 False，否则创建并返回 True
    """
    async with aiosqlite.connect(DB_PATH) as db:
        if await _get_active_work_id(db, chat_id, user_id) is not None:
            return False
        await db.execute(
            "INSERT INTO work_sessions(chat_id, user_id, start_ts) VALUES(?,?,?)",
            (chat_id, user_id, start_ts),
        )
        await db.commit()
        return True

async def stop_work(chat_id: int, user_id: int, end_ts: int) -> Optional[int]:
    """
    结束上班，返回本次分钟数；若当前不在上班中返回 None
    """
    async with aiosqlite.connect(DB_PATH) as db:
        wid = await _get_active_work_id(db, chat_id, user_id)
        if wid is None:
            return None
        await db.execute("UPDATE work_sessions SET end_ts=? WHERE id=?", (end_ts, wid))
        await db.commit()
        # 计算分钟
        async with db.execute("SELECT start_ts, COALESCE(end_ts, ?) FROM work_sessions WHERE id=?",
                              (end_ts, wid)) as cur:
            s, e = await cur.fetchone()
            return max(0, (int(e) - int(s)) // 60)

async def work_minutes_between(chat_id: int, user_id: int, start_ts: int, end_ts: int) -> int:
    """
    统计与 [start_ts, end_ts] 区间有交集的上班分钟数（按交集裁剪）
    """
    total = 0
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT start_ts, COALESCE(end_ts, ?) FROM work_sessions "
            "WHERE chat_id=? AND user_id=? AND NOT (COALESCE(end_ts, ?) < ? OR start_ts > ?)",
            (end_ts, chat_id, user_id, end_ts, start_ts, end_ts),
        ) as cur:
            async for s, e in cur:
                s2, e2 = max(s, start_ts), min(e, end_ts)
                if e2 > s2:
                    total += (e2 - s2) // 60
    return int(total)

# ========= 休息（抽烟/如厕/取外卖） =========
async def has_active_break(chat_id: int, user_id: int, kind: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM breaks WHERE chat_id=? AND user_id=? AND kind=? AND end_ts IS NULL LIMIT 1",
            (chat_id, user_id, kind),
        ) as cur:
            return await cur.fetchone() is not None

async def start_break(chat_id: int, user_id: int, kind: str, start_ts: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO breaks(chat_id, user_id, kind, start_ts) VALUES(?,?,?,?)",
            (chat_id, user_id, kind, start_ts),
        )
        await db.commit()

async def stop_break(chat_id: int, user_id: int, kind: str, end_ts: int) -> Optional[int]:
    """
    停止某种休息，返回本次分钟数；若没有进行中则返回 None
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, start_ts FROM breaks WHERE chat_id=? AND user_id=? AND kind=? AND end_ts IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (chat_id, user_id, kind),
        ) as cur:
            r = await cur.fetchone()
            if not r:
                return None
            bid, s = r
        await db.execute("UPDATE breaks SET end_ts=? WHERE id=?", (end_ts, bid))
        await db.commit()
        return max(0, (int(end_ts) - int(s)) // 60)

async def count_breaks_between(chat_id: int, user_id: int, kind: str, start_ts: int, end_ts: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM breaks WHERE chat_id=? AND user_id=? AND kind=? AND start_ts BETWEEN ? AND ?",
            (chat_id, user_id, kind, start_ts, end_ts),
        ) as cur:
            r = await cur.fetchone()
            return int(r[0] if r else 0)

# ========= 汇总（用于快照/日报/周报） =========
async def _sum_break_minutes(db: aiosqlite.Connection, chat_id: int, kind: str, start_ts: int, end_ts: int) -> Tuple[int, int]:
    """
    返回 (次数, 分钟数)，分钟按区间裁剪。
    """
    # 次数：按开始时间落在区间内统计
    async with db.execute(
        "SELECT COUNT(*) FROM breaks WHERE chat_id=? AND kind=? AND start_ts BETWEEN ? AND ?",
        (chat_id, kind, start_ts, end_ts),
    ) as cur:
        rc = await cur.fetchone()
        cnt = int(rc[0] if rc else 0)

    # 分钟：与区间的交集
    minutes = 0
    async with db.execute(
        "SELECT start_ts, COALESCE(end_ts, ?) FROM breaks "
        "WHERE chat_id=? AND kind=? AND NOT (COALESCE(end_ts, ?) < ? OR start_ts > ?)",
        (end_ts, chat_id, kind, end_ts, start_ts, end_ts),
    ) as cur:
        async for s, e in cur:
            s2, e2 = max(s, start_ts), min(e, end_ts)
            if e2 > s2:
                minutes += (e2 - s2) // 60
    return cnt, int(minutes)

async def summarize_between(chat_id: int, start_ts: int, end_ts: int) -> Tuple[int, int, int, int, int, List[Tuple[str,int]]]:
    """
    返回：
      c              -> 区间内打卡人数（distinct user_id, from checkins）
      s_cnt, s_min   -> 吸烟次数 & 分钟
      t_cnt, t_min   -> 如厕次数 & 分钟
      top            -> 按打卡次数 Top5: [(name, cnt), ...]
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # 打卡人数 & Top
        async with db.execute(
            "SELECT COUNT(DISTINCT user_id) FROM checkins WHERE chat_id=? AND ts BETWEEN ? AND ?",
            (chat_id, start_ts, end_ts),
        ) as cur:
            rc = await cur.fetchone()
            c = int(rc[0] if rc else 0)

        top: List[Tuple[str,int]] = []
        async with db.execute(
            "SELECT COALESCE(display_name, username, CAST(user_id AS TEXT)) AS name, COUNT(*) AS cnt "
            "FROM checkins WHERE chat_id=? AND ts BETWEEN ? AND ? "
            "GROUP BY user_id ORDER BY cnt DESC, name ASC LIMIT 5",
            (chat_id, start_ts, end_ts),
        ) as cur:
            async for name, cnt in cur:
                top.append((name or "", int(cnt)))

        # 休息分钟/次数
        s_cnt, s_min = await _sum_break_minutes(db, chat_id, "smoke", start_ts, end_ts)
        t_cnt, t_min = await _sum_break_minutes(db, chat_id, "toilet", start_ts, end_ts)

    return c, s_cnt, s_min, t_cnt, t_min, top

# ========= 规则/日报辅助 =========
async def work_started_between(chat_id: int, user_id: int, start_ts: int, end_ts: int) -> bool:
    """今天是否已经“上班打卡”（按 work_sessions.start_ts 判断）"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM work_sessions WHERE chat_id=? AND user_id=? AND start_ts BETWEEN ? AND ? LIMIT 1",
            (chat_id, user_id, start_ts, end_ts),
        ) as cur:
            return await cur.fetchone() is not None

async def daily_person_summary(chat_id: int, start_ts: int, end_ts: int):
    """
    返回列表：[{'user_id':..., 'name':..., 'work_min':..., 'toilet_cnt':..., 'takeout_cnt':...}, ...]
    - work_min：按区间裁剪后的上班分钟
    - toilet_cnt / takeout_cnt：区间内开始次数
    """
    rows = []
    async with aiosqlite.connect(DB_PATH) as db:
        # 用户集合：checkins / breaks / work_sessions
        users = set()

        async with db.execute(
            "SELECT DISTINCT user_id FROM checkins WHERE chat_id=? AND ts BETWEEN ? AND ?",
            (chat_id, start_ts, end_ts),
        ) as cur:
            users.update([r[0] for r in await cur.fetchall()])

        async with db.execute(
            "SELECT DISTINCT user_id FROM breaks WHERE chat_id=? AND start_ts BETWEEN ? AND ?",
            (chat_id, start_ts, end_ts),
        ) as cur:
            users.update([r[0] for r in await cur.fetchall()])

        async with db.execute(
            "SELECT DISTINCT user_id FROM work_sessions "
            "WHERE chat_id=? AND NOT (COALESCE(end_ts, ?) < ? OR start_ts > ?)",
            (chat_id, end_ts, start_ts, end_ts),
        ) as cur:
            users.update([r[0] for r in await cur.fetchall()])

        for uid in users:
            # 名称
            async with db.execute(
                "SELECT COALESCE(display_name, username, CAST(user_id AS TEXT)) "
                "FROM checkins WHERE chat_id=? AND user_id=? ORDER BY ts DESC LIMIT 1",
                (chat_id, uid),
            ) as cur:
                r = await cur.fetchone()
                name = r[0] if r and r[0] else str(uid)

            # 上班分钟（交集）
            work_min = 0
            async with db.execute(
                "SELECT start_ts, COALESCE(end_ts, ?) FROM work_sessions "
                "WHERE chat_id=? AND user_id=? AND NOT (COALESCE(end_ts, ?) < ? OR start_ts > ?)",
                (end_ts, chat_id, uid, end_ts, start_ts, end_ts),
            ) as cur:
                async for s, e in cur:
                    s2, e2 = max(s, start_ts), min(e, end_ts)
                    if e2 > s2:
                        work_min += (e2 - s2) // 60

            # 次数
            async with db.execute(
                "SELECT COUNT(*) FROM breaks WHERE chat_id=? AND user_id=? AND kind='toilet' AND start_ts BETWEEN ? AND ?",
                (chat_id, uid, start_ts, end_ts),
            ) as cur:
                toilet_cnt = (await cur.fetchone())[0] or 0

            async with db.execute(
                "SELECT COUNT(*) FROM breaks WHERE chat_id=? AND user_id=? AND kind='takeout' AND start_ts BETWEEN ? AND ?",
                (chat_id, uid, start_ts, end_ts),
            ) as cur:
                takeout_cnt = (await cur.fetchone())[0] or 0

            rows.append({
                "user_id": uid,
                "name": name,
                "work_min": int(work_min),
                "toilet_cnt": int(toilet_cnt),
                "takeout_cnt": int(takeout_cnt),
            })

    rows.sort(key=lambda x: (-x["work_min"], x["toilet_cnt"], x["takeout_cnt"], x["name"]))
    return rows
