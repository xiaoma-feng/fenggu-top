from __future__ import annotations

import json
from datetime import datetime, time as datetime_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
LATEST_PATH = ROOT / "data" / "latest.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")
MARKET_DATA_READY_TIME = datetime_time(15, 30)
MIN_LIMIT_UP_COUNT = 10
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
]


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

    if len(limit_ups) < MIN_LIMIT_UP_COUNT:
        fail(f"limit-up count {len(limit_ups)} is below {MIN_LIMIT_UP_COUNT}")
    if int(sentiment.get("limit_up_count") or 0) != len(limit_ups):
        fail("sentiment.limit_up_count does not match limit_ups length")

    first_stock = limit_ups[0]
    missing = [field for field in REQUIRED_LIMIT_UP_FIELDS if field not in first_stock]
    if missing:
        fail(f"first limit-up record is missing fields: {', '.join(missing)}")

    required_sections = ["broken_limits", "limit_downs", "strong_stocks", "sub_new_stocks", "stats"]
    empty_sections = [name for name in required_sections if not payload.get(name)]
    if empty_sections:
        fail(f"empty required sections: {', '.join(empty_sections)}")

    print(
        "data validation ok: "
        f"trade_date={trade_date_text} "
        f"limit_ups={len(limit_ups)} "
        f"broken={len(payload.get('broken_limits') or [])} "
        f"stats={len(payload.get('stats') or [])}"
    )


if __name__ == "__main__":
    main()
