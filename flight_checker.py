"""
flight_checker.py
-----------------
星宇航空（台中 ⇄ 下地島）與中華航空（台北桃園 ⇄ 峇里島）雙人機票即時查詢模組。
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

AIRPORT_NAMES = {
    "RMQ": "台中",
    "TPE": "台北桃園",
    "TSA": "台北松山",
    "KHH": "高雄",
    "SHI": "下地島/宮古島",
    "DPS": "峇里島/登巴薩",
    "OKA": "沖繩那霸",
    "TAK": "日本高松",
}

TARGET_ROUTES = [
    # 1. 星宇航空 台中 ⇄ 下地島/宮古島
    {
        "departure": "RMQ",
        "arrival": "SHI",
        "outbound": "2027-03-06",
        "inbound": "2027-03-10",
        "note": "三月初梯次 (03/06~03/10)",
        "airline": "星宇航空",
        "preferred_kw": "STARLUX",
        "official_url": "https://www.starlux-airlines.com/zh-TW"
    },
    {
        "departure": "RMQ",
        "arrival": "SHI",
        "outbound": "2027-03-13",
        "inbound": "2027-03-17",
        "note": "三月中梯次 (03/13~03/17)",
        "airline": "星宇航空",
        "preferred_kw": "STARLUX",
        "official_url": "https://www.starlux-airlines.com/zh-TW"
    },
    # 2. 中華航空 台北桃園 ⇄ 峇里島/登巴薩
    {
        "departure": "TPE",
        "arrival": "DPS",
        "outbound": "2027-05-06",
        "inbound": "2027-05-11",
        "note": "五月初梯次 (05/06~05/11)",
        "airline": "中華航空",
        "preferred_kw": "CHINA AIRLINES",
        "official_url": "https://www.china-airlines.com/zh-tw"
    },
    {
        "departure": "TPE",
        "arrival": "DPS",
        "outbound": "2027-05-13",
        "inbound": "2027-05-18",
        "note": "五月中梯次 (05/13~05/18)",
        "airline": "中華航空",
        "preferred_kw": "CHINA AIRLINES",
        "official_url": "https://www.china-airlines.com/zh-tw"
    },
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
    """向 SerpApi 查詢宮古島與峇里島雙人票價並產出格式化卡片資料"""
    api_key = os.getenv("SERPAPI_KEY", DEFAULT_SERPAPI_KEY).strip()
    results = []

    for item in TARGET_ROUTES:
        dep = item["departure"]
        arr = item["arrival"]
        outbound = item["outbound"]
        inbound = item["inbound"]
        note = item["note"]
        airline = item["airline"]
        p_kw = item["preferred_kw"]
        official_url = item["official_url"]
        route_key = f"{dep}_{arr}_{airline}_{outbound}_{inbound}"

        params = {
            "engine": "google_flights",
            "departure_id": dep,
            "arrival_id": arr,
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
                    "error": f"查無當日航班資訊（{airline} 可能未開航此日期或已售罄）",
                    "departure": dep,
                    "arrival": arr,
                    "outbound": outbound,
                    "inbound": inbound,
                    "note": note,
                    "airline": airline
                })
                continue

            # 依偏好航司過濾
            matched_flights = []
            for f in all_flights:
                legs = f.get("flights", [])
                airline_names = [leg.get("airline", "") for leg in legs]
                airline_str = " / ".join(airline_names).upper()
                flight_nos = " / ".join([leg.get("flight_number", "") for leg in legs]).upper()

                if p_kw in airline_str or p_kw in flight_nos:
                    matched_flights.append(f)
                elif "星宇" in airline and ("星宇" in airline_str or "JX" in flight_nos):
                    matched_flights.append(f)
                elif "華航" in airline or "中華" in airline:
                    if "中華" in airline_str or "CI" in flight_nos or "CHINA AIRLINES" in airline_str:
                        matched_flights.append(f)

            target_flight = matched_flights[0] if matched_flights else all_flights[0]
            curr_total = float(target_flight.get("price", 0))
            if curr_total <= 0:
                results.append({
                    "success": False,
                    "error": "未能提取有效票價",
                    "departure": dep,
                    "arrival": arr,
                    "outbound": outbound,
                    "inbound": inbound,
                    "note": note,
                    "airline": airline
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

            booking_url = target_flight.get("booking_url") or official_url
            now_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            dep_name = AIRPORT_NAMES.get(dep, dep)
            arr_name = AIRPORT_NAMES.get(arr, arr)

            card_html = (
                f"🎉 <b>【機票價格通知・{airline}】</b>\n\n"
                f"📍 <b>航線：</b>{dep_name} (<code>{dep}</code>) ⇄ {arr_name} (<code>{arr}</code>)\n"
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
                "booking_url": booking_url,
                "btn_text": f"✈️ 前往{airline}官網查票/訂位"
            })

        except Exception as e:
            logger.error(f"查詢機票異常 ({dep}->{arr} {outbound}~{inbound}): {e}", exc_info=True)
            results.append({
                "success": False,
                "error": str(e),
                "departure": dep,
                "arrival": arr,
                "outbound": outbound,
                "inbound": inbound,
                "note": note,
                "airline": airline
            })

    return results
