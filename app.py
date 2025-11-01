import os, time, logging, threading, requests
from pathlib import Path
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler

# ========= 환경변수 =========
TG_BOT_TOKEN    = os.getenv("TG_BOT_TOKEN")                      # 필수: BotFather 토큰
TARGET_CHAT_ID  = os.getenv("TARGET_CHAT_ID")                    # 선택: 1:1 또는 특정 채팅/채널 ID
ADMIN_ID        = int(os.getenv("ADMIN_ID", "0"))                # 선택: /reload 허용할 관리자 user_id
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "30"))        # 키워드 재로딩 주기(초), 기본 30

# 키워드 소스: 기본은 로컬 파일(./keywords.txt). Railway 배포 시 KEYWORDS_PATH="/data/keywords.txt" 권장
KEYWORDS_URL    = os.getenv("KEYWORDS_URL", "").strip()          # (미사용이면 공란) raw URL 사용 시 자동 반영
KEYWORDS_PATH   = os.getenv("KEYWORDS_PATH", "keywords.txt")     # 로컬 기본은 프로젝트 내 keywords.txt

# 기본 키워드(첫 로딩 실패 시 임시 사용)
DEFAULT_KWS     = [k.strip() for k in os.getenv("KEYWORDS", "급등,매수,RSI 30").split(",") if k.strip()]

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# ========= 키워드 로더 =========
class KeywordLoader:
    def __init__(self, url: str | None, path: str, refresh_sec: int = 30):
        self.url = url or None
        self.path = Path(path)
        self.refresh_sec = max(5, refresh_sec)
        self._keywords = DEFAULT_KWS[:]  # 초기값
        self._last_check = 0.0
        self._etag = None
        self._last_modified = None
        # 파일 모드라면 기본 파일 생성
        if not self.url:
            if not self.path.exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text("\n".join(self._keywords), encoding="utf-8")
                logging.info("Created default keywords file at %s", self.path)
        # 최초 로드
        self._try_reload(force=True)

    def get(self):
        # 주기적으로만 로드
        now = time.time()
        if now - self._last_check >= self.refresh_sec:
            self._try_reload()
        return self._keywords

    def _try_reload(self, force: bool = False):
        self._last_check = time.time()
        try:
            if self.url:
                self._reload_from_url(force)
            else:
                self._reload_from_file()
        except Exception as e:
            logging.error("Keyword reload failed: %s", e)

    def _parse_lines(self, text: str):
        # 줄 단위 파싱 (빈줄/주석 무시, 쉼표 분해 지원)
        lines = []
        for raw in text.splitlines():
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            if "," in s:
                parts = [p.strip() for p in s.split(",") if p.strip()]
                lines.extend(parts)
            else:
                lines.append(s)
        return lines

    def _reload_from_file(self):
        if not self.path.exists():
            return
        text = self.path.read_text(encoding="utf-8")
        kws = self._parse_lines(text)
        if kws:
            self._keywords = kws
            logging.info("Keywords loaded from file (%d items)", len(kws))

    def _reload_from_url(self, force: bool):
        headers = {}
        if self._etag:
            headers["If-None-Match"] = self._etag
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified
        if force:
            headers.pop("If-None-Match", None)
            headers.pop("If-Modified-Since", None)

        r = requests.get(self.url, headers=headers, timeout=10)
        if r.status_code == 304:
            return  # 변경 없음
        r.raise_for_status()
        text = r.text
        kws = self._parse_lines(text)
        if kws:
            self._keywords = kws
            self._etag = r.headers.get("ETag")
            self._last_modified = r.headers.get("Last-Modified")
            logging.info("Keywords loaded from URL (%d items)", len(kws))

loader = KeywordLoader(KEYWORDS_URL if KEYWORDS_URL else None, KEYWORDS_PATH, REFRESH_SECONDS)

# ========= 텔레그램 핸들러 =========
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text
    t = text.lower()
    kws = loader.get()
    if any(k.lower() in t for k in kws):
        room = update.effective_chat.title or update.effective_chat.username or "Telegram"
        alert = f"[{room}] 키워드 감지 ✅\n\n{text}"
        # 1) 감지된 그 방에: 알림 울리도록 disable_notification=False
        await update.message.reply_text(alert, disable_notification=False)
        # 2) 선택: 내 1:1(또는 특정 방)에도 동시에 전송
        if TARGET_CHAT_ID:
            try:
                await context.bot.send_message(
                    chat_id=int(TARGET_CHAT_ID),
                    text=alert,
                    disable_notification=False
                )
            except Exception as e:
                logging.error("TARGET_CHAT_ID send failed: %s", e)

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"chat_id: {update.effective_chat.id}\nuser_id: {update.effective_user.id}")

async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (선택) 수동 리로드: 관리자만
    if not ADMIN_ID or not update.effective_user or update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("권한이 없습니다.")
    loader._try_reload(force=True)
    await update.message.reply_text("키워드를 다시 불러왔습니다.")

def run_bot():
    # python-telegram-bot v21 + Flask 동시 실행을 위한 이벤트 루프 세팅
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    app_ = ApplicationBuilder().token(TG_BOT_TOKEN).build()
    app_.add_handler(CommandHandler("id", cmd_id))
    if ADMIN_ID:
        app_.add_handler(CommandHandler("reload", cmd_reload))
    app_.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app_.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)

# ========= 헬스체크 =========
@app.get("/")
def health():
    return "OK", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
# --- Health check endpoint for uptime robots ---
@app.route("/healthz")
def healthz():
    return "ok", 200

