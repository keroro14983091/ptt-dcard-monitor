import os
import tempfile
import unittest
from config import Config
import database as db
from crawlers.ptt import PTTCrawler
from bot_handler import format_notification_html


class TestMonitorSystem(unittest.TestCase):
    def setUp(self):
        # 使用暫存 SQLite 資料庫進行測試
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        db.init_db(self.temp_db_path)

    def tearDown(self):
        if os.path.exists(self.temp_db_path):
            try:
                os.remove(self.temp_db_path)
            except OSError:
                pass

    def test_board_keywords_crud(self):
        # 1. 預設規則檢查 (Stock 應有 群聯)
        cfg = db.get_all_monitored_boards_config(self.temp_db_path)
        self.assertIn("Stock", cfg)
        self.assertIn("群聯", cfg["Stock"]["keywords"])

        # 2. 新增看板關鍵字
        added = db.add_board_keyword("C_Chat", "咒術迴戰,芙莉蓮", self.temp_db_path)
        self.assertEqual(len(added), 2)
        self.assertIn("咒術迴戰", added)
        self.assertIn("芙莉蓮", added)

        kws = db.get_board_keywords("C_Chat", self.temp_db_path)
        self.assertIn("咒術迴戰", kws)
        self.assertIn("芙莉蓮", kws)

        # 3. 刪除看板關鍵字
        deleted = db.delete_board_keyword("C_Chat", "咒術迴戰", self.temp_db_path)
        self.assertIn("咒術迴戰", deleted)
        kws_after = db.get_board_keywords("C_Chat", self.temp_db_path)
        self.assertNotIn("咒術迴戰", kws_after)
        self.assertIn("芙莉蓮", kws_after)

    def test_board_push_count_crud(self):
        # 1. 設定推文門檻
        db.set_board_min_push("Gossiping", 100, self.temp_db_path)
        cfg = db.get_all_monitored_boards_config(self.temp_db_path)
        self.assertEqual(cfg["Gossiping"]["min_push_count"], 100)

        # 2. 刪除推文門檻
        deleted = db.delete_board_min_push("Gossiping", self.temp_db_path)
        self.assertTrue(deleted)
        cfg_after = db.get_all_monitored_boards_config(self.temp_db_path)
        self.assertNotIn("Gossiping", cfg_after)  # Gossiping 無關鍵字且無推文數時自動移出 active

    def test_pause_resume_state(self):
        self.assertFalse(db.is_monitoring_paused(self.temp_db_path))
        db.set_monitoring_paused(True, self.temp_db_path)
        self.assertTrue(db.is_monitoring_paused(self.temp_db_path))
        db.set_monitoring_paused(False, self.temp_db_path)
        self.assertFalse(db.is_monitoring_paused(self.temp_db_path))

    def test_post_deduplication(self):
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
