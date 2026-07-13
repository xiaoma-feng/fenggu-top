from __future__ import annotations

import json
import re
from datetime import datetime, time as datetime_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
LATEST_PATH = ROOT / "data" / "latest.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")
MARKET_DATA_READY_TIME = datetime_time(15, 30)
REQUIRED_LIMIT_UP_FIELDS = [
    "code",
    "name",
    "change_pct",
    "latest_price",
    "first_limit_time",
    "last_limit_time",
    "turnover_amount",
    "turnover_rate",
    "seal_amount",
    "consecutive_days",
    "open_times",
    "limit_stats",
    "market_board",
]
VALID_MARKET_BOARDS = {"主板", "创业板", "科创板", "北交所"}


def previous_business_day(day):
    current = day - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def latest_completed_trade_date(now):
    current = now.date()
    if current.weekday() >= 5:
        return previous_business_day(current)
    if now.time() < MARKET_DATA_READY_TIME:
        return previous_business_day(current)
    return current


def fail(message):
    raise SystemExit(f"data validation failed: {message}")


def main():
    if not LATEST_PATH.exists():
        fail("data/latest.json does not exist")

    payload = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    meta = payload.get("meta", {})
    sentiment = payload.get("sentiment", {})
    limit_ups = payload.get("limit_ups") or []

    if meta.get("data_status") != "ok":
        fail("meta.data_status is not ok")

    trade_date_text = meta.get("trade_date")
    if not trade_date_text:
        fail("meta.trade_date is empty")
    trade_date = datetime.strptime(trade_date_text, "%Y-%m-%d").date()
    completed_date = latest_completed_trade_date(datetime.now(SHANGHAI))
    if trade_date > completed_date:
        fail(f"trade date {trade_date_text} is later than completed date {completed_date}")

    broken_limits = payload.get("broken_limits") or []
    limit_downs = payload.get("limit_downs") or []
    if not any((limit_ups, broken_limits, limit_downs)):
        fail("all three market pools are empty")
    if int(sentiment.get("limit_up_count") or 0) != len(limit_ups):
        fail("sentiment.limit_up_count does not match limit_ups length")
    if int(sentiment.get("broken_limit_count") or 0) != len(payload.get("broken_limits") or []):
        fail("sentiment.broken_limit_count does not match broken_limits length")
    if int(sentiment.get("limit_down_count") or 0) != len(payload.get("limit_downs") or []):
        fail("sentiment.limit_down_count does not match limit_downs length")

    if limit_ups:
        first_stock = limit_ups[0]
        missing = [field for field in REQUIRED_LIMIT_UP_FIELDS if field not in first_stock]
        if missing:
            fail(f"first limit-up record is missing fields: {', '.join(missing)}")

    codes = [str(item.get("code") or "") for item in limit_ups]
    invalid_codes = [code for code in codes if not re.fullmatch(r"\d{6}", code)]
    if invalid_codes:
        fail(f"invalid stock codes: {', '.join(invalid_codes[:5])}")
    if len(codes) != len(set(codes)):
        fail("duplicate stock codes in limit_ups")

    missing_names = [item.get("code") for item in limit_ups if not item.get("name")]
    if missing_names:
        fail(f"limit-up records with missing names: {', '.join(missing_names[:5])}")

    invalid_boards = [item.get("code") for item in limit_ups if item.get("market_board") not in VALID_MARKET_BOARDS]
    if invalid_boards:
        fail(f"limit-up records with invalid market boards: {', '.join(invalid_boards[:5])}")

    highest_board = max([int(item.get("consecutive_days") or 1) for item in limit_ups] or [0])
    if int(sentiment.get("highest_board") or 0) != highest_board:
        fail("sentiment.highest_board does not match limit_ups")

    required_sections = ["limit_ups", "broken_limits", "limit_downs", "strong_stocks", "sub_new_stocks", "stats"]
    invalid_sections = [name for name in required_sections if not isinstance(payload.get(name), list)]
    if invalid_sections:
        fail(f"required sections are not arrays: {', '.join(invalid_sections)}")

    rankings = payload.get("rankings") or {}
    for key in ["industry_limit_rank", "theme_limit_rank", "market_board_limit_rank"]:
        if not isinstance(rankings.get(key), list):
            fail(f"rankings.{key} is not an array")

    print(
        "data validation ok: "
        f"trade_date={trade_date_text} "
        f"limit_ups={len(limit_ups)} "
        f"broken={len(payload.get('broken_limits') or [])} "
        f"stats={len(payload.get('stats') or [])}"
    )


if __name__ == "__main__":
    main()
