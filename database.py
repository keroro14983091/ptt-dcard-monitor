import os
import sqlite3
import logging
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Generator, Tuple
from datetime import datetime, timedelta
from config import config, logger


def canonicalize_board_name(board: str) -> str:
    """標準化常見 PTT 看板大小寫，其餘保持原樣"""
    b = board.strip()
    mapping = {
        "stock": "Stock",
        "lifeismoney": "Lifeismoney",
        "gossiping": "Gossiping",
        "c_chat": "C_Chat",
        "tech_job": "Tech_Job",
        "mobilecomm": "MobileComm",
        "nba": "NBA",
        "car": "car",
        "pc_shopping": "PC_Shopping",
        "e-shopping": "e-shopping",
        "hardwaredeal": "HardwareSale",
    }
    return mapping.get(b.lower(), b)


@contextmanager
def get_db_cursor(db_path: Optional[str] = None) -> Generator[sqlite3.Cursor, None, None]:
    """獲取 SQLite 連線與 Cursor 的 contextmanager，確保用畢自動關閉連線"""
    path = db_path or config.db_path
    db_dir = os.path.dirname(path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """
    初始化 SQLite 資料表：
    1. board_keywords (board TEXT, keyword TEXT, created_at TIMESTAMP, PRIMARY KEY(board, keyword))
    2. board_settings (board TEXT PRIMARY KEY, min_push_count INTEGER DEFAULT 0, created_at TIMESTAMP)
    3. system_settings (key TEXT PRIMARY KEY, value TEXT)
    4. notified_posts (platform, post_id, title, url, board, reason, created_at)
    5. keywords (舊版相容)
    """
    with get_db_cursor(db_path) as cursor:
        # 1. 建立 board_keywords 資料表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS board_keywords (
                board TEXT NOT NULL,
                keyword TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (board, keyword)
            );
            """
        )

        # 1.1 建立 board_exclude_keywords 排除關鍵字資料表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS board_exclude_keywords (
                board TEXT NOT NULL,
                keyword TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (board, keyword)
            );
            """
        )

        # 2. 建立 board_settings 資料表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS board_settings (
                board TEXT PRIMARY KEY,
                min_push_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # 3. 建立 system_settings 資料表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )

        # 4. 建立 notified_posts 資料表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS notified_posts (
                platform TEXT NOT NULL,
                post_id TEXT NOT NULL,
                title TEXT,
                url TEXT,
                board TEXT,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (platform, post_id)
            );
            """
        )

        # 5. 舊版相容 keywords
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS keywords (
                keyword TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # 建立快速查詢索引
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notified_lookup 
            ON notified_posts (platform, post_id);
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_board_kw_lookup 
            ON board_keywords (board);
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_board_exkw_lookup 
            ON board_exclude_keywords (board);
            """
        )

        # 6. 初始化預設看板與規則 (若 board_keywords 與 board_settings 皆為空)
        cursor.execute("SELECT COUNT(*) AS cnt FROM board_keywords;")
        bk_count = cursor.fetchone()["cnt"]
        cursor.execute("SELECT COUNT(*) AS cnt FROM board_settings;")
        bs_count = cursor.fetchone()["cnt"]

        if bk_count == 0 and bs_count == 0:
            logger.info("看板規則資料表為空，初始化預設看板監控規則...")
            default_rules = [
                ("Stock", ["群聯", "宜鼎", "創新服務", "漢唐"], 50),
                ("Lifeismoney", ["機票", "航空", "住宿", "旅行", "chatgpt", "gemini", "codex", "蝦皮", "電影"], 50),
                ("Gossiping", [], 80),
            ]
            for b_name, kws, push_th in default_rules:
                for kw in kws:
                    cursor.execute(
                        "INSERT OR IGNORE INTO board_keywords (board, keyword) VALUES (?, ?);",
                        (b_name, kw),
                    )
                if push_th > 0:
                    cursor.execute(
                        "INSERT OR REPLACE INTO board_settings (board, min_push_count) VALUES (?, ?);",
                        (b_name, push_th),
                    )

        # 7. 預設為 Stock 板建立 盤前、盤後、閒聊 排除規則
        for default_ex in ["盤前", "盤後", "閒聊"]:
            cursor.execute(
                "INSERT OR IGNORE INTO board_exclude_keywords (board, keyword) VALUES ('Stock', ?);",
                (default_ex,)
            )


# ==========================================
# 看板與關鍵字 CRUD 操作
# ==========================================

def add_board_keyword(board: str, keyword: str, db_path: Optional[str] = None) -> List[str]:
    """
    新增指定看板的一組或多組關鍵字（支援逗號分隔）
    回傳成功新增的關鍵字清單
    """
    b_name = canonicalize_board_name(board)
    raw_kws = [k.strip() for k in keyword.replace("，", ",").split(",") if k.strip()]
    added = []

    with get_db_cursor(db_path) as cursor:
        for kw in raw_kws:
            cursor.execute(
                "SELECT 1 FROM board_keywords WHERE board = ? AND keyword = ?;",
                (b_name, kw),
            )
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO board_keywords (board, keyword) VALUES (?, ?);",
                    (b_name, kw),
                )
                added.append(kw)

    return added


def delete_board_keyword(board: str, keyword: str, db_path: Optional[str] = None) -> List[str]:
    """
    刪除指定看板的關鍵字（支援逗號分隔或全部）
    回傳成功刪除的關鍵字清單
    """
    b_name = canonicalize_board_name(board)
    raw_kws = [k.strip() for k in keyword.replace("，", ",").split(",") if k.strip()]
    deleted = []

    with get_db_cursor(db_path) as cursor:
        for kw in raw_kws:
            cursor.execute(
                "DELETE FROM board_keywords WHERE board = ? AND keyword = ?;",
                (b_name, kw),
            )
            if cursor.rowcount > 0:
                deleted.append(kw)

    return deleted


def set_board_min_push(board: str, min_push_count: int, db_path: Optional[str] = None) -> bool:
    """設定或更新指定看板的推文門檻（若 min_push_count <= 0 則視為取消門檻）"""
    b_name = canonicalize_board_name(board)
    with get_db_cursor(db_path) as cursor:
        if min_push_count > 0:
            cursor.execute(
                "INSERT OR REPLACE INTO board_settings (board, min_push_count) VALUES (?, ?);",
                (b_name, int(min_push_count)),
            )
        else:
            cursor.execute("DELETE FROM board_settings WHERE board = ?;", (b_name,))
        return True


def delete_board_min_push(board: str, db_path: Optional[str] = None) -> bool:
    """刪除/取消指定看板的推文門檻"""
    b_name = canonicalize_board_name(board)
    with get_db_cursor(db_path) as cursor:
        cursor.execute("DELETE FROM board_settings WHERE board = ?;", (b_name,))
        return cursor.rowcount > 0


def add_board_exclude_keyword(board: str, keyword: str, db_path: Optional[str] = None) -> List[str]:
    """新增指定看板的一組或多組排除關鍵字（黑名單，支援逗號分隔）"""
    b_name = canonicalize_board_name(board)
    raw_kws = [k.strip() for k in keyword.replace("，", ",").split(",") if k.strip()]
    added = []

    with get_db_cursor(db_path) as cursor:
        for kw in raw_kws:
            cursor.execute(
                "SELECT 1 FROM board_exclude_keywords WHERE board = ? AND keyword = ?;",
                (b_name, kw),
            )
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO board_exclude_keywords (board, keyword) VALUES (?, ?);",
                    (b_name, kw),
                )
                added.append(kw)
    return added


def delete_board_exclude_keyword(board: str, keyword: str, db_path: Optional[str] = None) -> List[str]:
    """刪除指定看板的一組或多組排除關鍵字"""
    b_name = canonicalize_board_name(board)
    raw_kws = [k.strip() for k in keyword.replace("，", ",").split(",") if k.strip()]
    deleted = []

    with get_db_cursor(db_path) as cursor:
        for kw in raw_kws:
            cursor.execute(
                "DELETE FROM board_exclude_keywords WHERE board = ? AND keyword = ?;",
                (b_name, kw),
            )
            if cursor.rowcount > 0:
                deleted.append(kw)
    return deleted


def get_board_exclude_keywords(board: str, db_path: Optional[str] = None) -> List[str]:
    """獲取指定看板的排除關鍵字清單"""
    b_name = canonicalize_board_name(board)
    with get_db_cursor(db_path) as cursor:
        cursor.execute(
            "SELECT keyword FROM board_exclude_keywords WHERE board = ? ORDER BY created_at ASC;",
            (b_name,),
        )
        return [row["keyword"] for row in cursor.fetchall()]


def get_all_monitored_boards_config(db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """
    取得目前所有受監控看板之完整設定
    格式:
    {
        "Stock": {"keywords": ["台積電"], "exclude_keywords": ["盤前", "盤後"], "min_push_count": 50},
        "Gossiping": {"keywords": [], "exclude_keywords": [], "min_push_count": 80}
    }
    """
    boards_config: Dict[str, Dict[str, Any]] = {}

    with get_db_cursor(db_path) as cursor:
        # 1. 撈取所有包含關鍵字
        cursor.execute("SELECT board, keyword FROM board_keywords ORDER BY created_at ASC;")
        for row in cursor.fetchall():
            b = row["board"]
            if b not in boards_config:
                boards_config[b] = {"keywords": [], "exclude_keywords": [], "min_push_count": 0}
            boards_config[b]["keywords"].append(row["keyword"])

        # 2. 撈取所有排除關鍵字
        cursor.execute("SELECT board, keyword FROM board_exclude_keywords ORDER BY created_at ASC;")
        for row in cursor.fetchall():
            b = row["board"]
            if b not in boards_config:
                boards_config[b] = {"keywords": [], "exclude_keywords": [], "min_push_count": 0}
            boards_config[b]["exclude_keywords"].append(row["keyword"])

        # 3. 撈取所有推文數設定
        cursor.execute("SELECT board, min_push_count FROM board_settings;")
        for row in cursor.fetchall():
            b = row["board"]
            if b not in boards_config:
                boards_config[b] = {"keywords": [], "exclude_keywords": [], "min_push_count": 0}
            boards_config[b]["min_push_count"] = row["min_push_count"]

    # 過濾掉完全沒有任何條件的看板
    active_configs = {
        b: cfg for b, cfg in boards_config.items()
        if (cfg["keywords"] or cfg["exclude_keywords"] or cfg["min_push_count"] > 0)
    }
    return active_configs


# ==========================================
# 系統開關（暫停 / 開始監控）
# ==========================================

def set_monitoring_paused(paused: bool, db_path: Optional[str] = None) -> None:
    """設定系統暫停狀態"""
    val = "1" if paused else "0"
    with get_db_cursor(db_path) as cursor:
        cursor.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('is_paused', ?);",
            (val,),
        )


def is_monitoring_paused(db_path: Optional[str] = None) -> bool:
    """檢查系統是否處於暫停狀態"""
    with get_db_cursor(db_path) as cursor:
        cursor.execute("SELECT value FROM system_settings WHERE key = 'is_paused';")
        row = cursor.fetchone()
        if row and row["value"] == "1":
            return True
        return False


# ==========================================
# 推播去重與統計
# ==========================================

def is_post_notified(platform: str, post_id: str, db_path: Optional[str] = None) -> bool:
    """檢查指定平台的文章是否已推播過"""
    with get_db_cursor(db_path) as cursor:
        cursor.execute(
            "SELECT 1 FROM notified_posts WHERE platform = ? AND post_id = ? LIMIT 1;",
            (str(platform), str(post_id)),
        )
        return cursor.fetchone() is not None


def mark_post_notified(
    platform: str,
    post_id: str,
    title: str = "",
    url: str = "",
    board: str = "",
    reason: str = "",
    db_path: Optional[str] = None,
) -> bool:
    """記錄已推播的文章"""
    with get_db_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT OR REPLACE INTO notified_posts 
            (platform, post_id, title, url, board, reason, created_at) 
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
            """,
            (str(platform), str(post_id), title, url, board, reason),
        )
        return True


def get_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """獲取詳細統計資訊"""
    with get_db_cursor(db_path) as cursor:
        cursor.execute("SELECT COUNT(*) AS kw_count FROM board_keywords;")
        kw_count = cursor.fetchone()["kw_count"]

        cursor.execute("SELECT COUNT(*) AS post_count FROM notified_posts;")
        post_count = cursor.fetchone()["post_count"]

        cursor.execute("SELECT value FROM system_settings WHERE key = 'is_paused';")
        row = cursor.fetchone()
        is_paused = (row is not None and row["value"] == "1")

        all_cfg = get_all_monitored_boards_config(db_path)

        return {
            "is_paused": is_paused,
            "monitored_boards_count": len(all_cfg),
            "monitored_boards": list(all_cfg.keys()),
            "total_keywords_count": kw_count,
            "total_notified_posts": post_count,
        }


# 舊版相容接口
def get_keywords(db_path: Optional[str] = None) -> List[str]:
    """舊版全域關鍵字相容接口"""
    with get_db_cursor(db_path) as cursor:
        cursor.execute("SELECT DISTINCT keyword FROM board_keywords;")
        return [r["keyword"] for r in cursor.fetchall()]
