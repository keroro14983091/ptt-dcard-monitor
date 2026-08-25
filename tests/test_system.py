import os
import tempfile
import unittest
from config import Config
import database as db
from crawlers.ptt import PTTCrawler
from crawlers.dcard import DcardCrawler
from bot_handler import format_notification_html


class TestMonitorSystem(unittest.TestCase):
    def setUp(self):
        # 使用暫存 SQLite 資料庫進行測試
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        db.init_db(self.temp_db_path, default_keywords=["台積電", "美股"])

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_database_crud(self):
        # 1. 初始關鍵字檢查
        kws = db.get_keywords(self.temp_db_path)
        self.assertIn("台積電", kws)
        self.assertIn("美股", kws)

        # 2. 新增關鍵字
        added = db.add_keyword("聯發科", self.temp_db_path)
        self.assertTrue(added)
        # 重複新增應回傳 False
        added_duplicate = db.add_keyword("聯發科", self.temp_db_path)
        self.assertFalse(added_duplicate)
        self.assertIn("聯發科", db.get_keywords(self.temp_db_path))

        # 3. 刪除關鍵字
        deleted = db.delete_keyword("聯發科", self.temp_db_path)
        self.assertTrue(deleted)
        deleted_again = db.delete_keyword("聯發科", self.temp_db_path)
        self.assertFalse(deleted_again)
        self.assertNotIn("聯發科", db.get_keywords(self.temp_db_path))

        # 4. 推播文章去重檢查
        is_notified = db.is_post_notified("PTT", "ptt_Stock_M123", self.temp_db_path)
        self.assertFalse(is_notified)

        marked = db.mark_post_notified(
            platform="PTT",
            post_id="ptt_Stock_M123",
            title="[標的] 2330 台積電多",
            url="https://www.ptt.cc/bbs/Stock/M.123.html",
            board="Stock",
            reason="符合關鍵字 [台積電]",
            db_path=self.temp_db_path,
        )
        self.assertTrue(marked)
        self.assertTrue(db.is_post_notified("PTT", "ptt_Stock_M123", self.temp_db_path))

        # 5. 統計數據測試
        stats = db.get_stats(self.temp_db_path)
        self.assertEqual(stats["keyword_count"], 2)
        self.assertEqual(stats["total_notified_posts"], 1)

    def test_ptt_filter(self):
        crawler = PTTCrawler()
        mock_posts = [
            {
                "platform": "PTT",
                "board": "Stock",
                "post_id": "ptt_Stock_1",
                "raw_id": "1",
                "title": "[新聞] 台積電今日創新高",
                "url": "https://www.ptt.cc/bbs/Stock/1.html",
                "author": "tester",
                "date": "8/25",
                "push_count": 10,
                "is_bao": False,
                "nrec_text": "10",
            },
            {
                "platform": "PTT",
                "board": "Stock",
                "post_id": "ptt_Stock_2",
                "raw_id": "2",
                "title": "[閒聊] 今日大盤狂漲",
                "url": "https://www.ptt.cc/bbs/Stock/2.html",
                "author": "tester",
                "date": "8/25",
                "push_count": 100,
                "is_bao": True,
                "nrec_text": "爆",
            },
            {
                "platform": "PTT",
                "board": "Stock",
                "post_id": "ptt_Stock_3",
                "raw_id": "3",
                "title": "[無關] 今天天氣真好",
                "url": "https://www.ptt.cc/bbs/Stock/3.html",
                "author": "tester",
                "date": "8/25",
                "push_count": 5,
                "is_bao": False,
                "nrec_text": "5",
            },
        ]

        matched = crawler.filter_matching_posts(
            mock_posts, keywords=["台積電"], min_push_count=50
        )
        self.assertEqual(len(matched), 2)
        self.assertIn("符合關鍵字 [台積電]", matched[0]["reason"])
        self.assertIn("爆文達成", matched[1]["reason"])

    def test_dcard_filter(self):
        crawler = DcardCrawler()
        mock_posts = [
            {
                "platform": "Dcard",
                "board": "stock",
                "post_id": "dcard_stock_101",
                "raw_id": "101",
                "title": "美股投資新手請益",
                "excerpt": "最近想買進標普500...",
                "url": "https://www.dcard.tw/f/stock/p/101",
                "like_count": 12,
                "comment_count": 5,
                "created_at": "2026-08-25T00:00:00.000Z",
            },
            {
                "platform": "Dcard",
                "board": "stock",
                "post_id": "dcard_stock_102",
                "raw_id": "102",
                "title": "大家都買什麼定期定額？",
                "excerpt": "好奇大家看法",
                "url": "https://www.dcard.tw/f/stock/p/102",
                "like_count": 80,
                "comment_count": 150,
                "created_at": "2026-08-25T00:00:00.000Z",
            },
        ]

        matched = crawler.filter_matching_posts(
            mock_posts, keywords=["美股"], min_like_count=50
        )
        self.assertEqual(len(matched), 2)
        self.assertIn("符合關鍵字 [美股]", matched[0]["reason"])
        self.assertIn("熱門文章達成 (80 讚)", matched[1]["reason"])

    def test_notification_html_formatting(self):
        post = {
            "platform": "PTT",
            "board": "Stock",
            "title": "<b>危險標籤測試 & 特殊符號</b>",
            "reason": "符合關鍵字 [台積電]",
            "url": "https://www.ptt.cc/bbs/Stock/test.html",
        }
        formatted = format_notification_html(post)
        self.assertIn("&lt;b&gt;危險標籤測試 &amp; 特殊符號&lt;/b&gt;", formatted)
        self.assertIn("🚨<b>【PTT Stock 觸發通知】</b>", formatted)
        self.assertIn("href=\"https://www.ptt.cc/bbs/Stock/test.html\"", formatted)


if __name__ == "__main__":
    unittest.main()
