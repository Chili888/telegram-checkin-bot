import asyncio, os, logging
from datetime import datetime, timedelta, timezone
import pytz, uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberAdministrator, ChatMemberOwner
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, AIORateLimiter, MessageHandler, filters
from telegram.error import BadRequest

from . import storage
from .utils import t

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = os.getenv("BASE_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET","dev-secret")
ENABLE_POLLING = os.getenv("ENABLE_POLLING","false").lower()=="true"
PORT = int(os.getenv("PORT","8000"))

def is_admin(member): return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))

def kbd(lang): return InlineKeyboardMarkup([[InlineKeyboardButton(t(lang,"btn_checkin"), callback_data="checkin")]])

async def ensure(): await storage.init_db()
async def get_lang(chat_id:int)->str: return await storage.get_lang(chat_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure()
    lang = await get_lang(update.effective_chat.id)
    await update.message.reply_text("已启用自定义关键词触发。\n添加：/addtrigger 关键词 动作\n查看：/listtriggers\n删除：/deltrigger 关键词", reply_markup=kbd(lang))

async def check_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat; user = update.effective_user
    m = await context.bot.get_chat_member(chat.id, user.id)
    return is_admin(m)

# basic actions
async def action_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_lang(update.effective_chat.id)
    await update.message.reply_text(t(lang,"checkin_ok", tz="TZ"), reply_markup=kbd(lang))

async def action_smoke_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Smoking break started (demo)")

async def action_smoke_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Smoking break stopped (demo)")

async def action_toilet_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Toilet break started (demo)")

async def action_toilet_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Toilet break stopped (demo)")

ACTION_MAP = {
    "checkin": action_checkin,
    "smoke_start": action_smoke_start,
    "smoke_stop": action_smoke_stop,
    "toilet_start": action_toilet_start,
    "toilet_stop": action_toilet_stop,
}

# commands for triggers
async def addtrigger_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure()
    chat = update.effective_chat; lang = await get_lang(chat.id)
    if not await check_admin(update, context):
        await update.message.reply_text(t(lang,"admin_only")); return
    if len(context.args) < 2:
        await update.message.reply_text(t(lang,"usage_add")); return
    kw = context.args[0].strip().lower()
    act = context.args[1].strip().lower()
    if act not in ACTION_MAP:
        await update.message.reply_text(t(lang,"usage_add")); return
    ok = await storage.add_trigger(chat.id, kw, act)
    if ok: await update.message.reply_text(t(lang,"trigger_added", kw=kw, act=act))
    else:  await update.message.reply_text(t(lang,"trigger_exists", kw=kw))

async def listtriggers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure()
    chat = update.effective_chat; lang = await get_lang(chat.id)
    rows = await storage.list_triggers(chat.id)
    if not rows:
        await update.message.reply_text(t(lang,"no_triggers")); return
    lines = [t(lang,"triggers_header", n=len(rows))] + [t(lang,"triggers_item", kw=k, act=a) for (k,a) in rows]
    await update.message.reply_text("\n".join(lines))

async def deltrigger_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure()
    chat = update.effective_chat; lang = await get_lang(chat.id)
    if not await check_admin(update, context):
        await update.message.reply_text(t(lang,"admin_only")); return
    if not context.args:
        await update.message.reply_text(t(lang,"usage_del")); return
    kw = context.args[0].strip().lower()
    ok = await storage.del_trigger(chat.id, kw)
    if ok: await update.message.reply_text(t(lang,"trigger_deleted", kw=kw))
    else:  await update.message.reply_text(t(lang,"trigger_not_found", kw=kw))

# keyword dispatcher
async def keyword_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip().lower()
    chat_id = update.effective_chat.id
    rows = await storage.list_triggers(chat_id)
    for kw, act in rows:
        if kw in text:
            handler = ACTION_MAP.get(act)
            if handler:
                await handler(update, context)
                break

# FastAPI webhook
app_fastapi = FastAPI()
bot_app=None

@app_fastapi.get("/healthz")
async def healthz(): return PlainTextResponse("ok")

@app_fastapi.post(f"/webhook/{WEBHOOK_SECRET}")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return PlainTextResponse("ok")

async def main_async():
    global bot_app
    app = Application.builder().token(BOT_TOKEN).rate_limiter(AIORateLimiter()).build()
    bot_app = app
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addtrigger", addtrigger_cmd))
    app.add_handler(CommandHandler("listtriggers", listtriggers_cmd))
    app.add_handler(CommandHandler("deltrigger", deltrigger_cmd))
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

if __name__=="__main__": main()
