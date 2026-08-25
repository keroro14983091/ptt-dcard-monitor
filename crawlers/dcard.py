import requests
from typing import List, Dict, Any, Optional
from config import config, logger


class DcardCrawler:
    """Dcard 看板爬蟲：呼叫 Dcard 公開 API 抓取看板最新文章並依關鍵字與讚數過濾"""

    BASE_API_URL = "https://www.dcard.tw/service/api/v2"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(self.HEADERS)
        if config.dcard_cookie:
            self.session.headers.update({"Cookie": config.dcard_cookie})
        if config.dcard_proxy_url:
            self.session.proxies = {
                "http": config.dcard_proxy_url,
                "https": config.dcard_proxy_url,
            }

    def fetch_board_posts(self, board: str, limit: int = 30) -> List[Dict[str, Any]]:
        """
        透過 Dcard API 抓取指定看板最新文章
        board: 看板英文簡稱 (e.g. stock, tech_job)
        limit: 抓取數量 (預設 30 篇)
        """
        url = f"{self.BASE_API_URL}/forums/{board}/posts?popular=false&limit={limit}"
        posts = []

        try:
            resp = self.session.get(url, timeout=10.0)
            if resp.status_code == 403:
                logger.warning(
                    f"[Dcard] 看板 {board} 遇到 403 阻擋（可能需要設定 DCARD_COOKIE 或代理）。"
                )
                return []
            elif resp.status_code == 429:
                logger.warning(f"[Dcard] 看板 {board} 遇到 429 速率限制，請稍候重試。")
                return []
            elif resp.status_code != 200:
                logger.warning(f"[Dcard] 抓取看板 {board} 失敗，HTTP 代碼: {resp.status_code}")
                return []

            data = resp.json()
            if not isinstance(data, list):
                logger.warning(f"[Dcard] 看板 {board} 回傳格式非列表: {data}")
                return []

            for item in data:
                parsed = self._parse_item(board, item)
                if parsed:
                    posts.append(parsed)

        except requests.RequestException as e:
            logger.error(f"[Dcard] 請求看板 {board} 時發生網路異常: {e}")
        except Exception as e:
            logger.error(f"[Dcard] 解析看板 {board} 發生未知異常: {e}", exc_info=True)

        return posts

    def _parse_item(self, board: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析 Dcard JSON API 單篇文章物件"""
        post_id = item.get("id")
        title = item.get("title", "").strip()
        excerpt = item.get("excerpt", "").strip()
        like_count = item.get("likeCount", 0)
        comment_count = item.get("totalCommentCount", 0)
        created_at = item.get("createdAt", "")

        if not post_id or not title:
            return None

        url = f"https://www.dcard.tw/f/{board}/p/{post_id}"

        return {
            "platform": "Dcard",
            "board": board,
            "post_id": f"dcard_{board}_{post_id}",
            "raw_id": str(post_id),
            "title": title,
            "excerpt": excerpt,
            "url": url,
            "like_count": like_count,
            "comment_count": comment_count,
            "created_at": created_at,
        }

    def filter_matching_posts(
        self,
        posts: List[Dict[str, Any]],
        keywords: List[str],
        min_like_count: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        依據即時關鍵字及按讚數門檻過濾文章：
        1. 標題或摘要符合任何關鍵字（不分大小寫）
        2. 按讚數 (likeCount) 大於等於 min_like_count
        """
        matched_posts = []
        clean_keywords = [kw.strip().lower() for kw in keywords if kw.strip()]

        for post in posts:
            title_lower = post["title"].lower()
            excerpt_lower = post.get("excerpt", "").lower()

            # 比對標題與摘要是否包含關鍵字
            matched_kws = [
                kw
                for kw in clean_keywords
                if (kw in title_lower or kw in excerpt_lower)
            ]

            is_like_hot = (
                min_like_count > 0 and post.get("like_count", 0) >= min_like_count
            )

            reasons = []
            if matched_kws:
                reasons.append(f"符合關鍵字 [{', '.join(matched_kws)}]")
            if is_like_hot:
                reasons.append(f"熱門文章達成 ({post.get('like_count', 0)} 讚)")

            if reasons:
                post_copy = dict(post)
                post_copy["reason"] = "、".join(reasons)
                matched_posts.append(post_copy)

        return matched_posts
