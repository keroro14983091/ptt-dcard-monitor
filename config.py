import os
import sys
import io
import logging
from dataclasses import dataclass
from typing import List, Set
from dotenv import load_dotenv

# 強制 Windows 終端機標準輸出使用 UTF-8 編碼，避免 Emoji 導致 cp950 編碼崩潰
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 載入 .env 檔案
load_dotenv(override=True)


@dataclass
class Config:
    telegram_bot_token: str
    telegram_chat_ids: List[str]
    allowed_user_ids: Set[int]
    ptt_boards: List[str]
    dcard_boards: List[str]
    default_keywords: List[str]
    ptt_min_push_count: int
    dcard_min_like_count: int
    poll_interval_min_sec: int
    poll_interval_max_sec: int
    db_path: str
    log_level: str
    ptt_crawl_pages: int = 5
    dcard_cookie: str = ""
    dcard_proxy_url: str = ""
    telegram_proxy_url: str = ""
    port: int = 10000
    enable_web_server: bool = True

    @classmethod
    def load(cls) -> "Config":
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id_raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        if not bot_token or bot_token == "your_telegram_bot_token_here":
            print("[ERROR] 請在 .env 檔案中填寫正確的 TELEGRAM_BOT_TOKEN！", file=sys.stderr)
            sys.exit(1)

        if not chat_id_raw or chat_id_raw == "your_chat_id_here":
            print("[ERROR] 請在 .env 檔案中填寫正確的 TELEGRAM_CHAT_ID！", file=sys.stderr)
            sys.exit(1)

        chat_ids = [cid.strip() for cid in chat_id_raw.split(",") if cid.strip()]
        allowed_user_ids = set()
        for cid in chat_ids:
            try:
                allowed_user_ids.add(int(cid))
            except ValueError:
                pass

        ptt_boards_raw = os.getenv("PTT_BOARDS", "Stock,Lifeismoney,Gossiping")
        ptt_boards = [b.strip() for b in ptt_boards_raw.split(",") if b.strip()]

        dcard_boards_raw = os.getenv("DCARD_BOARDS", "")
        dcard_boards = [b.strip() for b in dcard_boards_raw.split(",") if b.strip()]

        default_keywords_raw = os.getenv("DEFAULT_KEYWORDS", "台積電,美股,優惠,買一送一,分紅")
        default_keywords = [k.strip() for k in default_keywords_raw.split(",") if k.strip()]

        ptt_min_push = int(os.getenv("PTT_MIN_PUSH_COUNT", "50"))
        dcard_min_like = int(os.getenv("DCARD_MIN_LIKE_COUNT", "50"))

        ptt_crawl_pages = int(os.getenv("PTT_CRAWL_PAGES", "5"))

        poll_min = int(os.getenv("POLL_INTERVAL_MIN_SEC", "30"))
        poll_max = int(os.getenv("POLL_INTERVAL_MAX_SEC", "60"))

        db_path = os.getenv("DB_PATH", "./data/monitor.db").strip()
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()

        dcard_cookie = os.getenv("DCARD_COOKIE", "").strip()
        dcard_proxy_url = os.getenv("DCARD_PROXY_URL", "").strip()
        telegram_proxy_url = os.getenv("TELEGRAM_PROXY_URL", "").strip()

        port = int(os.getenv("PORT", "10000"))
        enable_web_server = os.getenv("ENABLE_WEB_SERVER", "true").lower() in ("true", "1", "yes")

        return cls(
            telegram_bot_token=bot_token,
            telegram_chat_ids=chat_ids,
            allowed_user_ids=allowed_user_ids,
            ptt_boards=ptt_boards,
            dcard_boards=dcard_boards,
            default_keywords=default_keywords,
            ptt_min_push_count=ptt_min_push,
            dcard_min_like_count=dcard_min_like,
            ptt_crawl_pages=ptt_crawl_pages,
            poll_interval_min_sec=poll_min,
            poll_interval_max_sec=poll_max,
            db_path=db_path,
            log_level=log_level,
            dcard_cookie=dcard_cookie,
            dcard_proxy_url=dcard_proxy_url,
            telegram_proxy_url=telegram_proxy_url,
            port=port,
            enable_web_server=enable_web_server,
        )


def setup_logger(name: str = "monitor", level_name: str = "INFO") -> logging.Logger:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


# 全域實例
config = Config.load()
logger = setup_logger("MonitorApp", config.log_level)
