from __future__ import annotations

import argparse
import json
import math
import re
import time
from datetime import datetime, time as datetime_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_STATS_LOOKBACK_DAYS = 370
MARKET_DATA_READY_TIME = datetime_time(15, 30)
THEME_RULES = [
    ("机器人", ["机器人", "减速器", "伺服", "工业母机", "智能制造"]),
    ("PCB", ["PCB", "印制电路", "线路板", "覆铜板", "电子元件", "元件"]),
    ("算力", ["算力", "服务器", "数据中心", "液冷", "光模块", "CPO"]),
    ("创新药", ["创新药", "医药", "生物制品", "化学制药", "医疗"]),
    ("军工", ["军工", "航天", "航空", "卫星", "国防"]),
    ("半导体", ["半导体", "芯片", "集成电路", "封测"]),
    ("AI硬件", ["AI", "人工智能", "消费电子", "计算机设", "光学光电"]),
    ("消费电子", ["消费电子", "电子", "光学光电"]),
    ("有色金属", ["有色", "稀土", "金属", "冶钢", "矿业"]),
    ("固态电池", ["固态电池", "电池", "锂电", "新能源"]),
    ("商业航天", ["商业航天", "卫星", "航天"]),
]


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
    if not text:
        return ""
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def infer_market_board(code):
    text = as_text(code)
    if text.startswith(("300", "301")):
        return "创业板"
    if text.startswith("688"):
        return "科创板"
    if text.startswith(("8", "4", "920")):
        return "北交所"
    return "主板"


def infer_theme(row):
    text = " ".join(
        as_text(row.get(key))
        for key in ["name", "concept", "industry", "reason", "selected_reason"]
    )
    for theme, keywords in THEME_RULES:
        if any(keyword.lower() in text.lower() for keyword in keywords):
            return theme
    return "其他"


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


def limit_stats_parts(value):
    text = as_text(value)
    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if not match:
        return {"limit_days_in_window": 0, "limit_days_window": 0, "limit_stats": text}
    return {
        "limit_days_in_window": int(match.group(1)),
        "limit_days_window": int(match.group(2)),
        "limit_stats": text,
    }


def fetch_limit_ups(trade_date):
    raw = call_akshare("stock_zt_pool_em", date=trade_date)
    rows = []
    for row in frame_records(raw):
        stats = limit_stats_parts(pick(row, ["涨停统计"], ""))
        record = {
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
                **stats,
            }
        record["market_board"] = infer_market_board(record["code"])
        record["theme"] = infer_theme(record)
        rows.append(record)
    return [row for row in rows if row["code"] and row["name"]]


def fetch_broken_limits(trade_date):
    raw = call_akshare("stock_zt_pool_zbgc_em", date=trade_date)
    rows = []
    for row in frame_records(raw):
        stats = limit_stats_parts(pick(row, ["涨停统计"], ""))
        record = {
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
                **stats,
            }
        record["market_board"] = infer_market_board(record["code"])
        record["theme"] = infer_theme(record)
        rows.append(record)
    return [row for row in rows if row["code"] and row["name"]]


def fetch_limit_downs(trade_date):
    raw = call_akshare("stock_zt_pool_dtgc_em", date=trade_date)
    rows = []
    for row in frame_records(raw):
        record = {
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
            }
        record["market_board"] = infer_market_board(record["code"])
        record["theme"] = infer_theme(record)
        rows.append(record)
    return [row for row in rows if row["code"] and row["name"]]


def fetch_strong_stocks(trade_date):
    raw = call_akshare("stock_zt_pool_strong_em", date=trade_date)
    rows = []
    for row in frame_records(raw):
        stats = limit_stats_parts(pick(row, ["涨停统计"], ""))
        record = {
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
                **stats,
            }
        record["market_board"] = infer_market_board(record["code"])
        record["theme"] = infer_theme(record)
        rows.append(record)
    return [row for row in rows if row["code"] and row["name"]]


def fetch_sub_new_stocks(trade_date):
    raw = call_akshare("stock_zt_pool_sub_new_em", date=trade_date)
    rows = []
    for row in frame_records(raw):
        stats = limit_stats_parts(pick(row, ["涨停统计"], ""))
        record = {
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
                **stats,
            }
        record["market_board"] = infer_market_board(record["code"])
        record["theme"] = infer_theme(record)
        rows.append(record)
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
            records.append(
                {
                    "trade_date": trade_date,
                    "code": stock.get("code"),
                    "name": stock.get("name"),
                    "consecutive_days": as_int(stock.get("consecutive_days"), 1),
                }
            )
    return records


def fetch_history_records(trade_date, lookback_days):
    target_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
    records = []
    for offset in range(lookback_days + 1):
        day = target_date - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        day_text = day.strftime("%Y-%m-%d")
        daily = fetch_limit_ups(day.strftime("%Y%m%d"))
        for stock in daily:
            records.append(
                {
                    "trade_date": day_text,
                    "code": stock["code"],
                    "name": stock["name"],
                    "consecutive_days": as_int(stock.get("consecutive_days"), 1),
                }
            )
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


def build_history_snapshot(trade_date, lookback_days=DEFAULT_STATS_LOOKBACK_DAYS):
    return merge_history_records(load_history(), fetch_history_records(trade_date, lookback_days))


def previous_limit_session(history, trade_date):
    previous_dates = sorted({item["trade_date"] for item in history if item.get("trade_date") < trade_date})
    if not previous_dates:
        return "", []
    previous_date = previous_dates[-1]
    return previous_date, [item for item in history if item.get("trade_date") == previous_date]


def promotion_summary(limit_ups, history, trade_date):
    previous_date, previous_rows = previous_limit_session(history, trade_date)
    previous_codes = {item["code"] for item in previous_rows}
    promoted = [
        stock
        for stock in limit_ups
        if stock.get("code") in previous_codes and as_int(stock.get("consecutive_days"), 1) >= 2
    ]
    base_count = len(previous_codes)
    return {
        "previous_trade_date": previous_date,
        "yesterday_limit_up_count": base_count,
        "promoted_count": len(promoted),
        "promotion_rate": round((len(promoted) / base_count) * 100, 2) if base_count else 0,
        "promoted_stocks": [
            {
                "code": stock["code"],
                "name": stock["name"],
                "consecutive_days": as_int(stock.get("consecutive_days"), 1),
            }
            for stock in promoted
        ],
    }


def build_stats(limit_ups, trade_date, history):
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
    latest_names = {stock["code"]: stock["name"] for stock in limit_ups}
    latest_meta = {stock["code"]: stock for stock in limit_ups}
    stats = []
    for code in sorted({item["code"] for item in history} | set(latest_names)):
        rows = [item for item in history if item["code"] == code]
        dates = [datetime.strptime(item["trade_date"], "%Y-%m-%d").date() for item in rows]
        if not rows:
            continue
        last_row = max(rows, key=lambda item: item["trade_date"])
        latest = latest_meta.get(code, {})
        stats.append(
            {
                "code": code,
                "name": latest_names.get(code) or last_row.get("name") or "",
                "industry": latest.get("industry", ""),
                "theme": latest.get("theme", ""),
                "market_board": infer_market_board(code),
                "limit_count_7d": sum(day >= target_date - timedelta(days=7) for day in dates),
                "limit_count_30d": sum(day >= target_date - timedelta(days=30) for day in dates),
                "limit_count_1y": sum(day >= target_date - timedelta(days=365) for day in dates),
                "limit_count_ytd": sum(day.year == target_date.year for day in dates),
                "limit_count_3y": sum(day >= target_date - timedelta(days=365 * 3) for day in dates),
                "total_limit_count": len(rows),
                "max_consecutive_days": max([as_int(item.get("consecutive_days"), 1) for item in rows] or [1]),
                "last_limit_date": max([item["trade_date"] for item in rows], default=trade_date),
                "first_limit_date": min([item["trade_date"] for item in rows], default=trade_date),
                "broken_count_total": None,
                "is_limit_today": code in latest_names,
            }
        )
    return sorted(stats, key=lambda item: (item["limit_count_30d"], item["limit_count_1y"]), reverse=True)


def rank_by_field(rows, field, top_n=12):
    counts = {}
    for row in rows:
        key = as_text(row.get(field)) or "其他"
        counts[key] = counts.get(key, 0) + 1
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:top_n]
    ]


def build_payload(trade_date_arg=None, stats_lookback_days=DEFAULT_STATS_LOOKBACK_DAYS, allow_intraday=False):
    now = datetime.now(SHANGHAI)
    completed_trade_date = latest_completed_trade_date(now)
    if trade_date_arg:
        target_date = datetime.strptime(trade_date_arg, "%Y-%m-%d").date()
        if not allow_intraday and target_date > completed_trade_date:
            raise ValueError(
                f"{trade_date_arg} has not reached the 15:30 close update window. "
                f"Use --allow-intraday only for manual testing."
            )
        trade_date = trade_date_arg
    else:
        trade_date = completed_trade_date.strftime("%Y-%m-%d")
    ak_date = trade_date.replace("-", "")

    limit_ups = fetch_limit_ups(ak_date)
    broken_limits = fetch_broken_limits(ak_date)
    limit_downs = fetch_limit_downs(ak_date)
    strong_stocks = fetch_strong_stocks(ak_date)
    sub_new_stocks = fetch_sub_new_stocks(ak_date)
    highest_board = max([as_int(item.get("consecutive_days"), 1) for item in limit_ups] or [0])
    broken_count = len(broken_limits)
    total_for_rate = len(limit_ups) + broken_count
    history = build_history_snapshot(trade_date, stats_lookback_days) if limit_ups else []
    stats = build_stats(limit_ups, trade_date, history) if limit_ups else []
    promotion = promotion_summary(limit_ups, history, trade_date) if limit_ups else {
        "previous_trade_date": "",
        "yesterday_limit_up_count": 0,
        "promoted_count": 0,
        "promotion_rate": 0,
        "promoted_stocks": [],
    }

    return {
        "meta": {
            "site_name": "峰股top",
            "trade_date": trade_date,
            "updated_at": now.strftime("%Y-%m-%d %H:%M"),
            "market_data_ready_time": "15:30",
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
            "first_board_count": sum(as_int(item.get("consecutive_days"), 1) == 1 for item in limit_ups),
            "multi_board_count": sum(as_int(item.get("consecutive_days"), 1) >= 2 for item in limit_ups),
            "limit_up_turnover_amount": sum(as_number(item.get("turnover_amount"), 0) for item in limit_ups),
            "limit_up_seal_amount": sum(as_number(item.get("seal_amount"), 0) for item in limit_ups),
            "broken_rate": round((broken_count / total_for_rate) * 100, 2) if total_for_rate else 0,
            **promotion,
        },
        "rankings": {
            "industry_limit_rank": rank_by_field(limit_ups, "industry"),
            "theme_limit_rank": rank_by_field(limit_ups, "theme"),
            "market_board_limit_rank": rank_by_field(limit_ups, "market_board"),
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
    existing_dates = {path.stem for path in HISTORY_DIR.glob("*.json")}
    existing_dates.add(payload["meta"]["trade_date"])
    payload["meta"]["available_dates"] = sorted(existing_dates, reverse=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    latest_path.write_text(text + "\n", encoding="utf-8")
    history_path.write_text(text + "\n", encoding="utf-8")
    return latest_path, history_path


def main():
    parser = argparse.ArgumentParser(description="Update Fenggu Top market data.")
    parser.add_argument("--date", help="Trade date, for example 2026-07-06")
    parser.add_argument(
        "--stats-lookback-days",
        type=int,
        default=DEFAULT_STATS_LOOKBACK_DAYS,
        help="Calendar days used to backfill stock limit-up statistics.",
    )
    parser.add_argument(
        "--allow-intraday",
        action="store_true",
        help="Allow updating a not-yet-closed trade date. Use only for manual checks.",
    )
    args = parser.parse_args()

    payload = build_payload(args.date, args.stats_lookback_days, args.allow_intraday)
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
