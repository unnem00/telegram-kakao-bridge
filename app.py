# app.py  — Render(Flask + python-telegram-bot v21) 동시 실행용
# - /healthz 라우트를 app.run()보다 "위"에 둠 (404 해결)
# - 시작 시 delete_webhook 실행 (getUpdates 충돌 예방)
# - 에러 핸들러 등록 (No error handlers… 경고 예방)
# - 환경변수 TG_BOT_TOKEN 사용 (없으면 TELEGRAM_TOKEN 백업)

import os
import threading
import asyncio
import logging
from flask import Flask

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)

# ---------------------------
# Flask 앱 & 헬스체크 (항상 위쪽에!)
# ---------------------------
app = Flask(__name__)

@app.get("/")
def root():
    return "OK", 200

@app.get("/healthz")
def healthz():
    return "ok", 200


# ---------------------------
# 텔레그램 봇 핸들러
# ---------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("봇이 정상 동작 중입니다. (/start)")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 필요하면 키워드 로직으로 교체
    await update.message.reply_text(f"에코: {update.message.text}")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Telegram handler error", exc_info=context.error)

# ---------------------------
# 텔레그램 봇 실행 (long-polling)
# ---------------------------
async def bot_main():
    token = os.getenv("TG_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    if not token:
        logging.error("환경변수 TG_BOT_TOKEN(또는 TELEGRAM_TOKEN)이 없습니다.")
        return

    application = ApplicationBuilder().token(token).build()

    # 충돌 방지: 웹훅 제거 (getUpdates 사용)
    try:
        await application.bot.delete_webhook(drop_pending_updates=False)
        logging.info("delete_webhook 완료")
    except Exception:
        logging.exception("delete_webhook 실패 (무시 가능)")

    # 핸들러 등록
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(on_error)

    # run_polling이 내부에서 start/idle/stop까지 처리
    await application.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=False)

def start_bot_thread():
    # 별도 스레드에서 이벤트 루프 생성
    asyncio.run(bot_main())

# ---------------------------
# 엔트리포인트
# ---------------------------
if __name__ == "__main__":
    # 텔레그램 봇을 백그라운드 스레드로 실행
    threading.Thread(target=start_bot_thread, daemon=True).start()

    # Flask 실행
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
