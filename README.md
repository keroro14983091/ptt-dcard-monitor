# 📡 PTT 與 Dcard 關鍵字 / 爆文自動監控與 Telegram 雙向控制推播系統 (Python 版)

一套專為 PTT 與 Dcard 設計的高可靠度、非同步 Python 自動監控推播服務。定時輪詢指定看板（如 PTT Stock、Lifeismoney、Gossiping；Dcard 股市板、科技業板等），即時進行關鍵字比對與推讚數門檻判定，透過 SQLite 實現動態關鍵字管理與零重複推播（O(1) 去重索引），並提供 Telegram Bot 雙向指令互動（隨時新增/刪除/查詢關鍵字，無需重啟程式即時生效）與排版精美的 HTML 即時推播。

---

## 🌟 核心功能與特色

1. **動態關鍵字與 SQLite 去重管理 (`database.py`)**：
   - 建立 `keywords` 資料表：儲存目前監控中的關鍵字 (`keyword TEXT PRIMARY KEY, created_at TIMESTAMP`)。
   - 建立 `notified_posts` 資料表：記錄已推播過的文章 (`platform, post_id, title, url, board, reason, created_at`)，保證絕不重複推播。
   - 支援初始預設關鍵字（若資料庫為空時自動寫入「台積電、美股、優惠、買一送一、分紅」等預設詞）。
   - 爬蟲輪詢時動態從 SQLite 撈取最新關鍵字，修改即刻生效。

2. **Telegram 雙向互動與指令控制 (`bot_handler.py`)**：
   - **權限驗證保護**：嚴格驗證 `TELEGRAM_CHAT_ID`，非授權使用者無法操作指令。
   - **支援指令**：
     * `/add <關鍵字>` ：新增監控關鍵字到 SQLite 資料庫。
     * `/del <關鍵字>` ：從 SQLite 刪除指定關鍵字。
     * `/list` ：列出目前資料庫中所有監控中的關鍵字與數量。
     * `/status` ：查看系統運作狀態、監控看板與推播統計。
     * `/help` ：顯示指令使用說明。
   - 採用 `python-telegram-bot` (v20+ 非同步架構) 進行長輪詢監聽。

3. **PTT 爬蟲與爆文判定 (`crawlers/ptt.py`)**：
   - 自動帶入 18 歲年齡確認 Cookie (`over18=1`)，暢行 Gossiping、Stock、Lifeismoney 等所有看板。
   - 解析推文數（支援「爆」、數值推數、負分噓文）、標題、作者與文章超連結。
   - 同步支援「動態關鍵字比對」與「爆文 / 推文門檻比對」。

4. **Dcard 官方 API 爬蟲 (`crawlers/dcard.py`)**：
   - 呼叫 Dcard 公開 API 抓取最新看板文章。
   - 解析標題、內文摘要與按讚數 (`likeCount`)。
   - 支援標題/摘要關鍵字比對與熱門讚數門檻比對。
   - 具備 Cookie 與 Proxy 選填擴充能力。

5. **即時 HTML 推播格式**：
   ```html
   🚨<b>【PTT Stock 觸發通知】</b>

   📌 <b>標題：</b>[標的] 2330 台積電 多
   🎯 <b>觸發原因：</b>符合關鍵字 [台積電]、爆文達成 (100+ 推)
   🔗 <b>連結：</b><a href="...">點此開啟文章</a>
   ```

---

## 📁 檔案結構

```
.
├── crawlers/
│   ├── __init__.py
│   ├── ptt.py              # PTT 爬蟲與過濾邏輯
│   └── dcard.py            # Dcard API 爬蟲與過濾邏輯
├── tests/
│   └── test_system.py      # 自動化單元測試
├── data/
│   └── monitor.db          # SQLite 本地資料庫
├── .env.example            # 環境變數範本
├── .env                    # 本機環境變數設定
├── config.py               # 讀取與驗證環境變數、Logging 設定
├── database.py             # SQLite 資料庫 CRUD 操作
├── bot_handler.py          # Telegram Bot 指令處理與推播發送
├── main.py                 # 主程式入口 (非同步併發 Telegram 與爬蟲任務)
└── requirements.txt        # Python 依賴清單
```

---

## 🚀 快速開始

### 1. 安裝 Python 環境與套件
請確保 Python 版本 `>= 3.9`：
```bash
pip install -r requirements.txt
```

### 2. 設定環境變數 (`.env`)
複製 `.env.example` 為 `.env`，並填入您的 Telegram Bot Token 與 Chat ID：

```ini
# Telegram Bot 設定 (必填)
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=123456789

# 監控看板與關鍵字設定
PTT_BOARDS=Stock,Lifeismoney,Gossiping
DCARD_BOARDS=stock,tech_job
DEFAULT_KEYWORDS=台積電,美股,優惠,買一送一,分紅

# 爆文與熱門門檻設定
PTT_MIN_PUSH_COUNT=50
DCARD_MIN_LIKE_COUNT=50

# 爬蟲輪詢設定 (秒)
POLL_INTERVAL_MIN_SEC=30
POLL_INTERVAL_MAX_SEC=60

# 系統與資料庫設定
LOG_LEVEL=INFO
DB_PATH=./data/monitor.db
```

> **💡 如何取得 Telegram Bot Token 與 Chat ID？**
> 1. 在 Telegram 搜尋 `@BotFather`，發送 `/newbot` 依提示建立機器人，即可取得 `TELEGRAM_BOT_TOKEN`。
> 2. 向您的機器人發送任意訊息。
> 3. 在 Telegram 搜尋 `@userinfobot` 或 `@getidsbot` 即可查詢您的 `TELEGRAM_CHAT_ID`。

### 3. 啟動監控服務
```bash
python main.py
```

---

## 🤖 Telegram Bot 指令使用說明

在 Telegram 聊天視窗中可直接對機器人發送以下指令：

| 指令 | 說明 | 範例 |
| :--- | :--- | :--- |
| `/add <關鍵字>` | 新增監控關鍵字（即時生效） | `/add 輝達` |
| `/del <關鍵字>` | 刪除指定監控關鍵字 | `/del 輝達` |
| `/list` | 列出目前所有監控中的關鍵字 | `/list` |
| `/status` | 顯示系統運作狀態、監控看板與推播總數 | `/status` |
| `/help` | 顯示所有指令說明選單 | `/help` |

---

## 🧪 執行自動化測試

```bash
python -m unittest tests/test_system.py
```
測試涵蓋：
- SQLite 資料庫新增、刪除、查詢關鍵字與去重紀錄功能
- PTT 關鍵字比對、推文數與爆文判定邏輯
- Dcard 關鍵字比對與熱門按讚數過濾邏輯
- HTML 推播特殊字元轉義與格式化防破版驗證
