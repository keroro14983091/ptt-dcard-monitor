import sys
import time
import json
import random
import signal
import asyncio
from typing import List, Dict, Any

from config import config, logger
import database as db
from bot_handler import create_bot_application, broadcast_notification
from crawlers.ptt import PTTCrawler

# 全域控制變數
is_running = True
start_time = time.time()


async def monitor_crawler_loop(bot_holder: dict):
    """爬蟲排程主迴圈：定期抓取各看板、比對看板專屬關鍵字與推文門檻並推播"""
    global is_running
    ptt_crawler = PTTCrawler()

    logger.info("📡 爬蟲監控背景任務啟動中...")

    # 1. 等待 Telegram Bot 初始化完成
    for _ in range(30):
        if not is_running:
            return
        if bot_holder.get("bot"):
            break
        await asyncio.sleep(0.5)

    # 2. 系統啟動基準預熱 (Baseline Warmup)：
    # 初次啟動時，先掃描現有各看板文章並登記為已存在，避免推播啟動前的歷史舊文
    try:
        boards_config = db.get_all_monitored_boards_config()
        logger.info(f"🔄 執行啟動基準預熱掃描... (正在為 {len(boards_config)} 個看板登記現有文章)")
        for board, rule in boards_config.items():
            kws = rule.get("keywords", [])
            min_push = rule.get("min_push_count", 0)
            posts = await asyncio.to_thread(ptt_crawler.fetch_board_posts, board, pages=1, ignore_pinned=True)
            matched_posts = ptt_crawler.filter_matching_posts(
                posts, kws, min_push_count=min_push
            )
            for post in matched_posts:
                if not db.is_post_notified(post["platform"], post["post_id"]):
                    db.mark_post_notified(
                        platform=post["platform"],
                        post_id=post["post_id"],
                        title=post["title"],
                        url=post["url"],
                        board=post["board"],
                        reason=post["reason"],
                    )
        logger.info("✅ 啟動基準建立完成！即刻起僅監控與推播「從現在起新發布/新達標」之文章。")
    except Exception as e:
        logger.warning(f"啟動基準預熱掃描異常: {e}")

    # 3. 正式監控迴圈
    while is_running:
        try:
            # 檢查是否處於暫停狀態
            if db.is_monitoring_paused():
                logger.debug("⏸️ 系統目前處於暫停監控狀態，跳過本輪爬取。")
                for _ in range(10):
                    if not is_running or not db.is_monitoring_paused():
                        break
                    await asyncio.sleep(1.0)
                continue

            # 動態獲取所有受監控看板及專屬規則
            boards_config = db.get_all_monitored_boards_config()
            if not boards_config:
                logger.info("ℹ️ 目前無任何受監控看板（可於 Telegram 輸入「新增關鍵字」或「新增推文數」開始監控）。")
                for _ in range(15):
                    if not is_running:
                        break
                    await asyncio.sleep(1.0)
                continue

            logger.info(f"🔄 開始新一輪爬取檢查... (監控看板數: {len(boards_config)}，看板: {', '.join(boards_config.keys())})")
            bot = bot_holder.get("bot")

            # 依序爬取並過濾各看板
            for board, rule in boards_config.items():
                if not is_running or db.is_monitoring_paused():
                    break
                kws = rule.get("keywords", [])
                min_push = rule.get("min_push_count", 0)

                try:
                    logger.debug(f"[PTT] 正在抓取看板: {board} (關鍵字數: {len(kws)}, 門檻: {min_push})")
                    posts = await asyncio.to_thread(ptt_crawler.fetch_board_posts, board, pages=1, ignore_pinned=True)
                    matched_posts = ptt_crawler.filter_matching_posts(
                        posts, kws, min_push_count=min_push
                    )

                    for post in matched_posts:
                        if not is_running or db.is_monitoring_paused():
                            break
                        # 檢查是否已推播過
                        if not db.is_post_notified(post["platform"], post["post_id"]):
                            logger.info(
                                f"🎯 [觸發 PTT] 看板: {board} | 標題: {post['title']} | 原因: {post['reason']}"
                            )
                            if bot:
                                sent = await broadcast_notification(bot, post)
                                if sent:
                                    db.mark_post_notified(
                                        platform=post["platform"],
                                        post_id=post["post_id"],
                                        title=post["title"],
                                        url=post["url"],
                                        board=post["board"],
                                        reason=post["reason"],
                                    )
                            else:
                                logger.info(f"[命中但未推播(Bot未連線)] {post['title']}")
                            await asyncio.sleep(0.5)

                    await asyncio.sleep(1.0)
                except Exception as e:
                    logger.error(f"[PTT] 處理看板 {board} 時發生異常: {e}")

            # 計算隨機休眠時間
            if is_running and not db.is_monitoring_paused():
                delay = random.uniform(config.poll_interval_min_sec, config.poll_interval_max_sec)
                logger.info(f"⏳ 本輪爬取完畢，隨機休眠 {delay:.1f} 秒後進行下一輪...")
                for _ in range(int(delay)):
                    if not is_running or db.is_monitoring_paused():
                        break
                    await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.info("爬蟲任務接收到取消訊號。")
            break
        except Exception as e:
            logger.error(f"爬蟲監控迴圈發生未預期異常: {e}", exc_info=True)
            await asyncio.sleep(10.0)


async def start_telegram_bot(bot_app, bot_holder: dict):
    """啟動 Telegram Bot 輪詢，具備連線失敗重試機制"""
    global is_running
    while is_running:
        try:
            logger.info("正在連線至 Telegram API (api.telegram.org)...")
            await bot_app.initialize()
            await bot_app.start()
            await bot_app.updater.start_polling(drop_pending_updates=True)
            bot_holder["bot"] = bot_app.bot
            logger.info("🤖 Telegram Bot 繁體中文指令監聽器已成功上線！(支援自然文字與中文指令)")
            # 保持運行直到取消
            while is_running and bot_app.updater.running:
                await asyncio.sleep(2.0)
            break
        except Exception as e:
            logger.warning(
                f"⚠️ Telegram Bot 連線失敗 ({e})。\n"
                "💡 提示：若處於公司/受限網路，請在 .env 設定 TELEGRAM_PROXY_URL 代理，或檢查網路。\n"
                "系統將在 15 秒後自動重試連線..."
            )
            await asyncio.sleep(15.0)


async def handle_http_health_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """處理 HTTP GET 請求，回傳服務運行狀態供 Render 與 UptimeRobot 監控防休眠"""
    try:
        data = await reader.read(1024)
        if not data:
            writer.close()
            await writer.wait_closed()
            return

        uptime_sec = int(time.time() - start_time)
        try:
            stats = db.get_stats()
        except Exception:
            stats = {"is_paused": False, "monitored_boards_count": 0, "total_keywords_count": 0, "total_notified_posts": 0}

        payload = {
            "status": "healthy",
            "service": "PTT Telegram Keyword & Push Monitor",
            "uptime_seconds": uptime_sec,
            "is_paused": stats["is_paused"],
            "monitored_boards_count": stats["monitored_boards_count"],
            "monitored_boards": stats.get("monitored_boards", []),
            "total_keywords_count": stats["total_keywords_count"],
            "total_notified_posts": stats["total_notified_posts"],
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Access-Control-Allow-Origin: *\r\n"
            b"Connection: close\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
            + body
        )
        writer.write(response)
        await writer.drain()
    except Exception as e:
        logger.debug(f"HTTP 請求處理異常: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def start_health_server(port: int):
    """啟動非同步 HTTP 伺服器，滿足 Render 連接埠檢查並支援 UptimeRobot 定時 Ping"""
    try:
        server = await asyncio.start_server(handle_http_health_request, "0.0.0.0", port)
        logger.info(f"🌐 健康檢查 Web 伺服器已在連接埠 {port} 啟動 (提供 Render 綁定與 UptimeRobot 防休眠)")
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            server.close()
            await server.wait_closed()
    except Exception as e:
        logger.warning(f"⚠️ Web 伺服器啟動失敗 (連接埠 {port}): {e}，背景爬蟲與 Telegram 仍會正常運作。")


async def main():
    global is_running

    logger.info("==================================================")
    logger.info("🚀 PTT 看板條件/關鍵字/推文數自動監控推播系統 啟動中...")
    logger.info(f"📌 授權 Chat ID: {', '.join(config.telegram_chat_ids)}")
    logger.info("==================================================")

    # 1. 初始化 SQLite 資料庫
    db.init_db()

    # 2. 建立 Telegram Bot Application
    bot_app = create_bot_application()
    bot_holder = {"bot": None}

    # 3. 同時啟動 Bot 連線任務、爬蟲排程工作、以及 Web 健康檢查伺服器
    tasks = []
    bot_task = asyncio.create_task(start_telegram_bot(bot_app, bot_holder))
    crawler_task = asyncio.create_task(monitor_crawler_loop(bot_holder))
    tasks.extend([bot_task, crawler_task])

    if config.enable_web_server:
        web_task = asyncio.create_task(start_health_server(config.port))
        tasks.append(web_task)

    # 等待停止訊號
    try:
        await asyncio.gather(*tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("🛑 收到關閉訊號，正在安全關閉系統...")
    finally:
        is_running = False
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        logger.info("正在停止 Telegram Bot 服務...")
        try:
            if bot_app.updater and bot_app.updater.running:
                await bot_app.updater.stop()
            if bot_app.running:
                await bot_app.stop()
            await bot_app.shutdown()
        except Exception:
            pass
        logger.info("✅ 系統已安全關閉。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("系統已由使用者終止。")
    except Exception as e:
        logger.critical(f"系統發生未處理的嚴重異常: {e}", exc_info=True)
