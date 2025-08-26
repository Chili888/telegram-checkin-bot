import asyncio, os, logging, re
from datetime import datetime, timedelta, timezone, time as dtime
import pytz, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, ChatMemberAdministrator, ChatMemberOwner
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

# ====== 你的需求常量 ======
TZ_ET = pytz.timezone("America/New_York")              # 美国东部时间
DAILY_GREETING_ET = dtime(7, 50, 0, tzinfo=TZ_ET)      # 每天 7:50 ET 问好

# 上下班时间（ET）
WORK_SCHEDULE = {
    0: (8, 0, 22, 0),  # Mon
    1: (8, 0, 22, 0),  # Tue
    2: (8, 0, 22, 0),  # Wed
    3: (8, 0, 22, 0),  # Thu
    4: (8, 0, 22, 0),  # Fri
    5: (11, 0, 20, 0), # Sat
    6: (9, 0, 20, 0),  # Sun
}
REMIND_BEFORE_MIN = 5  # 上下班前 5 分钟提醒打卡

# 休息限制与处罚
SMOKE_LIMIT_MIN = 10
SMOKE_MAX_PER_DAY = 10
TOILET_LIMIT_MIN = 20
TOILET_MAX_PER_DAY = 5
PENALTY_MIN = 5  # 超时罚站 5 分钟（提醒）

# ====== 常用工具 ======
def kbd_checkin(lang):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_checkin"), callback_data="checkin")]])

async def ensure_db():
    await storage.init_db()

async def get_lang(chat_id: int) -> str:
    return await storage.get_lang(chat_id)

def is_admin_status(member: ChatMember) -> bool:
    return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    member = await context.bot.get_chat_member(chat.id, user.id)
    return is_admin_status(member)

# ====== 欢迎 & 每日问好 ======
WELCOME_TEXT = (
    "✅ 欢迎加入！\n"
    "今天也要把事情做好，赚大钱 💰！\n\n"
    "功能清单：\n"
    "✅ 🌐 多语言支持(中/英/越)\n"
    "✅ ⏰ 群组专属时区\n"
    "✅ 🏢 自定义工作时间\n"
    "✅ 🚬 吸烟休息限制（⏱️ 超时10分钟提醒）\n"
    "✅ 🚽 如厕休息限制（⏱️ 超时20分钟提醒）\n"
    "✅ 📊 自定义报告时间\n"
    "✅ 📈 每日自动统计报表\n\n"
    "中文关键词：打卡/签到、抽烟/吸烟/cy、厕所/如厕/卫生间/wc、结束/cy0/wc0、排行榜/统计、设置时区/工作时间/日报、导出CSV\n"
)

def greeting_text():
    return (
        "⏰ 早上好！今天继续努力工作，冲业绩、赚大钱！💸\n\n"
        "快捷操作：\n"
        "• 发送「打卡/签到」即可打卡\n"
        "• 发送「抽烟」开始吸烟休息（10 分钟内结束，每日最多 10 次）\n"
        "• 发送「厕所/如厕」开始如厕休息（20 分钟内结束，每日最多 5 次）\n"
        "• 上下班前 5 分钟会自动提醒打卡\n"
    )

# ====== 计划任务调度 ======
def _next_weekly_occurrence(weekday: int, hh: int, mm: int, tz: pytz.BaseTzInfo) -> datetime:
    now_local = datetime.now(tz)
    # 本周目标时刻
    target = tz.localize(datetime(now_local.year, now_local.month, now_local.day, hh, mm, 0))
    # 调整到该周对应 weekday
    delta = (weekday - target.weekday()) % 7
    target = target + timedelta(days=delta)
    if target <= now_local:  # 已过，则下一周
        target += timedelta(days=7)
    return target.astimezone(timezone.utc)

async def schedule_chat_jobs(app: Application, chat_id: int):
    """为指定群安排：每日 7:50 ET 问好 + 每日上下班前 5 分钟提醒"""
    # 先清理旧任务
    for j in list(app.job_queue.jobs()):
        if j.name and (j.name.startswith(f"greet-{chat_id}-") or j.name.startswith(f"workrem-{chat_id}-")):
            j.schedule_removal()

    # 每天 7:50 ET 问好
    first = _next_weekly_occurrence(datetime.now(TZ_ET).weekday(), DAILY_GREETING_ET.hour, DAILY_GREETING_ET.minute, TZ_ET)
    app.job_queue.run_repeating(
        daily_greeting_job,
        interval=24*3600,
        first=first,
        name=f"greet-{chat_id}-daily",
        data={"chat_id": chat_id},
    )

    # 上下班前 5 分钟提醒
    for wd, (sh, sm, eh, em) in WORK_SCHEDULE.items():
        # 上班
        start_first = _next_weekly_occurrence(wd, sh, sm, TZ_ET) - timedelta(minutes=REMIND_BEFORE_MIN)
        app.job_queue.run_repeating(
            work_reminder_job, interval=7*24*3600, first=start_first,
            name=f"workrem-{chat_id}-start-{wd}",
            data={"chat_id": chat_id, "kind": "start", "wd": wd, "h": sh, "m": sm},
        )
        # 下班
        end_first = _next_weekly_occurrence(wd, eh, em, TZ_ET) - timedelta(minutes=REMIND_BEFORE_MIN)
        app.job_queue.run_repeating(
            work_reminder_job, interval=7*24*3600, first=end_first,
            name=f"workrem-{chat_id}-end-{wd}",
            data={"chat_id": chat_id, "kind": "end", "wd": wd, "h": eh, "m": em},
        )

async def daily_greeting_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    await context.bot.send_message(chat_id=chat_id, text=greeting_text())

async def work_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    chat_id = d["chat_id"]; kind = d["kind"]; h = d["h"]; m = d["m"]
    when = f"{h:02d}:{m:02d} ET"
    if kind == "start":
        txt = f"⏰ {when} 即将上班（还有 {REMIND_BEFORE_MIN} 分钟）— 记得『打卡』！"
    else:
        txt = f"⏰ {when} 即将下班（还有 {REMIND_BEFORE_MIN} 分钟）— 记得收尾并『打卡』！"
    await context.bot.send_message(chat_id=chat_id, text=txt)

# ====== 命令 ======
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    lang = await get_lang(chat.id)
    await update.message.reply_text(WELCOME_TEXT, reply_markup=kbd_checkin(lang))
    # 启动 /start 时为本群安排计划任务
    await schedule_chat_jobs(context.application, chat.id)

async def checkin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    lang = await get_lang(chat.id)
    await update.message.reply_text(t(lang, "checkin_ok", tz="ET"), reply_markup=kbd_checkin(lang))

# ====== 休息：限时 + 限次 + 超时罚站 ======
async def _day_bounds_et(ts_tz=TZ_ET):
    now_local = datetime.now(ts_tz)
    start_local = ts_tz.localize(datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0))
    end_local = start_local + timedelta(days=1) - timedelta(seconds=1)
    return int(start_local.timestamp()), int(end_local.timestamp())

async def _start_break(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    chat = update.effective_chat
    user = update.effective_user
    lang = await get_lang(chat.id)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    day_start, day_end = await _day_bounds_et()

    # 限次
    max_per_day = SMOKE_MAX_PER_DAY if kind == "smoke" else TOILET_MAX_PER_DAY
    cnt = await storage.count_breaks_between(chat.id, user.id, kind, day_start, day_end)
    if cnt >= max_per_day:
        await update.message.reply_text(f"⚠️ 今日{ '吸烟' if kind=='smoke' else '如厕' }次数已达上限（{max_per_day} 次）")
        return

    # 防止重复开始
    if await storage.has_active_break(chat.id, user.id, kind):
        await update.message.reply_text(f"已在{ '吸烟' if kind=='smoke' else '如厕' }中，先『结束』再开始")
        return

    await storage.start_break(chat.id, user.id, kind, now_ts)
    await update.message.reply_text(f"⏱️ 开始{ '吸烟' if kind=='smoke' else '如厕' }休息（计时已启动）")

    # 限时提醒 + 处罚
    limit_min = SMOKE_LIMIT_MIN if kind == "smoke" else TOILET_LIMIT_MIN
    context.job_queue.run_once(break_limit_job, when=datetime.now(timezone.utc) + timedelta(minutes=limit_min),
                               chat_id=chat.id, name=f"limit-{kind}-{chat.id}-{user.id}",
                               data={"chat_id": chat.id, "user_id": user.id, "kind": kind, "limit_min": limit_min})

async def _stop_break(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    chat = update.effective_chat
    user = update.effective_user
    now_ts = int(datetime.now(timezone.utc).timestamp())
    mins = await storage.stop_break(chat.id, user.id, kind, now_ts)
    if mins is None:
        await update.message.reply_text("当前没有正在进行的休息")
        return

    # 判断是否超时
    limit_min = SMOKE_LIMIT_MIN if kind == "smoke" else TOILET_LIMIT_MIN
    txt = f"✅ 结束{ '吸烟' if kind=='smoke' else '如厕' }休息，持续 {mins} 分钟"
    if mins > limit_min:
        txt += f"（已超过 {limit_min} 分钟，罚站 {PENALTY_MIN} 分钟）"
        # 处罚提示 + 结束提示
        await update.message.reply_text(f"🚫 现在开始罚站 {PENALTY_MIN} 分钟")
        context.job_queue.run_once(lambda c: c.bot.send_message(chat.id, "⏳ 罚站结束，注意专注工作！"),
                                   when=datetime.now(timezone.utc) + timedelta(minutes=PENALTY_MIN))
    await update.message.reply_text(txt)

async def break_limit_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]; user_id = job.data["user_id"]; kind = job.data["kind"]; limit_min = job.data["limit_min"]
    # 若还未结束，则提醒
    if await storage.has_active_break(chat_id, user_id, kind):
        kind_cn = "吸烟" if kind == "smoke" else "如厕"
        await context.bot.send_message(chat_id=chat_id, text=f"⏰ {kind_cn}已超过 {limit_min} 分钟，请尽快结束！超时将罚站 {PENALTY_MIN} 分钟")

# ====== 中文关键词触发 ======
def _set_args(context, args_list):
    try: context.args = args_list
    except Exception: pass

async def keyword_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text_raw = update.message.text.strip()
    text = text_raw.lower()

    # 打卡
    if any(w in text_raw for w in ["打卡", "签到"]) or any(w in text for w in ["check in", "checkin"]):
        await checkin_cmd(update, context); return

    # 休息：先 stop 再 start
    if any(w in text_raw for w in ["结束吸烟", "停止吸烟", "抽烟结束", "cy0"]) or "smoke stop" in text:
        await _stop_break(update, context, "smoke"); return
    if any(w in text_raw for w in ["结束如厕", "厕所结束", "如厕结束", "wc0"]) or "toilet stop" in text:
        await _stop_break(update, context, "toilet"); return
    if any(w in text_raw for w in ["抽烟", "吸烟", "cy"]) or "smoke" in text:
        await _start_break(update, context, "smoke"); return
    if any(w in text_raw for w in ["上厕所", "厕所", "如厕", "卫生间", "洗手间", "wc"]) or "toilet" in text or "wc" in text:
        await _start_break(update, context, "toilet"); return

    # 排行榜
    if any(w in text_raw for w in ["排行榜","排行","榜单"]) or "leaderboard" in text:
        m = re.search(r"(\d{1,3})\s*天", text_raw)
        if "全部" in text_raw or "all" in text: _set_args(context, ["all"])
        elif m: _set_args(context, [m.group(1)])
        else: _set_args(context, [])
        await leaderboard_cmd(update, context); return

    # 统计
    if any(w in text_raw for w in ["统计", "我的统计", "个人统计"]) or "stats" in text:
        await stats_cmd(update, context); return

    # 帮助
    if any(w in text_raw for w in ["帮助", "说明", "怎么用"]) or "help" in text:
        await start_cmd(update, context); return

# ====== 按钮回调（打卡） ======
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = query.message.chat
    lang = await get_lang(chat.id)
    await query.answer(cache_time=5)
    try:
        await query.edit_message_text(t(lang, "checkin_ok", tz="ET"), reply_markup=kbd_checkin(lang))
    except BadRequest as e:
        if "Message is not modified" not in str(e): raise

# ====== FastAPI Webhook ======
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

# ====== 启动 ======
async def main_async():
    global bot_app
    app = Application.builder().token(BOT_TOKEN).rate_limiter(AIORateLimiter()).build()
    bot_app = app

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_handler))

    if ENABLE_POLLING:
        await app.initialize(); await app.start(); await app.updater.start_polling(); await app.updater.idle()
    else:
        await app.initialize()
        await app.bot.set_webhook(url=f"{BASE_URL}/webhook/{WEBHOOK_SECRET}")
        await app.start()
        server = uvicorn.Server(uvicorn.Config(app_fastapi, host="0.0.0.0", port=PORT))
        await server.serve()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
