import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# -------------------
# 기본 설정/로거
# -------------------
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")  # Render Environment에 설정
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")  # 선택(없으면 보낸 채팅으로 응답)

# -------------------
# 키워드 로딩
# -------------------
KEYWORDS_FILE = "keywords.txt"
keywords = set()

def load_keywords():
    global keywords
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            keywords = {line.strip() for line in f if line.strip()}
        logger.info("Keywords loaded (%d items)", len(keywords))
    except FileNotFoundError:
        logger.warning("keywords.txt not found; keywords set is empty")
        keywords = set()

load_keywords()

# -------------------
# 핸들러들
# -------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("봇이 준비되었습니다. /id 로 chat_id 확인 가능해요.")

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id if update.effective_chat else None
    user_id = update.effective_user.id if update.effective_user else None
    await update.message.reply_text(f"chat_id:{chat_id}, user_id:{user_id}")

async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 관리자 제한을 두고 싶다면 환경변수 ADMIN_ID를 쓰세요.
    admin_id = os.getenv("ADMIN_ID")
    if admin_id and str(update.effective_user.id) != str(admin_id):
        await update.message.reply_text("권한이 없습니다.")
        return
    load_keywords()
    await update.message.reply_text("키워드를 다시 불러왔습니다.")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    text = (update.message.text or "").strip()
    if not text:
        return

    # 키워드 감지
    hit = any(kw in text for kw in keywords) if keywords else False
    if hit:
        msg = f"[Telegram] 키워드 감지 ✅\n{text}"
        # TARGET_CHAT_ID가 있으면 거기로, 없으면 현재 대화창으로
        if TARGET_CHAT_ID:
            try:
                await context.bot.send_message(chat_id=int(TARGET_CHAT_ID), text=msg, disable_notification=False)
            except Exception as e:
                logger.error("send_message to TARGET_CHAT_ID failed: %s", e)
        else:
            await update.message.reply_text(msg)

# -------------------
# Telegram Bot (메인 스레드에서 실행)
# -------------------
async def run_bot():
    if not TG_BOT_TOKEN:
        logger.error("TG_BOT_TOKEN not set.")
        return

    app = ApplicationBuilder().token(TG_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("reload", cmd_reload))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_text))

    # 메인 스레드에서 polling 실행 → 신호 처리 문제 없음
    await app.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

# -------------------
# Flask (보조 스레드에서 실행)
# -------------------
flask_app = Flask(__name__)

@flask_app.get("/")
def root():
    return "OK", 200

@flask_app.get("/healthz")
def healthz():
    return "ok", 200

def run_flask():
    port = int(os.getenv("PORT", "8080"))
    # Render 무료 플랜에서 충분
    flask_app.run(host="0.0.0.0", port=port, threaded=True)

# -------------------
# 엔트리포인트
# -------------------
if __name__ == "__main__":
    # Flask를 보조 스레드로 올리고
    threading.Thread(target=run_flask, daemon=True).start()

    # 봇은 메인 스레드에서 실행 (신호 처리 OK)
    import asyncio
    asyncio.run(run_bot())
