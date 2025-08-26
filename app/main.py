import asyncio, os, logging, re
from datetime import datetime, timezone
import pytz, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    AIORateLimiter,
    MessageHandler,
    filters,
)
from telegram.error import BadRequest

from . import storage
from .utils import t

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "dev-secret")
ENABLE_POLLING = os.getenv("ENABLE_POLLING", "false").lower() == "true"
PORT = int(os.getenv("PORT", "8000"))

# --- helpers ---
def kbd_checkin(lang):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_checkin"), callback_data="checkin")]])

async def ensure_db():
    await storage.init_db()

async def get_lang_for_chat(chat_id: int) -> str:
    return await storage.get_lang(chat_id)
# --- commands ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    lang = await get_lang_for_chat(update.effective_chat.id)
    await update.message.reply_text(
        "欢迎使用群组打卡机器人 ✅\n"
        "支持斜杠命令和中文关键词触发（需在 BotFather /setprivacy → Disable）",
        reply_markup=kbd_checkin(lang),
    )

async def checkin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    user = update.effective_user
    lang = await get_lang_for_chat(chat.id)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    await update.message.reply_text(
        t(lang, "checkin_ok", tz="群时区"), reply_markup=kbd_checkin(lang)
    )
    logging.info(f"[CHECKIN] {user.full_name} in {chat.title} at {now}")

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    lang = await get_lang_for_chat(chat.id)
    days = "7"
    if context.args:
        days = context.args[0]
    await update.message.reply_text(f"📊 {days} 天排行榜（示例，待实现存储逻辑）")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    chat = update.effective_chat
    lang = await get_lang_for_chat(chat.id)
    await update.message.reply_text("📈 个人统计（示例，待实现）")
# --- breaks & reminders ---
async def _start_break(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    user = update.effective_user
    await update.message.reply_text(f"⏱️ {kind} break started by {user.full_name}（示例逻辑）")

async def _stop_break(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    user = update.effective_user
    await update.message.reply_text(f"✅ {kind} break stopped by {user.full_name}（示例逻辑）")

# --- keyword trigger (中文关键词 → 对应命令) ---
def _set_args(context, args_list):
    try:
        context.args = args_list
    except Exception:
        pass

async def keyword_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text_raw = update.message.text.strip()
    text = text_raw.lower()
    chat = update.effective_chat

    # 打卡
    if any(w in text_raw for w in ["打卡", "签到"]) or any(w in text for w in ["check in", "checkin"]):
        await checkin_cmd(update, context); return

    # 吸烟 / 如厕 —— 先匹配结束，再匹配开始
    if any(w in text_raw for w in ["结束吸烟", "停止吸烟", "抽烟结束"]) or "smoke stop" in text:
        await _stop_break(update, context, "smoke"); return
    if any(w in text_raw for w in ["结束如厕", "厕所结束", "如厕结束"]) or "toilet stop" in text:
        await _stop_break(update, context, "toilet"); return
    if any(w in text_raw for w in ["抽烟", "吸烟"]) or "smoke" in text:
        await _start_break(update, context, "smoke"); return
    if any(w in text_raw for w in ["上厕所", "厕所", "如厕", "卫生间"]) or "toilet" in text or "wc" in text:
        await _start_break(update, context, "toilet"); return
    # 排行榜
    if any(w in text_raw for w in ["排行榜", "排行", "榜单"]) or "leaderboard" in text:
        days = None
        m = re.search(r"(\d{1,3})天", text_raw)
        if m: days = m.group(1)
        if "全部" in text_raw or "all" in text:
            _set_args(context, ["all"])
        elif days:
            _set_args(context, [str(days)])
        else:
            _set_args(context, [])
        await leaderboard_cmd(update, context); return

    # 个人统计
    if any(w in text_raw for w in ["统计", "我的统计", "个人统计"]) or "stats" in text:
        await stats_cmd(update, context); return

    # 导出（管理员）
    if any(w in text_raw for w in ["导出", "导出csv", "导出表"]) or "export" in text:
        try:
            await export_cmd(update, context); return
        except Exception:
            pass

    # 帮助
    if any(w in text_raw for w in ["帮助", "说明", "怎么用"]) or "help" in text:
        await start_cmd(update, context); return

# --- export ---
async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text("📂 导出 CSV（示例逻辑，待补充存储实现）")

# --- button callback ---
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_db()
    query = update.callback_query
    chat = query.message.chat
    lang = await get_lang_for_chat(chat.id)
    await query.answer(cache_time=5)
    try:
        await query.edit_message_text(
            t(lang, "checkin_ok", tz="群时区"),
            reply_markup=kbd_checkin(lang),
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise
# --- FastAPI webhook server ---
app_fastapi = FastAPI()
bot_app = None

@app_fastapi.get("/healthz")
async def healthz():
    return PlainTextResponse("ok")

@app_fastapi.post(f"/webhook/{WEBHOOK_SECRET}")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return PlainTextResponse("ok")

# --- main ---
async def main_async():
    global bot_app
    application = Application.builder().token(BOT_TOKEN).rate_limiter(AIORateLimiter()).build()
    bot_app = application

    # commands
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("checkin", checkin_cmd))
    application.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("export", export_cmd))
    # keyword handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_handler))
    # button
    application.add_handler(CallbackQueryHandler(on_button))

    if ENABLE_POLLING:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        await application.updater.idle()
    else:
        await application.initialize()
        await application.bot.set_webhook(url=f"{BASE_URL}/webhook/{WEBHOOK_SECRET}")
        await application.start()
        server = uvicorn.Server(uvicorn.Config(app_fastapi, host="0.0.0.0", port=PORT))
        await server.serve()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
