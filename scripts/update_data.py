from __future__ import annotations

import argparse
import json
import math
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_STATS_LOOKBACK_DAYS = 370


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
    return "" if value is None else str(value).strip()


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


def as_float(value, fallback=0):
    return float(as_number(value, fallback))


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


def normalize_date(value):
    text = as_text(value)
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def limit_stats_parts(value):
    text = as_text(value)
    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    return {
        "limit_days_in_window": int(match.group(1)) if match else 0,
        "limit_days_window": int(match.group(2)) if match else 0,
        "limit_stats": text,
    }


def parse_consecutive(row):
    direct = pick(row, ["连板数", "连板", "连续涨停天数"])
    if direct is not None:
        return max(1, as_int(direct, 1))
    match = re.search(r"(\d+)\s*板", as_text(pick(row, ["涨停统计", "封板结构"], "")))
    return max(1, int(match.group(1))) if match else 1


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
    rows = []
    for row in frame_records(call_akshare("stock_zt_pool_em", date=trade_date)):
        rows.append({
            "code": as_text(pick(row, ["代码", "股票代码", "证券代码"])).zfill(6),
            "name": as_text(pick(row, ["名称", "股票简称", "股票名称"])),
            "change_pct": as_float(pick(row, ["涨跌幅"], 0)),
            "latest_price": as_float(pick(row, ["最新价"], 0)),
            "turnover_amount": as_number(pick(row, ["成交额"], 0)),
            "float_market_cap": as_number(pick(row, ["流通市值"], 0)),
            "total_market_cap": as_number(pick(row, ["总市值"], 0)),
            "turnover_rate": as_float(pick(row, ["换手率"], 0)),
            "first_limit_time": normalize_time(pick(row, ["首次封板时间", "首次涨停时间"])),
            "last_limit_time": normalize_time(pick(row, ["最后封板时间", "最终封板时间"])),
            "concept": as_text(pick(row, ["所属概念", "概念"], "")),
            "industry": as_text(pick(row, ["所属行业", "行业"], "")),
            "seal_amount": as_number(pick(row, ["封板资金", "封单资金", "封单金额"], 0)),
            "consecutive_days": parse_consecutive(row),
            "open_times": as_int(pick(row, ["炸板次数", "打开次数"], 0)),
            "reason": as_text(pick(row, ["涨停原因", "涨停原因类别", "原因"], "")),
            **limit_stats_parts(pick(row, ["涨停统计"], "")),
        })
    return [row for row in rows if row["code"] and row["name"]]


def fetch_broken_limits(trade_date):
    rows = []
    for row in frame_records(call_akshare("stock_zt_pool_zbgc_em", date=trade_date)):
        rows.append({
            "code": as_text(pick(row, ["代码", "股票代码", "证券代码"])).zfill(6),
            "name": as_text(pick(row, ["名称", "股票简称", "股票名称"])),
            "change_pct": as_float(pick(row, ["涨跌幅"], 0)),
            "latest_price": as_float(pick(row, ["最新价"], 0)),
            "limit_price": as_float(pick(row, ["涨停价"], 0)),
            "turnover_amount": as_number(pick(row, ["成交额"], 0)),
            "float_market_cap": as_number(pick(row, ["流通市值"], 0)),
            "total_market_cap": as_number(pick(row, ["总市值"], 0)),
            "turnover_rate": as_float(pick(row, ["换手率"], 0)),
            "speed": as_float(pick(row, ["涨速"], 0)),
            "amplitude": as_float(pick(row, ["振幅"], 0)),
            "first_limit_time": normalize_time(pick(row, ["首次封板时间"], "")),
            "open_times": as_int(pick(row, ["炸板次数"], 0)),
            "concept": as_text(pick(row, ["所属概念", "概念"], "")),
            "industry": as_text(pick(row, ["所属行业", "行业"], "")),
            "reason": as_text(pick(row, ["炸板原因", "原因", "涨停原因"], "")),
            **limit_stats_parts(pick(row, ["涨停统计"], "")),
        })
    return [row for row in rows if row["code"] and row["name"]]


def fetch_limit_downs(trade_date):
    rows = []
    for row in frame_records(call_akshare("stock_zt_pool_dtgc_em", date=trade_date)):
        rows.append({
            "code": as_text(pick(row, ["代码", "股票代码", "证券代码"])).zfill(6),
            "name": as_text(pick(row, ["名称", "股票简称", "股票名称"])),
            "change_pct": as_float(pick(row, ["涨跌幅"], 0)),
            "latest_price": as_float(pick(row, ["最新价"], 0)),
            "turnover_amount": as_number(pick(row, ["成交额"], 0)),
            "float_market_cap": as_number(pick(row, ["流通市值"], 0)),
            "total_market_cap": as_number(pick(row, ["总市值"], 0)),
            "pe_dynamic": as_float(pick(row, ["动态市盈率"], 0)),
            "turnover_rate": as_float(pick(row, ["换手率"], 0)),
            "seal_amount": as_number(pick(row, ["封单资金"], 0)),
            "last_limit_time": normalize_time(pick(row, ["最后封板时间"], "")),
            "board_turnover_amount": as_number(pick(row, ["板上成交额"], 0)),
            "consecutive_days": as_int(pick(row, ["连续跌停"], 0)),
            "open_times": as_int(pick(row, ["开板次数"], 0)),
            "industry": as_text(pick(row, ["所属行业", "行业"], "")),
        })
    return [row for row in rows if row["code"] and row["name"]]


def fetch_strong_stocks(trade_date):
    rows = []
    for row in frame_records(call_akshare("stock_zt_pool_strong_em", date=trade_date)):
        rows.append({
            "code": as_text(pick(row, ["代码", "股票代码", "证券代码"])).zfill(6),
            "name": as_text(pick(row, ["名称", "股票简称", "股票名称"])),
            "change_pct": as_float(pick(row, ["涨跌幅"], 0)),
            "latest_price": as_float(pick(row, ["最新价"], 0)),
            "limit_price": as_float(pick(row, ["涨停价"], 0)),
            "turnover_amount": as_number(pick(row, ["成交额"], 0)),
            "turnover_rate": as_float(pick(row, ["换手率"], 0)),
            "speed": as_float(pick(row, ["涨速"], 0)),
            "is_new_high": as_text(pick(row, ["是否新高"], "")),
            "volume_ratio": as_float(pick(row, ["量比"], 0)),
            "selected_reason": as_text(pick(row, ["入选理由"], "")),
            "industry": as_text(pick(row, ["所属行业", "行业"], "")),
            **limit_stats_parts(pick(row, ["涨停统计"], "")),
        })
    return [row for row in rows if row["code"] and row["name"]]


def fetch_sub_new_stocks(trade_date):
    rows = []
    for row in frame_records(call_akshare("stock_zt_pool_sub_new_em", date=trade_date)):
        rows.append({
            "code": as_text(pick(row, ["代码", "股票代码", "证券代码"])).zfill(6),
            "name": as_text(pick(row, ["名称", "股票简称", "股票名称"])),
            "change_pct": as_float(pick(row, ["涨跌幅"], 0)),
            "latest_price": as_float(pick(row, ["最新价"], 0)),
            "limit_price": as_float(pick(row, ["涨停价"], 0)),
            "turnover_amount": as_number(pick(row, ["成交额"], 0)),
            "turnover_rate": as_float(pick(row, ["换手率", "转手率"], 0)),
            "open_days": as_int(pick(row, ["开板几日"], 0)),
            "open_date": normalize_date(pick(row, ["开板日期"], "")),
            "listing_date": normalize_date(pick(row, ["上市日期"], "")),
            "is_new_high": as_text(pick(row, ["是否新高"], "")),
            "industry": as_text(pick(row, ["所属行业", "行业"], "")),
            **limit_stats_parts(pick(row, ["涨停统计"], "")),
        })
    return [row for row in rows if row["code"] and row["name"]]


def load_history():
    records = []
    for path in sorted(HISTORY_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        trade_date = payload.get("meta", {}).get("trade_date") or path.stem
        for stock in payload.get("limit_ups", []):
            records.append({
                "trade_date": trade_date,
                "code": stock.get("code"),
                "name": stock.get("name"),
                "consecutive_days": as_int(stock.get("consecutive_days"), 1),
            })
    return records


def fetch_history_records(trade_date, lookback_days):
    target_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
    records = []
    for offset in range(lookback_days + 1):
        day = target_date - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        daily = fetch_limit_ups(day.strftime("%Y%m%d"))
        day_text = day.strftime("%Y-%m-%d")
        for stock in daily:
            records.append({
                "trade_date": day_text,
                "code": stock["code"],
                "name": stock["name"],
                "consecutive_days": as_int(stock.get("consecutive_days"), 1),
            })
        if daily:
            time.sleep(0.05)
    return records


def merge_history_records(*groups):
    merged = {}
    for group in groups:
        for item in group:
            key = (item.get("trade_date"), item.get("code"))
            if key[0] and key[1]:
                merged[key] = item
    return list(merged.values())


def build_stats(limit_ups, trade_date, lookback_days=DEFAULT_STATS_LOOKBACK_DAYS):
    history = merge_history_records(load_history(), fetch_history_records(trade_date, lookback_days))
    existing_keys = {(item["trade_date"], item["code"]) for item in history}
    for stock in limit_ups:
        key = (trade_date, stock["code"])
        if key not in existing_keys:
            history.append({
                "trade_date": trade_date,
                "code": stock["code"],
                "name": stock["name"],
                "consecutive_days": as_int(stock.get("consecutive_days"), 1),
            })
    target_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
    latest_names = {stock["code"]: stock["name"] for stock in limit_ups}
    stats = []
    for code in sorted({item["code"] for item in history} | set(latest_names)):
        rows = [item for item in history if item["code"] == code]
        if not rows:
            continue
        dates = [datetime.strptime(item["trade_date"], "%Y-%m-%d").date() for item in rows]
        last_row = max(rows, key=lambda item: item["trade_date"])
        stats.append({
            "code": code,
            "name": latest_names.get(code) or last_row.get("name") or "",
            "limit_count_7d": sum(day >= target_date - timedelta(days=7) for day in dates),
            "limit_count_30d": sum(day >= target_date - timedelta(days=30) for day in dates),
            "limit_count_1y": sum(day >= target_date - timedelta(days=365) for day in dates),
            "total_limit_count": len(rows),
            "max_consecutive_days": max([as_int(item.get("consecutive_days"), 1) for item in rows] or [1]),
            "last_limit_date": max([item["trade_date"] for item in rows], default=trade_date),
            "is_limit_today": code in latest_names,
        })
    return sorted(stats, key=lambda item: (item["limit_count_30d"], item["limit_count_1y"]), reverse=True)


def build_payload(trade_date_arg=None, stats_lookback_days=DEFAULT_STATS_LOOKBACK_DAYS):
    now = datetime.now(SHANGHAI)
    trade_date = trade_date_arg or now.strftime("%Y-%m-%d")
    ak_date = trade_date.replace("-", "")
    limit_ups = fetch_limit_ups(ak_date)
    broken_limits = fetch_broken_limits(ak_date)
    limit_downs = fetch_limit_downs(ak_date)
    strong_stocks = fetch_strong_stocks(ak_date)
    sub_new_stocks = fetch_sub_new_stocks(ak_date)
    highest_board = max([as_int(item.get("consecutive_days"), 1) for item in limit_ups] or [0])
    broken_count = len(broken_limits)
    total_for_rate = len(limit_ups) + broken_count
    stats = build_stats(limit_ups, trade_date, stats_lookback_days) if limit_ups else []
    return {
        "meta": {
            "site_name": "峰股top",
            "trade_date": trade_date,
            "updated_at": now.strftime("%Y-%m-%d %H:%M"),
            "source": "akshare",
            "data_status": "ok" if limit_ups else "empty_or_failed",
            "stats_lookback_days": stats_lookback_days,
            "notes": [
                "涨停池、炸板池、跌停池来自 AKShare 东方财富专题接口。",
                "AKShare 当前涨停池不提供标准化涨停原因，页面优先展示行业和原始涨停统计。",
            ],
        },
        "sentiment": {
            "limit_up_count": len(limit_ups),
            "limit_down_count": len(limit_downs),
            "broken_limit_count": broken_count,
            "highest_board": highest_board,
            "limit_up_turnover_amount": sum(as_number(item.get("turnover_amount"), 0) for item in limit_ups),
            "limit_up_seal_amount": sum(as_number(item.get("seal_amount"), 0) for item in limit_ups),
            "broken_rate": round((broken_count / total_for_rate) * 100, 2) if total_for_rate else 0,
        },
        "limit_ups": limit_ups,
        "broken_limits": broken_limits,
        "limit_downs": limit_downs,
        "strong_stocks": strong_stocks,
        "sub_new_stocks": sub_new_stocks,
        "stats": stats,
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
    parser.add_argument("--stats-lookback-days", type=int, default=DEFAULT_STATS_LOOKBACK_DAYS)
    args = parser.parse_args()
    payload = build_payload(args.date, args.stats_lookback_days)
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
