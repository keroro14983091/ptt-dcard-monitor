import re
import time
import random
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from config import config, logger

# 嘗試導入具備真實瀏覽器 TLS/JA3 指紋偽裝的 curl_cffi 函式庫以突破 Cloudflare 阻擋
try:
    from curl_cffi import requests as cffi_requests
    from curl_cffi.requests import Session as CffiSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    CffiSession = None


class PTTCrawler:
    """PTT 看板爬蟲：支援 over18 年齡驗證、關鍵字匹配與推文數/爆文過濾，具備防 Cloudflare 阻擋與即時診斷追蹤"""

    BASE_URL = "https://www.ptt.cc"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    COOKIES = {"over18": "1"}

    def __init__(self, session: Optional[Any] = None, proxy_url: Optional[str] = None):
        self.use_curl_cffi = HAS_CURL_CFFI and (session is None)
        proxy = proxy_url or getattr(config, "ptt_proxy_url", "")

        if self.use_curl_cffi:
            # 採用 Chrome 124 TLS 指紋與 HTTP/2 握手，突破 Cloudflare 403 阻擋
            self.session = CffiSession(impersonate="chrome124")
            self.session.headers.update(self.HEADERS)
            self.session.cookies.set("over18", "1", domain=".ptt.cc")
            if proxy:
                self.session.proxies = {"http": proxy, "https": proxy}
                logger.info(f"[PTT] curl_cffi 爬蟲已配置代理: {proxy}")
            logger.info("[PTT] 爬蟲已啟用 curl_cffi (Chrome 124 TLS 偽裝) 模式，以突破 Cloudflare 防護")
        else:
            self.session = session or requests.Session()
            self.session.headers.update(self.HEADERS)
            self.session.cookies.update(self.COOKIES)
            if proxy:
                self.session.proxies = {"http": proxy, "https": proxy}
                logger.info(f"[PTT] requests 爬蟲已配置代理: {proxy}")
            if not HAS_CURL_CFFI:
                logger.info("[PTT] 使用標準 requests 模式")

        # 記錄各看板最新一次爬取診斷資訊
        self.board_status: Dict[str, Dict[str, Any]] = {}

    def get_board_status(self, board: Optional[str] = None) -> Dict[str, Any]:
        """獲取各看板或特定看板的最新連線診斷狀態"""
        if board:
            return self.board_status.get(board, {})
        return dict(self.board_status)

    def fetch_board_posts(
        self, board: str, pages: int = 1, ignore_pinned: bool = True
    ) -> List[Dict[str, Any]]:
        """
        抓取指定看板的最新文章列表
        pages: 抓取的頁數（預設 1 頁）
        ignore_pinned: 是否過濾置底公告文章（預設 True，過濾 PTT 永久置底公告）
        """
        posts = []
        url = f"{self.BASE_URL}/bbs/{board}/index.html"
        last_http_code = None
        error_msg = None
        pages_crawled = 0

        for page_idx in range(pages):
            if not url:
                break

            # 若抓取多頁，在換頁時加入 0.8 ~ 1.5 秒微延遲，避免短時間高頻突發請求觸發 Cloudflare 阻擋
            if page_idx > 0:
                time.sleep(random.uniform(0.8, 1.5))

            try:
                resp = self.session.get(url, timeout=10.0)
                last_http_code = resp.status_code
                pages_crawled += 1

                if resp.status_code != 200:
                    server = resp.headers.get("server", "")
                    title_match = re.search(r"<title>(.*?)</title>", resp.text, re.IGNORECASE)
                    title_snip = title_match.group(1).strip() if title_match else resp.text[:60].replace("\n", " ").strip()
                    error_msg = f"HTTP {resp.status_code} [{server}]: {title_snip}" if server else f"HTTP {resp.status_code}"
                    logger.warning(f"[PTT] 抓取看板 {board} 失敗，{error_msg}")
                    break

                soup = BeautifulSoup(resp.text, "html.parser")

                # 若 ignore_pinned=True 且在第一頁，過濾掉置底公告 (<div class="r-list-sep"></div> 之後的文章)
                if ignore_pinned and page_idx == 0 and soup.select_one("div.r-list-sep"):
                    pinned_entries = set(soup.select("div.r-list-sep ~ div.r-ent"))
                    entries = [e for e in soup.select("div.r-ent") if e not in pinned_entries]
                else:
                    entries = soup.select("div.r-ent")

                for entry in entries:
                    parsed = self._parse_entry(board, entry)
                    if parsed:
                        posts.append(parsed)

                # 取得上一頁連結
                prev_link = soup.select_one("div.btn-group-paging a:nth-child(2)")
                if prev_link and prev_link.get("href"):
                    url = self.BASE_URL + prev_link["href"]
                else:
                    url = None

            except Exception as e:
                error_msg = f"連線異常: {e}"
                logger.error(f"[PTT] 請求看板 {board} 時發生異常: {e}")
                break

        # 更新該看板即時診斷數據
        engine_tag = "curl_cffi" if getattr(self, "use_curl_cffi", False) else "requests"
        self.board_status[board] = {
            "status_code": last_http_code,
            "posts_count": len(posts),
            "pages_crawled": pages_crawled,
            "error": error_msg,
            "engine": engine_tag,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        return posts

    def _parse_entry(self, board: str, entry) -> Optional[Dict[str, Any]]:
        """解析單一文章 DOM 元素"""
        title_tag = entry.select_one("div.title a")
        if not title_tag or not title_tag.get("href"):
            # 文章可能已被刪除 (e.g. (本文已被刪除))
            return None

        title = title_tag.get_text(strip=True)
        href = title_tag["href"].strip()
        url = self.BASE_URL + href

        # 從 URL 擷取 post_id，例如 /bbs/Stock/M.1724567890.A.123.html -> M.1724567890.A.123
        match = re.search(r"/(M\.\d+\.A\.[0-9A-F]+)\.html", href)
        post_id = match.group(1) if match else href.split("/")[-1].replace(".html", "")

        # 解析推文數
        nrec_tag = entry.select_one("div.nrec")
        nrec_text = nrec_tag.get_text(strip=True) if nrec_tag else ""
        push_count = 0
        is_bao = (nrec_text == "爆")

        if is_bao:
            push_count = 100
        elif nrec_text.isdigit():
            push_count = int(nrec_text)
        elif nrec_text.startswith("X"):
            push_count = -10  # 噓文過多

        # 作者
        author_tag = entry.select_one("div.meta div.author")
        author = author_tag.get_text(strip=True) if author_tag else ""

        # 日期
        date_tag = entry.select_one("div.meta div.date")
        date_str = date_tag.get_text(strip=True) if date_tag else ""

        return {
            "platform": "PTT",
            "board": board,
            "post_id": f"ptt_{board}_{post_id}",
            "raw_id": post_id,
            "title": title,
            "url": url,
            "author": author,
            "date": date_str,
            "push_count": push_count,
            "is_bao": is_bao,
            "nrec_text": nrec_text,
        }

    def filter_matching_posts(
        self,
        posts: List[Dict[str, Any]],
        keywords: List[str],
        exclude_keywords: Optional[List[str]] = None,
        min_push_count: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        依據即時關鍵字、排除關鍵字及爆文門檻過濾文章：
        1. 標題含有任何「排除關鍵字」-> 絕對排除跳過 (不論推文數多高)
        2. 標題符合任何「包含關鍵字」（不分大小寫）
        3. 推文數為「爆」或大於等於 min_push_count
        """
        matched_posts = []
        clean_keywords = [kw.strip().lower() for kw in (keywords or []) if kw.strip()]
        clean_exclude_kws = [ex.strip().lower() for ex in (exclude_keywords or []) if ex.strip()]

        for post in posts:
            title_lower = post["title"].lower()

            # 1. 黑名單檢查：若命中任何排除詞，直接略過
            if any(ex_kw in title_lower for ex_kw in clean_exclude_kws):
                continue

            matched_kws = [kw for kw in clean_keywords if kw in title_lower]

            is_push_hot = post["is_bao"] or (
                min_push_count > 0 and post["push_count"] >= min_push_count
            )

            # 判斷是否符合條件
            reasons = []
            if matched_kws:
                reasons.append(f"符合關鍵字 [{', '.join(matched_kws)}]")
            if post["is_bao"]:
                reasons.append("爆文達成 (100+ 推)")
            elif is_push_hot:
                reasons.append(f"推文達標 ({post['push_count']} 推)")

            if reasons:
                post_copy = dict(post)
                post_copy["reason"] = "、".join(reasons)
                matched_posts.append(post_copy)

        return matched_posts
