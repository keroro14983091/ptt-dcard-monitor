import html
import functools
import logging
from typing import Optional, Dict, Any
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from telegram.request import HTTPXRequest
from telegram.constants import ParseMode
from config import config, logger
import database as db


def authorized_only(func):
    """驗證操作者是否具備管理員權限的裝飾器"""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        chat_id = update.effective_chat.id if update.effective_chat else None

        is_authorized = (
            (user_id in config.allowed_user_ids)
            or (str(chat_id) in config.telegram_chat_ids)
            or (str(user_id) in config.telegram_chat_ids)
        )

        if not is_authorized:
            logger.warning(f"攔截到未授權使用者嘗試操作指令: UserID={user_id}, ChatID={chat_id}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⛔ <b>未授權存取</b>\n您沒有操作此推播監控機器人的權限。",
                    parse_mode=ParseMode.HTML,
                )
            return

        return await func(update, context, *args, **kwargs)

    return wrapper


@authorized_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /help 與 /start 指令"""
    help_text = (
        "🤖 <b>PTT & Dcard 關鍵字監控機器人 指令選單</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔹 <code>/add &lt;關鍵字&gt;</code>\n"
        "   👉 新增監控關鍵字（即時生效）\n"
        "   例如：<code>/add 台積電</code>\n\n"
        "🔹 <code>/del &lt;關鍵字&gt;</code>\n"
        "   👉 刪除監控關鍵字\n"
        "   例如：<code>/del 台積電</code>\n\n"
        "🔹 <code>/list</code>\n"
        "   👉 查詢目前所有監控關鍵字清單\n\n"
        "🔹 <code>/status</code>\n"
        "   👉 查看系統狀態與資料庫統計\n\n"
        "🔹 <code>/help</code>\n"
        "   👉 顯示此說明選單\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📡 <i>系統會在背景持續監控 PTT 與 Dcard 最新文章與爆文。</i>"
    )
    if update.effective_message:
        await update.effective_message.reply_text(help_text, parse_mode=ParseMode.HTML)


@authorized_only
async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /add <關鍵字> 指令"""
    if not context.args:
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ 請提供要新增的關鍵字。\n用法範例：<code>/add 台積電</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    keyword = " ".join(context.args).strip()
    if not keyword:
        if update.effective_message:
            await update.effective_message.reply_text("⚠️ 關鍵字不能為空！")
        return

    success = db.add_keyword(keyword)
    if success:
        logger.info(f"使用者新增關鍵字: {keyword}")
        reply_msg = f"✅ 已成功加入關鍵字：<b>{html.escape(keyword)}</b>"
    else:
        reply_msg = f"ℹ️ 關鍵字 <b>{html.escape(keyword)}</b> 已在監控清單中，無需重複新增。"

    if update.effective_message:
        await update.effective_message.reply_text(reply_msg, parse_mode=ParseMode.HTML)


@authorized_only
async def del_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /del <關鍵字> 指令"""
    if not context.args:
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ 請提供要刪除的關鍵字。\n用法範例：<code>/del 台積電</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    keyword = " ".join(context.args).strip()
    success = db.delete_keyword(keyword)
    if success:
        logger.info(f"使用者刪除關鍵字: {keyword}")
        reply_msg = f"🗑️ 已成功刪除關鍵字：<b>{html.escape(keyword)}</b>"
    else:
        reply_msg = f"⚠️ 找不到關鍵字：<b>{html.escape(keyword)}</b>，請先使用 /list 確認。"

    if update.effective_message:
        await update.effective_message.reply_text(reply_msg, parse_mode=ParseMode.HTML)


@authorized_only
async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /list 指令"""
    keywords = db.get_keywords()
    if not keywords:
        msg = "📭 目前沒有任何監控中的關鍵字。\n可使用 <code>/add &lt;關鍵字&gt;</code> 來新增！"
    else:
        kw_list_formatted = "\n".join([f"{idx + 1}. <code>{html.escape(kw)}</code>" for idx, kw in enumerate(keywords)])
        msg = (
            f"📋 <b>目前監控關鍵字清單（共 {len(keywords)} 組）：</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{kw_list_formatted}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💡 提示：使用 <code>/del &lt;關鍵字&gt;</code> 可刪除指定項目。"
        )

    if update.effective_message:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


@authorized_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 /status 指令"""
    stats = db.get_stats()
    ptt_boards = ", ".join(config.ptt_boards)
    dcard_info = f"\n📌 <b>Dcard 監控看板：</b> {', '.join(config.dcard_boards)}" if config.dcard_boards else ""
    dcard_threshold = f"\n🔥 <b>Dcard 讚數門檻：</b> {config.dcard_min_like_count} 讚" if config.dcard_boards else ""

    msg = (
        "📊 <b>系統運作狀態回報</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 <b>監控關鍵字總數：</b> {stats['keyword_count']} 組\n"
        f"📬 <b>歷史推播總數：</b> {stats['total_notified_posts']} 篇\n"
        f"📌 <b>PTT 監控看板：</b> {ptt_boards}"
        f"{dcard_info}\n"
        f"⏱️ <b>輪詢間隔：</b> {config.poll_interval_min_sec} ~ {config.poll_interval_max_sec} 秒\n"
        f"🔥 <b>PTT 爆文門檻：</b> {config.ptt_min_push_count} 推 / 爆"
        f"{dcard_threshold}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <i>服務正常運作中</i>"
    )
    if update.effective_message:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


def format_notification_html(post: Dict[str, Any]) -> str:
    """產生推播訊息格式"""
    platform = html.escape(str(post.get("platform", "")))
    board = html.escape(str(post.get("board", "")))
    title = html.escape(str(post.get("title", "")))
    reason = html.escape(str(post.get("reason", "")))
    url = post.get("url", "")

    message = (
        f"🚨<b>【{platform} {board} 觸發通知】</b>\n\n"
        f"📌 <b>標題：</b>{title}\n"
        f"🎯 <b>觸發原因：</b>{reason}\n"
        f"🔗 <b>連結：</b><a href=\"{url}\">點此開啟文章</a>"
    )
    return message


async def send_notification(bot, chat_id: str, post: Dict[str, Any]) -> bool:
    """透過 Telegram Bot 發送單篇推播"""
    if bot is None:
        return False
    try:
        text = format_notification_html(post)
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )
        return True
    except Exception as e:
        logger.error(f"發送 Telegram 通知至 {chat_id} 失敗: {e}")
        return False


async def broadcast_notification(bot, post: Dict[str, Any]) -> bool:
    """發送推播通知給所有在 TELEGRAM_CHAT_ID 設定中的使用者"""
    if bot is None:
        logger.warning(f"Telegram Bot 尚未連線，跳過推播: {post.get('title')}")
        return False
    success = True
    for chat_id in config.telegram_chat_ids:
        sent = await send_notification(bot, chat_id, post)
        if not sent:
            success = False
    return success


def create_bot_application() -> Application:
    """建立並設定 Telegram Bot Application"""
    req_kwargs = {
        "connect_timeout": 15.0,
        "read_timeout": 15.0,
        "write_timeout": 15.0,
    }
    if config.telegram_proxy_url:
        req_kwargs["proxy"] = config.telegram_proxy_url
        logger.info(f"Telegram Bot 已配置代理: {config.telegram_proxy_url}")

    request = HTTPXRequest(**req_kwargs)
    builder = ApplicationBuilder().token(config.telegram_bot_token).request(request)

    app = builder.build()

    # 註冊指令處理器
    app.add_handler(CommandHandler(["start", "help"], help_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler(["del", "delete"], del_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("status", status_command))

    return app
