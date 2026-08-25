import html
import functools
import logging
from typing import Optional, Dict, Any, List
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
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


# ==========================================
# 核心指令處理邏輯 (支援繁體中文文字與 Slash 指令)
# ==========================================

@authorized_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 指令 / 說明 / /help"""
    help_text = (
        "🤖 <b>PTT 看板條件監控機器人 指令選單</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>【關鍵字管理】</b>\n"
        "🔹 <code>新增關鍵字 &lt;看板&gt; &lt;關鍵字&gt;</code>\n"
        "   👉 新增該看板的監控關鍵字（支援多組逗號分隔）\n"
        "   範例：<code>新增關鍵字 Stock 台積電,聯發科</code>\n\n"
        "🔹 <code>刪除關鍵字 &lt;看板&gt; &lt;關鍵字&gt;</code>\n"
        "   👉 刪除該看板的指定關鍵字\n"
        "   範例：<code>刪除關鍵字 Stock 台積電</code>\n\n"
        "📌 <b>【推文數門檻管理】</b>\n"
        "🔹 <code>新增推文數 &lt;看板&gt; &lt;推文數&gt;</code>\n"
        "   👉 設定該看板達到多少推文（或爆文）才推播\n"
        "   範例：<code>新增推文數 Stock 50</code>\n"
        "   範例：<code>新增推文數 Gossiping 80</code>\n\n"
        "🔹 <code>刪除推文數 &lt;看板&gt;</code>\n"
        "   👉 移除該看板的推文數門檻監控\n"
        "   範例：<code>刪除推文數 Stock</code>\n\n"
        "📌 <b>【清單與狀態查詢】</b>\n"
        "🔹 <code>清單</code>\n"
        "   👉 顯示所有監控看板的關鍵字與推文數設定\n\n"
        "🔹 <code>狀態</code>\n"
        "   👉 查詢系統運行狀態（運行中 / 暫停中）與推播統計\n\n"
        "📌 <b>【監控開關】</b>\n"
        "🔹 <code>停止監控</code> 👉 暫停推播與爬蟲\n"
        "🔹 <code>開始監控</code> 👉 開始/恢復即時監控\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>直接在聊天室發送中文文字即可，不需加斜線 /！</i>"
    )
    if update.effective_message:
        await update.effective_message.reply_text(help_text, parse_mode=ParseMode.HTML)


@authorized_only
async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 清單 / /list"""
    boards_config = db.get_all_monitored_boards_config()
    is_paused = db.is_monitoring_paused()

    status_tag = "⏸️ <b>[監控目前處於暫停狀態]</b>\n\n" if is_paused else "🟢 <b>[監控正常運行中]</b>\n\n"

    if not boards_config:
        msg = (
            f"{status_tag}"
            "📭 <b>目前沒有任何受監控的看板與條件。</b>\n\n"
            "💡 可使用以下指令開始監控：\n"
            "• <code>新增關鍵字 Stock 台積電</code>\n"
            "• <code>新增推文數 Gossiping 80</code>"
        )
    else:
        content_lines = []
        for idx, (board, cfg) in enumerate(boards_config.items(), 1):
            kws = cfg.get("keywords", [])
            min_push = cfg.get("min_push_count", 0)

            kw_text = ", ".join([f"<code>{html.escape(k)}</code>" for k in kws]) if kws else "<i>(未設定)</i>"
            push_text = f"<b>{min_push} 推 / 爆</b>" if min_push > 0 else "<i>(未設定)</i>"

            block = (
                f"🏷️ <b>{idx}. 看板：{html.escape(board)}</b>\n"
                f"   🎯 關鍵字：{kw_text}\n"
                f"   🔥 推文門檻：{push_text}"
            )
            content_lines.append(block)

        msg = (
            f"{status_tag}"
            f"📋 <b>目前監控看板清單（共 {len(boards_config)} 個看板）：</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            + "\n\n".join(content_lines)
            + "\n━━━━━━━━━━━━━━━━━━━━\n"
            "💡 提示：只要看板設有關鍵字或推文數，系統就會自動排程監控！"
        )

    if update.effective_message:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


@authorized_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 狀態 / /status"""
    stats = db.get_stats()
    is_paused = stats["is_paused"]
    boards_list = ", ".join(stats["monitored_boards"]) if stats["monitored_boards"] else "無"

    state_text = "⏸️ <b>已暫停監控</b>（不會發送推播）" if is_paused else "🟢 <b>監控中（正常運作）</b>"

    msg = (
        "📊 <b>系統運作狀態回報</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>運作狀態：</b> {state_text}\n"
        f"📌 <b>監控看板清單：</b> {boards_list}\n"
        f"🏷️ <b>總監控看板數：</b> {stats['monitored_boards_count']} 個\n"
        f"🎯 <b>總關鍵字設定數：</b> {stats['total_keywords_count']} 組\n"
        f"📬 <b>歷史推播總數：</b> {stats['total_notified_posts']} 篇\n"
        f"⏱️ <b>輪詢間隔：</b> {config.poll_interval_min_sec} ~ {config.poll_interval_max_sec} 秒\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>發送「清單」可查看各看板詳細設定規則</i>"
    )
    if update.effective_message:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


@authorized_only
async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 停止監控 / 暫停"""
    db.set_monitoring_paused(True)
    logger.info("使用者設定暫停監控。")
    msg = (
        "⏸️ <b>系統已停止監控！</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "爬蟲已暫停輪詢，將不會發送任何推播通知。\n"
        "隨時發送 <b>開始監控</b> 即可恢復即時推播！"
    )
    if update.effective_message:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


@authorized_only
async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """處理 開始監控 / 恢復"""
    db.set_monitoring_paused(False)
    logger.info("使用者設定開始/恢復監控。")
    msg = (
        "🟢 <b>系統已開始即時監控！</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "爬蟲已重新開始輪詢各看板最新文章。\n"
        "有符合條件的新文章將立即發送推播！"
    )
    if update.effective_message:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


# ==========================================
# 看板條件設定指令
# ==========================================

@authorized_only
async def handle_add_keyword_text(update: Update, board: str, keyword: str) -> None:
    """處理 新增關鍵字 <看板> <關鍵字>"""
    if not board or not keyword:
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ <b>格式錯誤</b>\n用法範例：<code>新增關鍵字 Stock 台積電</code> 或 <code>新增關鍵字 Stock 台積電,聯發科</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    added = db.add_board_keyword(board, keyword)
    b_name = db.canonicalize_board_name(board)

    if added:
        kws_str = ", ".join([f"<b>{html.escape(k)}</b>" for k in added])
        msg = f"✅ 已成功為 <b>【{html.escape(b_name)}】</b> 看板新增關鍵字：{kws_str}\n\n💡 下一輪爬蟲將自動納入監控！"
    else:
        msg = f"ℹ️ 關鍵字已在 <b>【{html.escape(b_name)}】</b> 看板監控中，無需重複新增。"

    if update.effective_message:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


@authorized_only
async def handle_del_keyword_text(update: Update, board: str, keyword: str) -> None:
    """處理 刪除關鍵字 <看板> <關鍵字>"""
    if not board or not keyword:
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ <b>格式錯誤</b>\n用法範例：<code>刪除關鍵字 Stock 台積電</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    deleted = db.delete_board_keyword(board, keyword)
    b_name = db.canonicalize_board_name(board)

    if deleted:
        kws_str = ", ".join([f"<b>{html.escape(k)}</b>" for k in deleted])
        msg = f"🗑️ 已成功從 <b>【{html.escape(b_name)}】</b> 看板刪除關鍵字：{kws_str}"
    else:
        msg = f"⚠️ 在 <b>【{html.escape(b_name)}】</b> 看板中找不到指定的關鍵字，請輸入「清單」確認。"

    if update.effective_message:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


@authorized_only
async def handle_add_push_text(update: Update, board: str, push_str: str) -> None:
    """處理 新增推文數 <看板> <推文數>"""
    if not board or not push_str:
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ <b>格式錯誤</b>\n用法範例：<code>新增推文數 Stock 50</code> 或 <code>新增推文數 Gossiping 80</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    try:
        push_count = int(push_str.strip())
        if push_count <= 0:
            raise ValueError()
    except ValueError:
        if update.effective_message:
            await update.effective_message.reply_text("⚠️ 推文數門檻必須為大於 0 的整數數字！（例如 50、80、100）")
        return

    db.set_board_min_push(board, push_count)
    b_name = db.canonicalize_board_name(board)
    msg = f"🔥 已成功設定 <b>【{html.escape(b_name)}】</b> 看板推文門檻為 <b>{push_count} 推（或爆文）</b>！\n\n💡 只要達標將即時推播！"

    if update.effective_message:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


@authorized_only
async def handle_del_push_text(update: Update, board: str) -> None:
    """處理 刪除推文數 <看板> [推文數]"""
    if not board:
        if update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ <b>格式錯誤</b>\n用法範例：<code>刪除推文數 Stock</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    success = db.delete_board_min_push(board)
    b_name = db.canonicalize_board_name(board)

    if success:
        msg = f"🗑️ 已成功清除 <b>【{html.escape(b_name)}】</b> 看板的推文數門檻監控！"
    else:
        msg = f"ℹ️ <b>【{html.escape(b_name)}】</b> 看板原本就未設定推文門檻。"

    if update.effective_message:
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


# ==========================================
# 中文自然語言訊息分流處理器
# ==========================================

@authorized_only
async def text_message_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """攔截使用者發送的一般中文純文字，進行語意解析與分流"""
    if not update.effective_message or not update.effective_message.text:
        return

    raw_text = update.effective_message.text.strip()

    # 1. 指令 / 說明
    if raw_text in ("指令", "說明", "幫助", "選單", "/help", "/start", "?", "？"):
        await help_command(update, context)
        return

    # 2. 清單 / 查詢
    if raw_text in ("清單", "監控清單", "查詢", "關鍵字", "/list"):
        await list_command(update, context)
        return

    # 3. 狀態
    if raw_text in ("狀態", "系統狀態", "/status"):
        await status_command(update, context)
        return

    # 4. 停止監控 / 暫停
    if raw_text in ("停止監控", "暫停監控", "暫停", "/pause"):
        await pause_command(update, context)
        return

    # 5. 開始監控 / 恢復
    if raw_text in ("開始監控", "恢復監控", "開始", "恢復", "/resume"):
        await resume_command(update, context)
        return

    # 6. 新增關鍵字 <看板> <關鍵字>
    if raw_text.startswith("新增關鍵字") or raw_text.startswith("+關鍵字") or raw_text.startswith("+關鍵"):
        parts = raw_text.split(None, 2)
        if len(parts) >= 3:
            board = parts[1].strip()
            keyword = parts[2].strip()
            await handle_add_keyword_text(update, board, keyword)
        elif len(parts) == 2 and "," in parts[1]:
            # 兼容：新增關鍵字 Stock,台積電
            sub_parts = parts[1].split(",", 1)
            await handle_add_keyword_text(update, sub_parts[0], sub_parts[1])
        else:
            await update.effective_message.reply_text(
                "⚠️ <b>格式範例：</b><code>新增關鍵字 Stock 台積電</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    # 7. 刪除關鍵字 <看板> <關鍵字>
    if raw_text.startswith("刪除關鍵字") or raw_text.startswith("-關鍵字") or raw_text.startswith("-關鍵"):
        parts = raw_text.split(None, 2)
        if len(parts) >= 3:
            board = parts[1].strip()
            keyword = parts[2].strip()
            await handle_del_keyword_text(update, board, keyword)
        else:
            await update.effective_message.reply_text(
                "⚠️ <b>格式範例：</b><code>刪除關鍵字 Stock 台積電</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    # 8. 新增推文數 / 設定推文數 <看板> <推文數>
    if raw_text.startswith("新增推文數") or raw_text.startswith("設定推文數") or raw_text.startswith("+推文數"):
        parts = raw_text.split(None, 2)
        if len(parts) >= 3:
            board = parts[1].strip()
            push_str = parts[2].strip()
            await handle_add_push_text(update, board, push_str)
        else:
            await update.effective_message.reply_text(
                "⚠️ <b>格式範例：</b><code>新增推文數 Stock 50</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    # 9. 刪除推文數 <看板> [推文數]
    if raw_text.startswith("刪除推文數") or raw_text.startswith("-推文數") or raw_text.startswith("取消推文數"):
        parts = raw_text.split()
        if len(parts) >= 2:
            board = parts[1].strip()
            await handle_del_push_text(update, board)
        else:
            await update.effective_message.reply_text(
                "⚠️ <b>格式範例：</b><code>刪除推文數 Stock</code>",
                parse_mode=ParseMode.HTML,
            )
        return

    # 未識別的中文自然指令
    await update.effective_message.reply_text(
        f"🤔 無法識別的指令：<b>{html.escape(raw_text)}</b>\n\n"
        "💡 請輸入 <b>指令</b> 查看所有支援的功能，例如：\n"
        "• <code>新增關鍵字 Stock 台積電</code>\n"
        "• <code>新增推文數 Gossiping 80</code>\n"
        "• <code>清單</code>\n"
        "• <code>狀態</code>",
        parse_mode=ParseMode.HTML,
    )


# ==========================================
# 推播 HTML 格式化與發送
# ==========================================

def format_notification_html(post: Dict[str, Any]) -> str:
    """產生推播訊息格式"""
    platform = html.escape(str(post.get("platform", "PTT")))
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

    # 1. 註冊斜線指令處理器
    app.add_handler(CommandHandler(["start", "help"], help_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("pause", pause_command))
    app.add_handler(CommandHandler("resume", resume_command))

    # 2. 註冊純文字自然語言分流處理器（支援所有中文輸入指令）
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_dispatcher))

    return app
