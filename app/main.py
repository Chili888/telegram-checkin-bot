import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone, time
from typing import Optional

import pytz
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, ChatMemberAdministrator, ChatMemberOwner
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, AIORateLimiter

from . import storage
from .utils import t

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("checkin-bot-pro")

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "dev-secret")
ENABLE_POLLING = os.getenv("ENABLE_POLLING", "false").lower() == "true"
TZ_DEFAULT = os.getenv("TZ_DEFAULT", "UTC")
PORT = int(os.getenv("PORT", "8000"))

if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN env")

def is_admin_status(member: ChatMember) -> bool:
    return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    member = await context.bot.get_chat_member(chat.id, user.id)
    return is_admin_status(member)

def kbd_checkin(lang: str):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_checkin"), callback_data="checkin")]])

async def ensure_db():
    await storage.init_db()

async def get_lang_for_chat(chat_id: int) -> str:
    lang = await storage.get_lang(chat_id)
    return lang or "zh"

# --- helper: day window in chat tz ---
async def day_bounds(chat_id: int) -> tuple[int,int,str]:
    tzname = await storage.get_tz(chat_id)
    try:
        tz = pytz.timezone(tzname)
    except Exception:
        tz = pytz.timezone("UTC")
        tzname = "UTC"
    now_local = datetime.now(tz)
    start_local = tz.localize(datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0))
    end_local = start_local + timedelta(days=1) - timedelta(seconds=1)
    return int(start_local.timestamp()), int(end_local.timestamp()), tzname

# --- commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    lang = await get_lang_for_chat(chat.id)
    await update.message.reply_text(
        t(lang, "hello") + "\n\n" + t(lang, "help"),
        reply_markup=kbd_checkin(lang)
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    if not context.args:
        await update.message.reply_text("Usage: /lang zh|en|vi")
        return
    lang = context.args[0].lower()
    if lang not in ("zh", "en", "vi"):
        await update.message.reply_text("Usage: /lang zh|en|vi")
        return
    await storage.set_lang(chat.id, lang)
    await update.message.reply_text(t(lang, "lang_ok", lang=lang))

async def settz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    lang = await get_lang_for_chat(chat.id)
    if not await is_admin(update, context):
        await update.message.reply_text(t(lang, "settz_admin"))
        return
    if not context.args:
        await update.message.reply_text("Usage: /settz Asia/Phnom_Penh")
        return
    tz = context.args[0]
    try:
        _ = pytz.timezone(tz)
    except Exception:
        await update.message.reply_text(t(lang, "invalid_tz"))
        return
    await storage.set_tz(chat.id, tz)
    await update.message.reply_text(t(lang, "settz_ok", tz=tz))

async def workhours_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    lang = await get_lang_for_chat(chat.id)
    if not await is_admin(update, context):
        await update.message.reply_text(t(lang, "admin_only"))
        return
    if not context.args or "-" not in context.args[0]:
        await update.message.reply_text("Usage: /workhours HH:MM-HH:MM")
        return
    hours = context.args[0]
    await storage.set_workhours(chat.id, *hours.split("-", 1))
    await update.message.reply_text(t(lang, "work_set", hours=hours))

async def setreport_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    lang = await get_lang_for_chat(chat.id)
    if not await is_admin(update, context):
        await update.message.reply_text(t(lang, "admin_only"))
        return
    if not context.args:
        await update.message.reply_text("Usage: /setreport HH:MM")
        return
    hhmm = context.args[0]
    await storage.set_report_time(chat.id, hhmm)
    await update.message.reply_text(t(lang, "report_set", time=hhmm))
    # re-schedule daily report for this chat
    await schedule_daily_report_for_chat(context.application, chat.id)

async def checkin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    user = update.effective_user
    lang = await get_lang_for_chat(chat.id)
    start_ts, end_ts, tzname = await day_bounds(chat.id)
    already = await storage.has_checkin_between(chat.id, user.id, start_ts, end_ts)
    if already:
        await update.message.reply_text(t(lang, "checked_today", tz=tzname), reply_markup=kbd_checkin(lang))
        return
    now_ts = int(datetime.now(timezone.utc).timestamp())
    await storage.add_checkin(chat.id, user.id, user.username, user.full_name, now_ts)
    await update.message.reply_text(t(lang, "checkin_ok", tz=tzname), reply_markup=kbd_checkin(lang))

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    query = update.callback_query
    chat = query.message.chat
    user = query.from_user
    lang = await get_lang_for_chat(chat.id)
    await query.answer()
    start_ts, end_ts, tzname = await day_bounds(chat.id)
    already = await storage.has_checkin_between(chat.id, user.id, start_ts, end_ts)
    if already:
        await query.edit_message_text(t(lang, "checked_today", tz=tzname), reply_markup=kbd_checkin(lang))
        return
    now_ts = int(datetime.now(timezone.utc).timestamp())
    await storage.add_checkin(chat.id, user.id, user.username, user.full_name, now_ts)
    await query.edit_message_text(t(lang, "checkin_ok", tz=tzname), reply_markup=kbd_checkin(lang))

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    lang = await get_lang_for_chat(chat.id)
    days = 7
    if context.args:
        arg = context.args[0].lower()
        if arg == "all":
            days = -1
        elif arg.isdigit():
            days = max(1, int(arg))
    since_ts = None if days == -1 else int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    rows = await storage.leaderboard(chat.id, since_ts)
    if not rows:
        await update.message.reply_text(t(lang, "no_data"))
        return
    title = t(lang, "lb_title_days", days=days) if since_ts is not None else t(lang, "lb_title_all")
    lines = [title] + [f"{i}. {name} — {cnt}" for i, (_, name, cnt) in enumerate(rows, 1)]
    await update.message.reply_text("\n".join(lines))

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    lang = await get_lang_for_chat(chat.id)
    target = update.effective_user
    total, last_ts = await storage.user_stats(chat.id, target.id)
    if total == 0:
        await update.message.reply_text(t(lang, "no_data"))
        return
    last_str = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if last_ts else "N/A"
    await update.message.reply_text(f"{target.full_name} {total} / {last_str}")

# --- breaks & reminders ---
REMINDER_MINUTES = 2

async def _start_break(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    await ensure_db()
    chat = update.effective_chat
    user = update.effective_user
    lang = await get_lang_for_chat(chat.id)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    await storage.start_break(chat.id, user.id, kind, now_ts)
    await update.message.reply_text(t(lang, f"{kind}_started"))
    # schedule reminder in 2 minutes
    when = datetime.now(timezone.utc) + timedelta(minutes=REMINDER_MINUTES)
    context.job_queue.run_once(break_reminder_job, when=when, chat_id=chat.id, name=f"brk-{kind}-{chat.id}-{user.id}", data={"user_id": user.id, "kind": kind})

async def _stop_break(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    await ensure_db()
    chat = update.effective_chat
    user = update.effective_user
    lang = await get_lang_for_chat(chat.id)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    mins = await storage.stop_break(chat.id, user.id, kind, now_ts)
    if mins is None:
        await update.message.reply_text(t(lang, "unknown_cmd"))
        return
    await update.message.reply_text(t(lang, f"{kind}_stopped", mins=mins))

async def smoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /smoke start|stop")
        return
    if context.args[0].lower() == "start":
        await _start_break(update, context, "smoke")
    else:
        await _stop_break(update, context, "smoke")

async def toilet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /toilet start|stop")
        return
    if context.args[0].lower() == "start":
        await _start_break(update, context, "toilet")
    else:
        await _stop_break(update, context, "toilet")

async def break_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data or {}
    chat_id = job.chat_id
    kind = data.get("kind", "break")
    user_id = data.get("user_id")
    lang = await storage.get_lang(chat_id)
    # 直接 @ 用户提醒（为了兼容，不强行 @username）
    await context.bot.send_message(chat_id=chat_id, text=t(lang, "break_reminder", kind=("吸烟" if kind=="smoke" else "如厕") if lang=="zh" else kind))

# --- daily report scheduling ---
async def schedule_daily_report_for_chat(app: Application, chat_id: int):
    tzname = await storage.get_tz(chat_id)
    report_hhmm = await storage.get_report_time(chat_id)
    if not report_hhmm:
        return
    # remove old jobs for this chat
    for j in list(app.job_queue.jobs()):
        if j.name and j.name.startswith(f"report-{chat_id}-"):
            j.schedule_removal()
    # schedule next occurrence in chat tz
    try:
        tz = pytz.timezone(tzname)
    except Exception:
        tz = pytz.timezone("UTC")
        tzname = "UTC"
    hh, mm = [int(x) for x in report_hhmm.split(":")]
    now_local = datetime.now(tz)
    run_local = tz.localize(datetime(now_local.year, now_local.month, now_local.day, hh, mm, 0))
    if run_local <= now_local:
        run_local += timedelta(days=1)
    run_utc = run_local.astimezone(timezone.utc)
    app.job_queue.run_repeating(daily_report_job, interval=24*3600, first=run_utc, name=f"report-{chat_id}-{report_hhmm}", data={"chat_id": chat_id})

async def daily_report_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    lang = await storage.get_lang(chat_id)
    tzname = await storage.get_tz(chat_id)
    try:
        tz = pytz.timezone(tzname)
    except Exception:
        tz = pytz.timezone("UTC")
        tzname = "UTC"
    now_local = datetime.now(tz)
    start_local = tz.localize(datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0))
    end_local = start_local + timedelta(days=1) - timedelta(seconds=1)
    start_ts, end_ts = int(start_local.timestamp()), int(end_local.timestamp())
    c, s_cnt, s_min, t_cnt, t_min, top = await storage.summarize_today(chat_id, start_ts, end_ts)
    top_text = "\n".join([f"- {name}: {cnt}" for (name, cnt) in top]) if top else t(lang, "no_data")
    title = t(lang, "report_title", date=start_local.strftime("%Y-%m-%d"), tz=tzname)
    sections = t(lang, "report_sections", checkins=c, smoke_cnt=s_cnt, smoke_min=int(s_min), toilet_cnt=t_cnt, toilet_min=int(t_min), top=top_text)
    await context.bot.send_message(chat_id=chat_id, text=f"{title}\n\n{sections}")

# --- webhook server ---
app_fastapi = FastAPI()
bot_app: Optional[Application] = None

@app_fastapi.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")

@app_fastapi.post(f"/webhook/{WEBHOOK_SECRET}")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return PlainTextResponse("ok")

async def main_async():
    global bot_app
    await ensure_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .rate_limiter(AIORateLimiter())
        .build()
    )
    bot_app = application

    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler("lang", lang_cmd))
    application.add_handler(CommandHandler("settz", settz_cmd))
    application.add_handler(CommandHandler("workhours", workhours_cmd))
    application.add_handler(CommandHandler("setreport", setreport_cmd))
    application.add_handler(CommandHandler("checkin", checkin_cmd))
    application.add_handler(CallbackQueryHandler(on_button))
    application.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("smoke", smoke_cmd))
    application.add_handler(CommandHandler("toilet", toilet_cmd))
    application.add_handler(CommandHandler("export", lambda u, c: u.message.reply_text("Use older build to export CSV")))  # simplified here

    # schedule existing reports for known chats?
    # (lazy: upon /setreport we schedule; alternatively, you can persist chat ids and schedule on startup)

    if ENABLE_POLLING:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await application.updater.idle()
    else:
        if not BASE_URL:
            raise RuntimeError("Missing BASE_URL for webhook mode")
        await application.initialize()
        await application.bot.set_webhook(url=f"{BASE_URL}/webhook/{WEBHOOK_SECRET}", allowed_updates=Update.ALL_TYPES)
        await application.start()
        config = uvicorn.Config(app_fastapi, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

def main():
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()
