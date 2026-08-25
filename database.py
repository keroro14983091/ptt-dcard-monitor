import os
import sqlite3
import logging
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Generator
from datetime import datetime, timedelta
from config import config, logger


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


def init_db(db_path: Optional[str] = None, default_keywords: Optional[List[str]] = None) -> None:
    """
    初始化 SQLite 資料表：
    1. keywords (keyword TEXT PRIMARY KEY, created_at TIMESTAMP)
    2. notified_posts (platform, post_id, title, url, board, reason, created_at)
    若 keywords 為空，自動寫入預設關鍵字。
    自動相容舊版資料表結構與欄位遷移。
    """
    defaults = default_keywords if default_keywords is not None else config.default_keywords

    with get_db_cursor(db_path) as cursor:
        # 1. 建立 keywords 資料表
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS keywords (
                keyword TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # 2. 建立 notified_posts 資料表
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

        # 3. 檢查現有欄位並進行自動擴充/補齊 (相容舊版 DB)
        cursor.execute("PRAGMA table_info(notified_posts);")
        existing_cols = {row["name"] for row in cursor.fetchall()}

        if "reason" not in existing_cols:
            cursor.execute("ALTER TABLE notified_posts ADD COLUMN reason TEXT;")
        if "title" not in existing_cols:
            cursor.execute("ALTER TABLE notified_posts ADD COLUMN title TEXT;")
        if "url" not in existing_cols:
            cursor.execute("ALTER TABLE notified_posts ADD COLUMN url TEXT;")
        if "board" not in existing_cols:
            cursor.execute("ALTER TABLE notified_posts ADD COLUMN board TEXT;")

        # 建立快速查詢索引
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notified_lookup 
            ON notified_posts (platform, post_id);
            """
        )

        # 4. 檢查是否需要匯入預設關鍵字
        cursor.execute("SELECT COUNT(*) AS cnt FROM keywords;")
        count = cursor.fetchone()["cnt"]

        if count == 0 and defaults:
            logger.info(f"關鍵字資料表為空，寫入預設關鍵字: {defaults}")
            for kw in defaults:
                kw_clean = kw.strip()
                if kw_clean:
                    cursor.execute(
                        "INSERT OR IGNORE INTO keywords (keyword, created_at) VALUES (?, CURRENT_TIMESTAMP);",
                        (kw_clean,),
                    )


def add_keyword(keyword: str, db_path: Optional[str] = None) -> bool:
    """新增關鍵字，若已存在則回傳 False"""
    kw_clean = keyword.strip()
    if not kw_clean:
        return False

    with get_db_cursor(db_path) as cursor:
        cursor.execute("SELECT 1 FROM keywords WHERE keyword = ?;", (kw_clean,))
        if cursor.fetchone():
            return False

        cursor.execute(
            "INSERT INTO keywords (keyword, created_at) VALUES (?, CURRENT_TIMESTAMP);",
            (kw_clean,),
        )
        return True


def delete_keyword(keyword: str, db_path: Optional[str] = None) -> bool:
    """刪除關鍵字，若不存在回傳 False"""
    kw_clean = keyword.strip()
    if not kw_clean:
        return False

    with get_db_cursor(db_path) as cursor:
        cursor.execute("DELETE FROM keywords WHERE keyword = ?;", (kw_clean,))
        return cursor.rowcount > 0


def get_keywords(db_path: Optional[str] = None) -> List[str]:
    """取得所有監控關鍵字清單"""
    with get_db_cursor(db_path) as cursor:
        cursor.execute("SELECT keyword FROM keywords ORDER BY created_at ASC;")
        rows = cursor.fetchall()
        return [row["keyword"] for row in rows]


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
        # 使用 INSERT OR IGNORE 或 INSERT OR REPLACE
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
    """獲取資料庫統計資訊"""
    with get_db_cursor(db_path) as cursor:
        cursor.execute("SELECT COUNT(*) AS kw_count FROM keywords;")
        kw_count = cursor.fetchone()["kw_count"]

        cursor.execute("SELECT COUNT(*) AS post_count FROM notified_posts;")
        post_count = cursor.fetchone()["post_count"]

        cursor.execute(
            """
            SELECT platform, COUNT(*) as cnt 
            FROM notified_posts 
            GROUP BY platform;
            """
        )
        platform_counts = {row["platform"]: row["cnt"] for row in cursor.fetchall()}

        return {
            "keyword_count": kw_count,
            "total_notified_posts": post_count,
            "platform_stats": platform_counts,
        }


def cleanup_old_posts(days: int = 30, db_path: Optional[str] = None) -> int:
    """清理超過 N 天的舊推播紀錄，避免資料庫無限膨脹"""
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_cursor(db_path) as cursor:
        cursor.execute(
            "DELETE FROM notified_posts WHERE created_at < ?;",
            (cutoff,),
        )
        return cursor.rowcount
