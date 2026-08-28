"""
flight_checker.py
-----------------
星宇航空（台中 RMQ ⇄ 下地島 SHI）雙人機票即時查詢模組。
無縫整合於 PTT / Dcard 推播監控機器人中。
"""

import os
import html
import logging
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List
import requests

logger = logging.getLogger("PTTMonitor.FlightChecker")

# 預設監控設定
DEFAULT_SERPAPI_KEY = "677373e0cf225645df8d772f91167c48ae3fee661923f0fecd56c45b683519d0"
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"

TARGET_DATES = [
    {"outbound": "2027-03-06", "inbound": "2027-03-10", "note": "三月初梯次 (03/06~03/10)"},
    {"outbound": "2027-03-13", "inbound": "2027-03-17", "note": "三月中梯次 (03/13~03/17)"}
]


def _get_db_conn():
    conn = sqlite3.connect("flight_prices.db", timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_key TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT NOT NULL,
            checked_at TIMESTAMP NOT NULL
        );
    """)
    conn.commit()
    return conn


def _get_latest_and_lowest_price(route_key: str):
    """查詢上次價格與歷史最低價"""
    with _get_db_conn() as conn:
        cursor = conn.cursor()
        # 上次價格
        cursor.execute(
            "SELECT price FROM price_history WHERE route_key = ? ORDER BY checked_at DESC, id DESC LIMIT 1;",
            (route_key,)
        )
        row = cursor.fetchone()
        prev_price = float(row["price"]) if row else None

        # 歷史最低價
        cursor.execute(
            "SELECT MIN(price) AS min_price FROM price_history WHERE route_key = ?;",
            (route_key,)
        )
        row_min = cursor.fetchone()
        min_price = float(row_min["min_price"]) if row_min and row_min["min_price"] is not None else None

        return prev_price, min_price


def _save_price(route_key: str, price: float, currency: str = "TWD"):
    with _get_db_conn() as conn:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO price_history (route_key, price, currency, checked_at) VALUES (?, ?, ?, ?);",
            (route_key, price, currency, now_str)
        )
        conn.commit()


def fetch_starlux_flights_sync() -> List[Dict[str, Any]]:
    """向 SerpApi 查詢星宇航空雙人票價並產出格式化卡片資料"""
    api_key = os.getenv("SERPAPI_KEY", DEFAULT_SERPAPI_KEY).strip()
    results = []

    for item in TARGET_DATES:
        outbound = item["outbound"]
        inbound = item["inbound"]
        note = item["note"]
        route_key = f"RMQ_SHI_{outbound}_{inbound}"

        params = {
            "engine": "google_flights",
            "departure_id": "RMQ",
            "arrival_id": "SHI",
            "outbound_date": outbound,
            "return_date": inbound,
            "currency": "TWD",
            "adults": 2,
            "hl": "zh-TW",
            "gl": "tw",
            "api_key": api_key
        }

        try:
            resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=15)
            data = resp.json()

            all_flights = []
            if "best_flights" in data and isinstance(data["best_flights"], list):
                all_flights.extend(data["best_flights"])
            if "other_flights" in data and isinstance(data["other_flights"], list):
                all_flights.extend(data["other_flights"])

            if not all_flights:
                results.append({
                    "success": False,
                    "error": "查無當日航班資訊（星宇可能未開航此日期或已售罄）",
                    "outbound": outbound,
                    "inbound": inbound,
                    "note": note
                })
                continue

            # 優先找星宇
            starlux_flights = []
            for f in all_flights:
                legs = f.get("flights", [])
                airline_names = [leg.get("airline", "") for leg in legs]
                airline_str = " / ".join(airline_names)
                if "星宇" in airline_str or "STARLUX" in airline_str.upper() or "JX" in str(legs):
                    starlux_flights.append(f)

            target_flight = starlux_flights[0] if starlux_flights else all_flights[0]
            curr_total = float(target_flight.get("price", 0))
            if curr_total <= 0:
                results.append({
                    "success": False,
                    "error": "未能提取有效票價",
                    "outbound": outbound,
                    "inbound": inbound,
                    "note": note
                })
                continue

            # 比對歷史
            prev_total, lowest_total = _get_latest_and_lowest_price(route_key)
            _save_price(route_key, curr_total, "TWD")

            curr_pp = curr_total / 2.0
            if prev_total is not None:
                diff_amount = curr_total - prev_total
                diff_pct = (diff_amount / prev_total) * 100.0
                prev_total_str = f" <i>(上次：TWD {prev_total:,.0f})</i>"
                prev_pp_str = f" <i>(上次：TWD {prev_total / 2.0:,.0f})</i>"
                if diff_amount < 0:
                    change_str = f"📉 <b>跌 {abs(diff_amount):,.0f} TWD</b> (<code>{diff_pct:+.1f}%</code>)"
                elif diff_amount > 0:
                    change_str = f"🔺 <b>漲 {abs(diff_amount):,.0f} TWD</b> (<code>{diff_pct:+.1f}%</code>)"
                else:
                    change_str = "⚪ 與上次持平無變動"
            else:
                prev_total_str = " <i>(首次記錄)</i>"
                prev_pp_str = " <i>(首次記錄)</i>"
                change_str = "🛰 首次建立基準價格"

            # 歷史低價
            lowest_bench = lowest_total or curr_total
            if curr_total <= lowest_bench:
                lowest_str = f"<code>TWD {lowest_bench:,.0f}</code> 🔥 <b>(目前即為歷史最低！)</b>"
            else:
                diff_low = curr_total - lowest_bench
                pct_low = (diff_low / lowest_bench) * 100.0 if lowest_bench > 0 else 0
                lowest_str = f"<code>TWD {lowest_bench:,.0f}</code> <i>(距低點 +{diff_low:,.0f} / +{pct_low:.1f}%)</i>"

            booking_url = target_flight.get("booking_url") or "https://www.starlux-airlines.com/zh-TW"
            now_time = datetime.now().strftime("%Y-%m-%d %H:%M")

            card_html = (
                f"🎉 <b>【星宇航空・雙人機票即時回報】</b>\n\n"
                f"📍 <b>航線：</b>台中 (<code>RMQ</code>) ⇄ 下地島/宮古島 (<code>SHI</code>)\n"
                f"📅 <b>日期：</b>{outbound} ⇄ {inbound} ({html.escape(note)})\n\n"
                f"💵 <b>雙人總價：</b><code>TWD {curr_total:,.0f}</code>{prev_total_str}\n"
                f"👤 <b>平均每人：</b><code>TWD {curr_pp:,.0f}</code>{prev_pp_str}\n"
                f"📊 <b>較上次查詢：</b>{change_str}\n"
                f"🏆 <b>歷史最低價：</b>{lowest_str}\n"
                f"⏱ <b>查詢時間：</b>{now_time}"
            )

            results.append({
                "success": True,
                "html": card_html,
                "booking_url": booking_url
            })

        except Exception as e:
            logger.error(f"查詢機票異常 ({outbound}~{inbound}): {e}", exc_info=True)
            results.append({
                "success": False,
                "error": str(e),
                "outbound": outbound,
                "inbound": inbound,
                "note": note
            })

    return results
