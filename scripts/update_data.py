from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def clean_value(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return clean_value(value.item())
    return value


def as_text(value):
    value = clean_value(value)
    if value is None:
        return ""
    return str(value).strip()


def as_number(value, fallback=0):
    value = clean_value(value)
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return value
    text = str(value).replace(",", "").strip()
    if not text or text == "-":
        return fallback
    multiplier = 1
    if text.endswith("亿"):
        multiplier = 100000000
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10000
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return fallback


def as_int(value, fallback=0):
    return int(as_number(value, fallback))


def pick(row, names, fallback=None):
    for name in names:
        if name in row and clean_value(row[name]) is not None:
            return row[name]
    return fallback


def normalize_time(value):
    text = as_text(value)
    if not text:
        return ""
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2:
            return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:00"
        if len(parts) == 3:
            return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:{parts[2].zfill(2)}"
    digits = re.sub(r"\D", "", text)
    if len(digits) <= 6 and digits:
        digits = digits.zfill(6)
        return f"{digits[:2]}:{digits[2:4]}:{digits[4:6]}"
    return text


def parse_consecutive(row):
    direct = pick(row, ["连板数", "连板", "连续涨停天数"])
    if direct is not None:
        return max(1, as_int(direct, 1))
    text = as_text(pick(row, ["涨停统计", "涨停封板结构", "封板结构"], ""))
    match = re.search(r"(\d+)\s*板", text)
    if match:
        return max(1, int(match.group(1)))
    return 1


def frame_records(df):
    if df is None or df.empty:
        return []
    return [{key: clean_value(value) for key, value in row.items()} for row in df.to_dict("records")]


def call_akshare(name, *args, **kwargs):
    try:
        import akshare as ak
    except ImportError:
        return pd.DataFrame()

    func = getattr(ak, name, None)
    if func is None:
        return pd.DataFrame()
    try:
        return func(*args, **kwargs)
    except TypeError:
        try:
            return func(*args)
        except Exception:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def fetch_limit_ups(trade_date):
    raw = call_akshare("stock_zt_pool_em", date=trade_date)
    rows = []
    for row in frame_records(raw):
        rows.append(
            {
                "code": as_text(pick(row, ["代码", "股票代码", "证券代码"])).zfill(6),
                "name": as_text(pick(row, ["名称", "股票简称", "股票名称"])),
                "first_limit_time": normalize_time(pick(row, ["首次封板时间", "首次涨停时间"])),
                "last_limit_time": normalize_time(pick(row, ["最后封板时间", "最终封板时间"])),
                "concept": as_text(pick(row, ["所属概念", "涨停原因类别", "概念"], "")),
                "industry": as_text(pick(row, ["所属行业", "行业"], "")),
                "seal_amount": as_number(pick(row, ["封板资金", "封单资金", "封单金额"], 0)),
                "consecutive_days": parse_consecutive(row),
                "open_times": as_int(pick(row, ["炸板次数", "打开次数"], 0)),
                "reason": as_text(pick(row, ["涨停原因", "涨停原因类别", "原因"], "")),
            }
        )
    return [row for row in rows if row["code"] and row["name"]]


def fetch_broken_limits(trade_date):
    raw = call_akshare("stock_zt_pool_zbgc_em", date=trade_date)
    rows = []
    for row in frame_records(raw):
        rows.append(
            {
                "code": as_text(pick(row, ["代码", "股票代码", "证券代码"])).zfill(6),
                "name": as_text(pick(row, ["名称", "股票简称", "股票名称"])),
                "concept": as_text(pick(row, ["所属行业", "所属概念", "概念"], "")),
                "reason": as_text(pick(row, ["炸板原因", "原因", "涨停原因"], "炸板观察")),
            }
        )
    return [row for row in rows if row["code"] and row["name"]]


def fetch_limit_down_count(trade_date):
    for func_name in ["stock_zt_pool_dtgc_em", "stock_zt_pool_dtdp_em"]:
        raw = call_akshare(func_name, date=trade_date)
        if raw is not None and not raw.empty:
            return len(raw)
    return 0


def load_history():
    records = []
    for path in sorted(HISTORY_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        trade_date = payload.get("meta", {}).get("trade_date") or path.stem
        for stock in payload.get("limit_ups", []):
            records.append(
                {
                    "trade_date": trade_date,
                    "code": stock.get("code"),
                    "name": stock.get("name"),
                    "consecutive_days": as_int(stock.get("consecutive_days"), 1),
                }
            )
    return records


def build_stats(limit_ups, trade_date):
    history = load_history()
    existing_keys = {(item["trade_date"], item["code"]) for item in history}
    for stock in limit_ups:
        key = (trade_date, stock["code"])
        if key not in existing_keys:
            history.append(
                {
                    "trade_date": trade_date,
                    "code": stock["code"],
                    "name": stock["name"],
                    "consecutive_days": as_int(stock.get("consecutive_days"), 1),
                }
            )

    target_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
    stats = []
    for stock in limit_ups:
        code = stock["code"]
        rows = [item for item in history if item["code"] == code]
        dates = [datetime.strptime(item["trade_date"], "%Y-%m-%d").date() for item in rows]
        stats.append(
            {
                "code": code,
                "name": stock["name"],
                "limit_count_7d": sum(day >= target_date - timedelta(days=7) for day in dates),
                "limit_count_30d": sum(day >= target_date - timedelta(days=30) for day in dates),
                "limit_count_1y": sum(day >= target_date - timedelta(days=365) for day in dates),
                "total_limit_count": len(rows),
                "max_consecutive_days": max([as_int(item.get("consecutive_days"), 1) for item in rows] or [1]),
                "last_limit_date": max([item["trade_date"] for item in rows], default=trade_date),
            }
        )
    return stats


def build_payload(trade_date_arg=None):
    now = datetime.now(SHANGHAI)
    trade_date = trade_date_arg or now.strftime("%Y-%m-%d")
    ak_date = trade_date.replace("-", "")

    limit_ups = fetch_limit_ups(ak_date)
    broken_limits = fetch_broken_limits(ak_date)
    limit_down_count = fetch_limit_down_count(ak_date)
    highest_board = max([as_int(item.get("consecutive_days"), 1) for item in limit_ups] or [0])
    broken_count = len(broken_limits)
    total_for_rate = len(limit_ups) + broken_count

    return {
        "meta": {
            "site_name": "峰股top",
            "trade_date": trade_date,
            "updated_at": now.strftime("%Y-%m-%d %H:%M"),
            "source": "akshare",
        },
        "sentiment": {
            "limit_up_count": len(limit_ups),
            "limit_down_count": limit_down_count,
            "broken_limit_count": broken_count,
            "highest_board": highest_board,
            "broken_rate": round((broken_count / total_for_rate) * 100, 2) if total_for_rate else 0,
        },
        "limit_ups": limit_ups,
        "broken_limits": broken_limits,
        "stats": build_stats(limit_ups, trade_date),
    }


def write_payload(payload):
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(exist_ok=True)
    latest_path = DATA_DIR / "latest.json"
    history_path = HISTORY_DIR / f"{payload['meta']['trade_date']}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    latest_path.write_text(text + "\n", encoding="utf-8")
    history_path.write_text(text + "\n", encoding="utf-8")
    return latest_path, history_path


def main():
    parser = argparse.ArgumentParser(description="Update Fenggu Top market data.")
    parser.add_argument("--date", help="Trade date, for example 2026-07-06")
    args = parser.parse_args()

    payload = build_payload(args.date)
    latest_path, history_path = write_payload(payload)
    print(f"wrote {latest_path}")
    print(f"wrote {history_path}")
    print(
        f"limit_up={payload['sentiment']['limit_up_count']} "
        f"broken={payload['sentiment']['broken_limit_count']} "
        f"highest_board={payload['sentiment']['highest_board']}"
    )


if __name__ == "__main__":
    main()
