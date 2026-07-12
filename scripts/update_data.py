from __future__ import annotations

import argparse
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as datetime_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
THEME_CACHE_PATH = DATA_DIR / "eastmoney-theme-cache.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_STATS_LOOKBACK_DAYS = 370
DEFAULT_HISTORY_DAYS = 92
MARKET_DATA_READY_TIME = datetime_time(15, 30)
EASTMONEY_CORE_THEME_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax"
THEME_SPLIT_PATTERN = re.compile(r"[，,；;、|/\\\n\r]+")
THEME_PLACEHOLDERS = {"", "-", "--", "其他", "未知", "暂无", "暂无题材", "无", "null", "none", "nan"}


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


def normalize_theme_values(values):
    if not isinstance(values, (list, tuple, set)):
        values = [values]

    normalized = []
    seen = set()
    for value in values:
        if isinstance(value, (list, tuple, set)):
            candidates = normalize_theme_values(value)
        else:
            candidates = THEME_SPLIT_PATTERN.split(as_text(value))
        for candidate in candidates:
            name = as_text(candidate).strip("、，,;；|/ ")
            if (
                not name
                or name.startswith("<generator object")
                or name.lower() in THEME_PLACEHOLDERS
                or name in THEME_PLACEHOLDERS
            ):
                continue
            if name not in seen:
                seen.add(name)
                normalized.append(name)
    return normalized


def set_record_themes(record, values):
    themes = normalize_theme_values(values)
    record["themes"] = themes
    record["theme"] = "、".join(themes)
    record["concept"] = "、".join(themes)
    return record


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


def eastmoney_security_code(code):
    text = as_text(code).zfill(6)
    if text.startswith(("6", "688")):
        return f"SH{text}"
    if text.startswith(("4", "8", "920")):
        return f"BJ{text}"
    return f"SZ{text}"


def fetch_eastmoney_core_themes(code):
    session = requests.Session()
    session.trust_env = False
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://emweb.securities.eastmoney.com/",
        "User-Agent": "Mozilla/5.0",
    }

    for attempt in range(3):
        try:
            response = session.get(
                EASTMONEY_CORE_THEME_URL,
                params={"code": eastmoney_security_code(code)},
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            boards = payload.get("ssbk") if isinstance(payload, dict) else None
            if not isinstance(boards, list):
                return None
            return normalize_theme_values([
                item.get("BOARD_NAME")
                for item in boards
                if as_text(item.get("IS_PRECISE")) == "1"
            ])
        except (requests.RequestException, ValueError):
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    return None


def load_theme_cache():
    default = {
        "source": "eastmoney_core_conception",
        "updated_at": "",
        "stocks": {},
    }
    try:
        cache = json.loads(THEME_CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default

    if not isinstance(cache, dict):
        return default
    stocks = cache.get("stocks")
    if not isinstance(stocks, dict):
        stocks = {}
    return {**default, **cache, "stocks": stocks}


def save_theme_cache(cache):
    DATA_DIR.mkdir(exist_ok=True)
    cache["source"] = "eastmoney_core_conception"
    cache["updated_at"] = datetime.now(SHANGHAI).strftime("%Y-%m-%d %H:%M")
    THEME_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_eastmoney_themes(codes, cache, refresh_current=False):
    code_list = sorted({as_text(code).zfill(6) for code in codes if as_text(code)})
    today = datetime.now(SHANGHAI).strftime("%Y-%m-%d")
    resolved = {}
    to_fetch = []

    for code in code_list:
        entry = cache["stocks"].get(code)
        entry_themes = normalize_theme_values(entry.get("themes")) if isinstance(entry, dict) else []
        is_current = isinstance(entry, dict) and entry.get("fetched_date") == today
        raw_entry_themes = entry.get("themes", []) if isinstance(entry, dict) else []
        cache_is_valid = not any(
            as_text(name).startswith("<generator object")
            for name in (raw_entry_themes if isinstance(raw_entry_themes, list) else [raw_entry_themes])
        )
        if entry is not None and cache_is_valid and (not refresh_current or is_current):
            resolved[code] = entry_themes
        else:
            to_fetch.append(code)

    if to_fetch:
        successful = 0
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(fetch_eastmoney_core_themes, code): code for code in to_fetch}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    themes = future.result()
                except Exception:
                    themes = None
                if themes is None:
                    cached = cache["stocks"].get(code, {})
                    resolved[code] = normalize_theme_values(cached.get("themes"))
                    continue
                normalized = normalize_theme_values(themes)
                cache["stocks"][code] = {
                    "themes": normalized,
                    "fetched_date": today,
                }
                resolved[code] = normalized
                successful += 1
        print(f"eastmoney core themes: fetched {successful}/{len(to_fetch)} stocks")

    return resolved


def enrich_limit_up_themes(rows, cache, refresh_current=False):
    themes_by_code = resolve_eastmoney_themes(
        [row.get("code") for row in rows],
        cache,
        refresh_current=refresh_current,
    )
    for row in rows:
        set_record_themes(
            row,
            [row.get("themes"), row.get("concept"), themes_by_code.get(as_text(row.get("code")).zfill(6), [])],
        )


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
        set_record_themes(record, record.get("concept"))
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
        set_record_themes(record, record.get("concept"))
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
        set_record_themes(record, record.get("concept"))
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
        set_record_themes(record, record.get("concept"))
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
        set_record_themes(record, record.get("concept"))
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
        if field in {"theme", "themes"}:
            for theme in normalize_theme_values(row.get("themes") or row.get("theme")):
                counts[theme] = counts.get(theme, 0) + 1
            continue
        key = as_text(row.get(field)) or "其他"
        counts[key] = counts.get(key, 0) + 1
    return [
        {"name": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:top_n]
    ]


def date_range_back(day, days):
    for offset in range(days):
        current = day - timedelta(days=offset)
        if current.weekday() < 5:
            yield current


def build_limit_only_payload(trade_date, limit_ups, history, now, stats_lookback_days):
    stats = build_stats(limit_ups, trade_date, list(history)) if limit_ups else []
    highest_board = max([as_int(item.get("consecutive_days"), 1) for item in limit_ups] or [0])
    return {
        "meta": {
            "site_name": "峰股top",
            "trade_date": trade_date,
            "updated_at": now.strftime("%Y-%m-%d %H:%M"),
            "market_data_ready_time": "15:30",
            "source": "akshare + eastmoney",
            "data_status": "ok" if limit_ups else "empty_or_failed",
            "stats_lookback_days": stats_lookback_days,
            "history_scope_days": DEFAULT_HISTORY_DAYS,
            "notes": [
                "历史日期主要用于查看每日涨停池，支持近 3 个月追溯。",
                "题材来自东方财富核心题材接口，支持一只股票归属多个题材。",
            ],
        },
        "sentiment": {
            "limit_up_count": len(limit_ups),
            "limit_down_count": 0,
            "broken_limit_count": 0,
            "highest_board": highest_board,
            "first_board_count": sum(as_int(item.get("consecutive_days"), 1) == 1 for item in limit_ups),
            "multi_board_count": sum(as_int(item.get("consecutive_days"), 1) >= 2 for item in limit_ups),
            "limit_up_turnover_amount": sum(as_number(item.get("turnover_amount"), 0) for item in limit_ups),
            "limit_up_seal_amount": sum(as_number(item.get("seal_amount"), 0) for item in limit_ups),
            "broken_rate": 0,
            "previous_trade_date": "",
            "yesterday_limit_up_count": 0,
            "promoted_count": 0,
            "promotion_rate": 0,
            "promoted_stocks": [],
        },
        "rankings": {
            "industry_limit_rank": rank_by_field(limit_ups, "industry"),
            "theme_limit_rank": rank_by_field(limit_ups, "theme"),
            "market_board_limit_rank": rank_by_field(limit_ups, "market_board"),
        },
        "limit_ups": limit_ups,
        "broken_limits": [],
        "limit_downs": [],
        "strong_stocks": [],
        "sub_new_stocks": [],
        "stats": stats,
    }


def build_payload(
    trade_date_arg=None,
    stats_lookback_days=DEFAULT_STATS_LOOKBACK_DAYS,
    allow_intraday=False,
    theme_cache=None,
):
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
    theme_cache = theme_cache if theme_cache is not None else load_theme_cache()

    limit_ups = fetch_limit_ups(ak_date)
    enrich_limit_up_themes(limit_ups, theme_cache, refresh_current=True)
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
            "source": "akshare + eastmoney",
            "data_status": "ok" if limit_ups else "empty_or_failed",
            "stats_lookback_days": stats_lookback_days,
            "notes": [
                "涨停池、炸板池、跌停池来自 AKShare 东方财富专题接口。",
                "题材来自东方财富核心题材接口，支持一只股票归属多个题材。",
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


def available_history_dates():
    return sorted({path.stem for path in HISTORY_DIR.glob("*.json")}, reverse=True)


def write_json(path, payload):
    payload["meta"]["available_dates"] = available_history_dates()
    if payload["meta"]["trade_date"] not in payload["meta"]["available_dates"]:
        payload["meta"]["available_dates"] = sorted(
            [payload["meta"]["trade_date"], *payload["meta"]["available_dates"]],
            reverse=True,
        )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_payload(payload):
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(exist_ok=True)
    latest_path = DATA_DIR / "latest.json"
    history_path = HISTORY_DIR / f"{payload['meta']['trade_date']}.json"
    write_json(history_path, payload)
    write_json(latest_path, payload)
    return latest_path, history_path


def write_history_range(
    latest_payload,
    history_days=DEFAULT_HISTORY_DAYS,
    stats_lookback_days=DEFAULT_STATS_LOOKBACK_DAYS,
    theme_cache=None,
):
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(exist_ok=True)
    now = datetime.now(SHANGHAI)
    latest_date = datetime.strptime(latest_payload["meta"]["trade_date"], "%Y-%m-%d").date()
    history = build_history_snapshot(latest_payload["meta"]["trade_date"], stats_lookback_days)
    theme_cache = theme_cache if theme_cache is not None else load_theme_cache()
    written = []
    for day in date_range_back(latest_date, history_days):
        trade_date = day.strftime("%Y-%m-%d")
        history_path = HISTORY_DIR / f"{trade_date}.json"
        if trade_date == latest_payload["meta"]["trade_date"]:
            payload = latest_payload
        else:
            limit_ups = fetch_limit_ups(day.strftime("%Y%m%d"))
            enrich_limit_up_themes(limit_ups, theme_cache)
            payload = build_limit_only_payload(trade_date, limit_ups, history, now, stats_lookback_days)
        write_json(history_path, payload)
        written.append(history_path)
        time.sleep(0.03)
    write_json(DATA_DIR / "latest.json", latest_payload)
    return written


def refresh_saved_theme_data():
    paths = [DATA_DIR / "latest.json", *sorted(HISTORY_DIR.glob("*.json"))]
    payloads = []
    seen_paths = set()
    for path in paths:
        if path in seen_paths or not path.exists():
            continue
        seen_paths.add(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("limit_ups"), list):
            payloads.append((path, payload))

    cache = load_theme_cache()
    all_limit_ups = [stock for _, payload in payloads for stock in payload.get("limit_ups", [])]
    enrich_limit_up_themes(all_limit_ups, cache)

    latest_path = DATA_DIR / "latest.json"
    for path, payload in payloads:
        if path == latest_path:
            enrich_limit_up_themes(payload["limit_ups"], cache, refresh_current=True)

        themes_by_code = {
            as_text(stock.get("code")).zfill(6): normalize_theme_values(stock.get("themes"))
            for stock in payload.get("limit_ups", [])
        }
        for stat in payload.get("stats", []):
            themes = themes_by_code.get(as_text(stat.get("code")).zfill(6), [])
            stat["themes"] = themes
            stat["theme"] = "、".join(themes)

        rankings = payload.setdefault("rankings", {})
        rankings["theme_limit_rank"] = rank_by_field(payload.get("limit_ups", []), "theme")
        meta = payload.setdefault("meta", {})
        meta["source"] = "akshare + eastmoney"
        notes = [note for note in meta.get("notes", []) if "题材" not in as_text(note)]
        notes.append("题材来自东方财富核心题材接口，支持一只股票归属多个题材。")
        meta["notes"] = notes
        write_json(path, payload)

    save_theme_cache(cache)
    print(f"refreshed themes for {len(payloads)} payloads and {len(all_limit_ups)} limit-up rows")


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
    parser.add_argument(
        "--history-days",
        type=int,
        default=DEFAULT_HISTORY_DAYS,
        help="Calendar days of selectable historical limit-up data to write.",
    )
    parser.add_argument(
        "--no-history-range",
        action="store_true",
        help="Only write latest.json and the selected trade date history file.",
    )
    parser.add_argument(
        "--refresh-themes-only",
        action="store_true",
        help="Refresh saved JSON files from the Eastmoney core-theme cache without fetching market pools.",
    )
    args = parser.parse_args()

    if args.refresh_themes_only:
        refresh_saved_theme_data()
        return

    theme_cache = load_theme_cache()
    payload = build_payload(
        args.date,
        args.stats_lookback_days,
        args.allow_intraday,
        theme_cache=theme_cache,
    )
    latest_path, history_path = write_payload(payload)
    written_history = []
    if not args.no_history_range:
        written_history = write_history_range(
            payload,
            args.history_days,
            args.stats_lookback_days,
            theme_cache=theme_cache,
        )
    save_theme_cache(theme_cache)
    print(f"wrote {latest_path}")
    print(f"wrote {history_path}")
    if written_history:
        print(f"history_range={len(written_history)} files")
    print(
        f"limit_up={payload['sentiment']['limit_up_count']} "
        f"broken={payload['sentiment']['broken_limit_count']} "
        f"highest_board={payload['sentiment']['highest_board']}"
    )


if __name__ == "__main__":
    main()
