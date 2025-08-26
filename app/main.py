import asyncio, os, logging, re
from datetime import datetime, timedelta, timezone, time as dtime
import pytz, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ChatMember, ChatMemberAdministrator, ChatMemberOwner
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    AIORateLimiter, MessageHandler, filters
)
from telegram.error import BadRequest

from . import storage
from .utils import t

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pro-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "dev-secret")
ENABLE_POLLING = os.getenv("ENABLE_POLLING", "false").lower() == "true"
PORT = int(os.getenv("PORT", "8000"))

# ===== 固定配置：美东时区 & 日程 =====
TZ_ET = pytz.timezone("America/New_York")
DAILY_GREETING_ET = dtime(7, 50, 0, tzinfo=TZ_ET)

WORK_SCHEDULE = {
    0: (8, 0, 22, 0),  # Mon
    1: (8, 0, 22, 0),  # Tue
    2: (8, 0, 22, 0),  # Wed
    3: (8, 0, 22, 0),  # Thu
    4: (8, 0, 22, 0),  # Fri
    5: (11, 0, 20, 0), # Sat
    6: (9, 0, 20, 0),  # Sun
}
REMIND_BEFORE_MIN = 5

SMOKE_LIMIT_MIN = 10
SMOKE_MAX_PER_DAY = 10
TOILET_LIMIT_MIN = 20
TOILET_MAX_PER_DAY = 5
PENALTY_MIN = 5

# ===== UI =====
def kbd_checkin(lang):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_checkin"), callback_data="checkin")]])

def reply_kbd_cn():
    rows = [
        [KeyboardButton("上班打卡"), KeyboardButton("下班打卡")],
        [KeyboardButton("上厕所"), KeyboardButton("拉完了")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

WELCOME_TEXT = (
    "✅ 欢迎加入！今天也要把事情做好，赚大钱 💰！\n\n"
    "功能清单：\n"
    "✅ 🚬 吸烟限制（10 分钟/天 10 次/超时罚站 5 分钟）\n"
    "✅ 🚽 如厕限制（20 分钟/天 5 次/超时罚站 5 分钟）\n"
    "✅ 📈 下班日报 + 周总结\n\n"
    "中文关键词：上班打卡/下班打卡、抽烟=cy/结束抽烟=cy0、厕所=wc/结束厕所=wc0、排行榜/统计/帮助\n"
)

def greeting_text():
    return (
        "⏰ 早上好！今天继续努力工作，冲业绩、赚大钱！💸\n\n"
        "快捷操作：\n"
        "• 发送「上班打卡/下班打卡/打卡」\n"
        "• 发送「抽烟/结束抽烟」「上厕所/结束厕所」\n"
        "• 上下班前 5 分钟自动提醒打卡\n"
    )

# ===== 工具函数 =====
async def ensure_db(): await storage.init_db()
async def get_lang(chat_id:int) -> str: return await storage.get_lang(chat_id)
def is_admin_status(m: ChatMember) -> bool: return isinstance(m,(ChatMemberAdministrator,ChatMemberOwner))

def _next_weekly_occurrence(weekday: int, hh: int, mm: int, tz: pytz.BaseTzInfo) -> datetime:
    now_local = datetime.now(tz)
    target = tz.localize(datetime(now_local.year, now_local.month, now_local.day, hh, mm, 0))
    delta = (weekday - target.weekday()) % 7
    target = target + timedelta(days=delta)
    if target <= now_local: target += timedelta(days=7)
    return target.astimezone(timezone.utc)

def _et_day_bounds(dt_et: datetime):
    start_local = TZ_ET.localize(datetime(dt_et.year, dt_et.month, dt_et.day, 0, 0, 0))
    end_local = start_local + timedelta(days=1) - timedelta(seconds=1)
    return int(start_local.timestamp()), int(end_local.timestamp()), start_local, end_local

# ===== 计划任务 =====
async def daily_greeting_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
    await context.bot.send_message(chat_id=chat_id, text=greeting_text())

async def work_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    chat_id, kind, h, m = d["chat_id"], d["kind"], d["h"], d["m"]
    when = f"{h:02d}:{m:02d} ET"
    if kind == "start":
        txt = f"⏰ {when} 即将上班（还有 {REMIND_BEFORE_MIN} 分钟）— 记得『打卡』！"
    else:
        txt = f"⏰ {when} 即将下班（还有 {REMIND_BEFORE_MIN} 分钟）— 记得收尾并『打卡』！"
    await context.bot.send_message(chat_id=chat_id, text=txt)

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE, chat_id: int, ref_et: datetime):
    lang = await get_lang(chat_id)
    start_ts, end_ts, start_local, _ = _et_day_bounds(ref_et)
    c, s_cnt, s_min, t_cnt, t_min, top = await storage.summarize_between(chat_id, start_ts, end_ts)
    top_text = "\n".join([f"- {name}: {cnt}" for (name, cnt) in top]) if top else "（无）"
    title = f"📈 今日统计报表（{start_local.strftime('%Y-%m-%d')}，ET）"
    body = (
        f"打卡人数：{c}\n"
        f"吸烟：{s_cnt} 次；合计 {s_min} 分钟\n"
        f"如厕：{t_cnt} 次；合计 {t_min} 分钟\n"
        f"Top 打卡：\n{top_text}"
    )
    await context.bot.send_message(chat_id=chat_id, text=f"{title}\n\n{body}")

async def weekly_report_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
    now_et = datetime.now(TZ_ET)
    weekday = now_et.weekday()
    monday = (now_et - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = TZ_ET.localize(datetime(monday.year, monday.month, monday.day, 0, 0, 0))
    sunday_end = monday + timedelta(days=7) - timedelta(seconds=1)
    start_ts, end_ts = int(monday.timestamp()), int(sunday_end.timestamp())

    c, s_cnt, s_min, t_cnt, t_min, top = await storage.summarize_between(chat_id, start_ts, end_ts)
    top_text = "\n".join([f"- {name}: {cnt}" for (name, cnt) in top]) if top else "（无）"
    title = f"🧾 本周总结（{monday.strftime('%Y-%m-%d')} ~ {sunday_end.strftime('%Y-%m-%d')}，ET）"
    body = (
        f"周内打卡：{c}\n"
        f"吸烟合计：{s_cnt} 次；{s_min} 分钟\n"
        f"如厕合计：{t_cnt} 次；{t_min} 分钟\n"
        f"Top 打卡：\n{top_text}\n\n"
        f"下周继续努力，冲业绩、赚大钱！💰"
    )
    await context.bot.send_message(chat_id=chat_id, text=f"{title}\n\n{body}")

async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
    ref_et = datetime.now(TZ_ET)
    await send_daily_report(context, chat_id, ref_et)

async def schedule_chat_jobs(app: Application, chat_id: int):
    for j in list(app.job_queue.jobs()):
        if j.name and (j.name.startswith(f"greet-{chat_id}-") or j.name.startswith(f"workrem-{chat_id}-")
                       or j.name.startswith(f"dailyrep-{chat_id}-") or j.name == f"weekly-{chat_id}"):
            j.schedule_removal()

    first = _next_weekly_occurrence(datetime.now(TZ_ET).weekday(), DAILY_GREETING_ET.hour, DAILY_GREETING_ET.minute, TZ_ET)
    app.job_queue.run_repeating(daily_greeting_job, interval=24*3600, first=first,
                                name=f"greet-{chat_id}-daily", data={"chat_id": chat_id})

    for wd, (sh, sm, eh, em) in WORK_SCHEDULE.items():
        start_first = _next_weekly_occurrence(wd, sh, sm, TZ_ET) - timedelta(minutes=REMIND_BEFORE_MIN)
        app.job_queue.run_repeating(work_reminder_job, interval=7*24*3600, first=start_first,
                                    name=f"workrem-{chat_id}-start-{wd}",
                                    data={"chat_id": chat_id, "kind": "start", "h": sh, "m": sm})
        end_first = _next_weekly_occurrence(wd, eh, em, TZ_ET) - timedelta(minutes=REMIND_BEFORE_MIN)
        app.job_queue.run_repeating(work_reminder_job, interval=7*24*3600, first=end_first,
                                    name=f"workrem-{chat_id}-end-{wd}",
                                    data={"chat_id": chat_id, "kind": "end", "h": eh, "m": em})

        # 下班即刻日报
        end_exact = _next_weekly_occurrence(wd, eh, em, TZ_ET)
        app.job_queue.run_repeating(daily_report_job, interval=7*24*3600, first=end_exact,
                                    name=f"dailyrep-{chat_id}-{wd}", data={"chat_id": chat_id})

    sun_eh, sun_em = WORK_SCHEDULE[6][2], WORK_SCHEDULE[6][3]
    weekly_first = _next_weekly_occurrence(6, sun_eh, sun_em, TZ_ET) + timedelta(minutes=5)
    app.job_queue.run_repeating(weekly_report_job, interval=7*24*3600, first=weekly_first,
                                name=f"weekly-{chat_id}", data={"chat_id": chat_id})

# ===== 命令 =====
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    lang = await get_lang(chat.id)
    await update.message.reply_text(WELCOME_TEXT, reply_markup=reply_kbd_cn())
    await schedule_chat_jobs(context.application, chat.id)

async def checkin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    user = update.effective_user
    lang = await get_lang(chat.id)

    now_et = datetime.now(TZ_ET)
    start_ts, end_ts, _, _ = _et_day_bounds(now_et)

    already = await storage.has_checkin_between(chat.id, user.id, start_ts, end_ts)
    if already:
        await update.message.reply_text(t(lang, "checked_today", tz="ET"), reply_markup=reply_kbd_cn())
        return

    now_ts = int(datetime.now(timezone.utc).timestamp())
    await storage.add_checkin(chat.id, user.id, user.username or "", user.full_name, now_ts)
    await update.message.reply_text(t(lang, "checkin_ok", tz="ET"), reply_markup=reply_kbd_cn())

# ===== 上下班打卡（含累计统计）=====
async def workin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    user = update.effective_user
    now_ts = int(datetime.now(timezone.utc).timestamp())
    ok = await storage.start_work(chat.id, user.id, now_ts)
    name = user.first_name or user.full_name or (user.username or "伙伴")
    if ok:
        await update.message.reply_text(f"👋 早上好，{name}！上班加油，业绩长虹！🚀", reply_markup=reply_kbd_cn())
    else:
        await update.message.reply_text("你已经在上班中，先『下班打卡』再重新开始哦～", reply_markup=reply_kbd_cn())

async def workout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    user = update.effective_user
    name = user.first_name or user.full_name or (user.username or "伙伴")
    now_ts = int(datetime.now(timezone.utc).timestamp())

    mins = await storage.stop_work(chat.id, user.id, now_ts)
    if mins is None:
        await update.message.reply_text("现在不在上班状态哦～先『上班打卡』再来", reply_markup=reply_kbd_cn())
        return

    # 计算今天/本周累计（ET）
    now_et = datetime.now(TZ_ET)
    day_start_ts, day_end_ts, _, _ = _et_day_bounds(now_et)
    weekday = now_et.weekday()
    monday = (now_et - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = TZ_ET.localize(datetime(monday.year, monday.month, monday.day, 0, 0, 0))
    sunday_end = monday + timedelta(days=7) - timedelta(seconds=1)
    week_start_ts, week_end_ts = int(monday.timestamp()), int(sunday_end.timestamp())

    day_total = await storage.work_minutes_between(chat.id, user.id, day_start_ts, day_end_ts)
    week_total = await storage.work_minutes_between(chat.id, user.id, week_start_ts, week_end_ts)

    def fmt(mins:int):
        h, m = divmod(int(mins), 60)
        return f"{h}小时{m}分钟" if h else f"{m}分钟"

    await update.message.reply_text(
        f"👏 辛苦了，{name}！\n"
        f"本次上班：{fmt(mins)}\n"
        f"今日累计：{fmt(day_total)}\n"
        f"本周累计：{fmt(week_total)}",
        reply_markup=reply_kbd_cn()
    )

# ===== 休息（限时 + 限次 + 罚站）=====
async def _day_bounds_et():
    now_local = datetime.now(TZ_ET)
    start_local = TZ_ET.localize(datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0))
    end_local = start_local + timedelta(days=1) - timedelta(seconds=1)
    return int(start_local.timestamp()), int(end_local.timestamp())

async def _start_break(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    chat = update.effective_chat; user = update.effective_user
    now_ts = int(datetime.now(timezone.utc).timestamp())
    day_start, day_end = await _day_bounds_et()
    max_per_day = SMOKE_MAX_PER_DAY if kind == "smoke" else TOILET_MAX_PER_DAY
    cnt = await storage.count_breaks_between(chat.id, user.id, kind, day_start, day_end)
    if cnt >= max_per_day:
        await update.message.reply_text(f"⚠️ 今日{ '吸烟' if kind=='smoke' else '如厕' }次数已达上限（{max_per_day} 次）"); return
    if await storage.has_active_break(chat.id, user.id, kind):
        await update.message.reply_text(f"已在{ '吸烟' if kind=='smoke' else '如厕' }中，先『结束』再开始"); return
    await storage.start_break(chat.id, user.id, kind, now_ts)
    await update.message.reply_text(f"⏱️ 开始{ '吸烟' if kind=='smoke' else '如厕' }休息（计时已启动）")
    limit_min = SMOKE_LIMIT_MIN if kind == "smoke" else TOILET_LIMIT_MIN
    context.job_queue.run_once(break_limit_job, when=datetime.now(timezone.utc) + timedelta(minutes=limit_min),
        chat_id=chat.id, name=f"limit-{kind}-{chat.id}-{user.id}",
        data={"chat_id": chat.id, "user_id": user.id, "kind": kind, "limit_min": limit_min})

async def _stop_break(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    chat = update.effective_chat; user = update.effective_user
    now_ts = int(datetime.now(timezone.utc).timestamp())
    mins = await storage.stop_break(chat.id, user.id, kind, now_ts)
    if mins is None:
        await update.message.reply_text("当前没有正在进行的休息"); return
    limit_min = SMOKE_LIMIT_MIN if kind == "smoke" else TOILET_LIMIT_MIN
    txt = f"✅ 结束{ '吸烟' if kind=='smoke' else '如厕' }休息，持续 {mins} 分钟"
    if mins > limit_min:
        txt += f"（已超过 {limit_min} 分钟，罚站 {PENALTY_MIN} 分钟）"
        await update.message.reply_text(f"🚫 现在开始罚站 {PENALTY_MIN} 分钟")
        context.job_queue.run_once(lambda c: c.bot.send_message(chat.id, "⏳ 罚站结束，注意专注工作！"),
                                   when=datetime.now(timezone.utc) + timedelta(minutes=PENALTY_MIN))
    await update.message.reply_text(txt)

async def break_limit_job(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    if await storage.has_active_break(d["chat_id"], d["user_id"], d["kind"]):
        kind_cn = "吸烟" if d["kind"]=="smoke" else "如厕"
        await context.bot.send_message(chat_id=d["chat_id"],
            text=f"⏰ {kind_cn}已超过 {d['limit_min']} 分钟，请尽快结束！超时将罚站 {PENALTY_MIN} 分钟")

# ===== 关键词触发 =====
def _set_args(context, args_list):
    try: context.args = args_list
    except Exception: pass

async def keyword_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text_raw = update.message.text.strip()
    text = text_raw.lower()

    # 上下班
    if text_raw in ["上班打卡","上班","上班了","开始上班"]:
        await workin_cmd(update, context); return
    if text_raw in ["下班打卡","下班","下班了","收工"]:
        await workout_cmd(update, context); return

    # 打卡
    if any(w in text_raw for w in ["打卡", "签到"]) or any(w in text for w in ["check in", "checkin"]):
        await checkin_cmd(update, context); return

    # 休息
    if any(w in text_raw for w in ["结束吸烟", "抽完了", "抽烟结束", "cy0"]) or "smoke stop" in text:
        await _stop_break(update, context, "smoke"); return
    if any(w in text_raw for w in ["结束厕所", "拉完了", "如厕结束", "停止如厕", "wc0"]) or "toilet stop" in text:
        await _stop_break(update, context, "toilet"); return
    if any(w in text_raw for w in ["抽烟", "吸烟", "cy"]) or "smoke" in text:
        await _start_break(update, context, "smoke"); return
    if any(w in text_raw for w in ["上厕所", "厕所", "如厕", "卫生间", "洗手间", "wc"]) or "toilet" in text or "wc" in text:
        await _start_break(update, context, "toilet"); return

    # 排行/统计/帮助
    if any(w in text_raw for w in ["排行榜","排行","榜单"]) or "leaderboard" in text:
        m = re.search(r"(\d{1,3})\s*天", text_raw)
        if "全部" in text_raw or "all" in text: _set_args(context, ["all"])
        elif m: _set_args(context, [m.group(1)])
        else: _set_args(context, [])
        # 这里可以接 leaderboard_cmd（留空位）
        await update.message.reply_text("📊 排行榜功能（可接入存储）"); return

    if any(w in text_raw for w in ["统计","我的统计","个人统计"]) or "stats" in text:
        await update.message.reply_text("📈 个人统计（可接入存储）"); return

    if any(w in text_raw for w in ["帮助","说明","怎么用"]) or "help" in text:
        await start_cmd(update, context); return

# ===== 按钮回调（打卡） =====
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = query.message.chat
    lang = await get_lang(chat.id)
    await query.answer(cache_time=5)
    try:
        await query.edit_message_text(t(lang, "checkin_ok", tz="ET"), reply_markup=kbd_checkin(lang))
    except BadRequest as e:
        if "Message is not modified" not in str(e): raise

# ===== FastAPI webhook =====
app_fastapi = FastAPI()
bot_app = None

@app_fastapi.get("/healthz")
async def healthz(): return PlainTextResponse("ok")

@app_fastapi.post(f"/webhook/{WEBHOOK_SECRET}")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return PlainTextResponse("ok")

# ===== 启动 =====
async def main_async():
    global bot_app
    app = Application.builder().token(BOT_TOKEN).rate_limiter(AIORateLimiter()).build()
    bot_app = app

    await app.initialize()
    # 斜杠菜单
    await app.bot.set_my_commands([
        ("workin", "上班打卡"),
        ("workout", "下班打卡"),
        ("smoke_start", "抽烟"),
        ("smoke_stop", "结束抽烟"),
        ("toilet_start", "上厕所"),
        ("toilet_stop", "结束厕所"),
    ])

    # handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("workin", workin_cmd))
    app.add_handler(CommandHandler("workout", workout_cmd))
    app.add_handler(CommandHandler("smoke_start", lambda u,c: _start_break(u,c,"smoke")))
    app.add_handler(CommandHandler("smoke_stop",  lambda u,c: _stop_break(u,c,"smoke")))
    app.add_handler(CommandHandler("toilet_start", lambda u,c: _start_break(u,c,"toilet")))
    app.add_handler(CommandHandler("toilet_stop",  lambda u,c: _stop_break(u,c,"toilet")))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_handler))
    app.add_handler(CallbackQueryHandler(on_button))

    if ENABLE_POLLING:
        await app.start(); await app.updater.start_polling(); await app.updater.idle()
    else:
        await app.bot.set_webhook(url=f"{BASE_URL}/webhook/{WEBHOOK_SECRET}")
        await app.start()
        server = uvicorn.Server(uvicorn.Config(app_fastapi, host="0.0.0.0", port=PORT))
        await server.serve()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
