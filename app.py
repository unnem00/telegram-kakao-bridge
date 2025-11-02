import os
import asyncio
import logging
import threading
from typing import List

from flask import Flask

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)

# ---------- 설정 ----------
TOKEN = os.getenv("TG_BOT_TOKEN")  # Render > Environment에 설정한 토큰
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # 선택(관리자만 /reload 허용하고 싶을 때)
KEYWORDS_FILE = os.getenv("KEYWORDS_FILE", "keywords.txt")
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID", "0"))  # 선택(특정 채팅으로만 알림)

# ---------- 로깅 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("bridge")

# ---------- 키워드 ----------
_keywords: List[str] = []

def load_keywords() -> List[str]:
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except FileNotFoundError:
        logger.warning("keywords.txt not found. Proceeding with empty list.")
        return []

# ---------- 텔레그램 핸들러 ----------
async def on_start(app):
    # 폴링 전에 혹시 남아있을 웹훅을 제거
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted.")
    except Exception as e:
        logger.warning("delete_webhook failed: %s", e)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("키워드 감지 봇이 준비되었습니다. ✅")

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"chat_id: {update.effective_chat.id}\nuser_id: {update.effective_user.id}"
    )

async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("관리자만 사용할 수 있습니다.")
        return
    global _keywords
    _keywords = load_keywords()
    await update.message.reply_text("키워드를 다시 불러왔습니다. ✅")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.lower()

    if not _keywords:
        return

    hit = next((kw for kw in _keywords if kw.lower() in text), None)
    if not hit:
        return

    msg = f"[Telegram] 키워드 감지 ✅\n\n키워드: {hit}\n본문: {update.message.text}"

    # 1) 특정 방으로만 전송하고 싶으면 TARGET_CHAT_ID 사용
    if TARGET_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=TARGET_CHAT_ID, text=msg, disable_notification=False)
        except Exception as e:
            logger.error("send_message failed: %s", e)
    else:
        # 2) 아니면 현재 채팅에 회신
        await update.message.reply_text(msg)

# ---------- Flask(헬스체크) ----------
flask_app = Flask(__name__)

@flask_app.get("/healthz")
def healthz():
    return "ok", 200

@flask_app.get("/")
def root():
    return "OK", 200

# ---------- 봇 실행(별도 스레드/별도 루프) ----------
def bot_worker():
    """
    python-telegram-bot v21은 asyncio 기반입니다.
    Flask와 충돌하지 않도록 별도 스레드 + 별도 이벤트 루프에서 run_polling을 실행합니다.
    """
    asyncio.set_event_loop(asyncio.new_event_loop())
    loop = asyncio.get_event_loop()

    global _keywords
    _keywords = load_keywords()

    application = ApplicationBuilder().token(TOKEN).post_init(on_start).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("id", cmd_id))
    application.add_handler(CommandHandler("reload", cmd_reload))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # non-main thread에서 신호 핸들러 등록 금지
    # close_loop=False로 두고 스레드의 이벤트 루프 수명은 우리가 관리
    loop.run_until_complete(
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            stop_signals=None,
            close_loop=False,
            drop_pending_updates=True,
        )
    )

def main():
    if not TOKEN:
        raise RuntimeError("환경변수 TG_BOT_TOKEN 이(가) 설정되어 있지 않습니다.")

    # 봇 스레드 시작
    t = threading.Thread(target=bot_worker, name="tg-bot", daemon=True)
    t.start()
    logger.info("Bot thread started.")

    # Render가 제공한 PORT 사용
    port = int(os.getenv("PORT", "8080"))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
