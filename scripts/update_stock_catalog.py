from __future__ import annotations

import argparse
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import akshare as ak
import requests


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CATALOG_PATH = DATA_DIR / "stock-catalog.json"
LATEST_PATH = DATA_DIR / "latest.json"
THEME_CACHE_PATH = DATA_DIR / "eastmoney-theme-cache.json"
EASTMONEY_SPOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_TOKEN = "bd1d9ddb04089700cf9c27f6f7426281"


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def clean_value(value: Any, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    if isinstance(value, float) and math.isnan(value):
        return fallback
    if str(value).strip().lower() in {"", "nan", "none", "null", "-", "--"}:
        return fallback
    return value


def number(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return fallback if math.isnan(result) or math.isinf(result) else result


def normalize_code(value: Any) -> str:
    match = re.search(r"(\d{6})$", str(value or "").strip().lower())
    return match.group(1) if match else ""


def infer_market_board(code: str) -> str:
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("4", "8", "92")):
        return "北交所"
    return "主板"


def normalize_themes(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = re.split(r"[,，、;；/]+", str(value or ""))
    excluded = {"", "-", "--", "其他", "未知", "暂无", "暂无数据", "空值"}
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        theme = str(raw or "").strip()
        if theme in excluded or theme in seen:
            continue
        seen.add(theme)
        result.append(theme)
    return result


def latest_records() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    payload = read_json(LATEST_PATH, {})
    records: dict[str, dict[str, Any]] = {}
    for group in ("stats", "limit_ups", "broken_limits", "limit_downs"):
        for item in payload.get(group) or []:
            if not isinstance(item, dict):
                continue
            code = normalize_code(item.get("code"))
            if not code:
                continue
            records.setdefault(code, {}).update(item)
    return records, payload.get("meta") or {}


def cached_catalog() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    payload = read_json(CATALOG_PATH, {})
    records: dict[str, dict[str, Any]] = {}
    for item in payload.get("stocks") or []:
        if not isinstance(item, dict):
            continue
        code = normalize_code(item.get("code"))
        if code:
            records[code] = item
    return records, payload.get("meta") or {}


def cached_themes() -> dict[str, list[str]]:
    payload = read_json(THEME_CACHE_PATH, {})
    raw_stocks = payload.get("stocks") or {}
    result: dict[str, list[str]] = {}
    if not isinstance(raw_stocks, dict):
        return result
    for raw_code, value in raw_stocks.items():
        code = normalize_code(raw_code)
        if not code:
            continue
        themes = value.get("themes") if isinstance(value, dict) else value
        normalized = normalize_themes(themes)
        if normalized:
            result[code] = normalized
    return result


def fetch_with_retry(function_name: str, attempts: int = 3):
    function = getattr(ak, function_name)
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return function()
        except Exception as exc:  # noqa: BLE001 - external data source errors vary.
            error = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    if error:
        raise error
    raise RuntimeError(f"{function_name} returned no data")


def fetch_eastmoney_records(attempts: int = 8) -> dict[str, dict[str, Any]]:
    params = {
        "pn": "1",
        "pz": "6000",
        "po": "1",
        "np": "1",
        "ut": EASTMONEY_TOKEN,
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f2,f3,f6,f8,f12,f14,f20,f21,f100",
    }
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                EASTMONEY_SPOT_URL,
                params=params,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
                timeout=45,
            )
            response.raise_for_status()
            rows = ((response.json().get("data") or {}).get("diff") or [])
            if len(rows) < 4_000:
                raise RuntimeError(f"Eastmoney returned only {len(rows)} stocks")
            result: dict[str, dict[str, Any]] = {}
            for row in rows:
                code = normalize_code(row.get("f12"))
                if not code:
                    continue
                result[code] = {
                    "code": code,
                    "name": str(clean_value(row.get("f14"), "") or "").strip(),
                    "industry": str(clean_value(row.get("f100"), "") or "").strip(),
                    "latest_price": number(row.get("f2")),
                    "change_pct": number(row.get("f3")),
                    "turnover_amount": number(row.get("f6")),
                    "turnover_rate": number(row.get("f8")),
                    "total_market_cap": number(row.get("f20")),
                    "float_market_cap": number(row.get("f21")),
                }
            return result
        except Exception as exc:  # noqa: BLE001 - endpoint and proxy failures vary.
            error = exc
            if attempt < attempts:
                time.sleep(min(attempt * 2, 10))
    if error:
        raise error
    raise RuntimeError("Eastmoney returned no stock directory")


def fetch_sina_spot_records() -> dict[str, dict[str, Any]]:
    frame = fetch_with_retry("stock_zh_a_spot")
    result: dict[str, dict[str, Any]] = {}
    for row in frame.to_dict("records"):
        code = normalize_code(row.get("代码"))
        if not code:
            continue
        result[code] = {
            "code": code,
            "name": str(clean_value(row.get("名称"), "") or "").strip(),
            "latest_price": number(row.get("最新价")),
            "change_pct": number(row.get("涨跌幅")),
            "turnover_amount": number(row.get("成交额")),
            "quote_time": str(clean_value(row.get("时间戳"), "") or "").strip(),
        }
    return result


def fetch_name_records() -> dict[str, dict[str, Any]]:
    frame = fetch_with_retry("stock_info_a_code_name")
    result: dict[str, dict[str, Any]] = {}
    for row in frame.to_dict("records"):
        code = normalize_code(row.get("code"))
        if not code:
            continue
        result[code] = {
            "code": code,
            "name": str(clean_value(row.get("name"), "") or "").strip(),
        }
    return result


def build_catalog(offline: bool = False) -> dict[str, Any]:
    existing, existing_meta = cached_catalog()
    latest, latest_meta = latest_records()
    themes = cached_themes()
    spot: dict[str, dict[str, Any]] = {}
    names: dict[str, dict[str, Any]] = {}
    source_errors: list[str] = []

    if not offline:
        try:
            spot = fetch_eastmoney_records()
        except Exception as exc:  # noqa: BLE001
            source_errors.append(f"eastmoney_spot: {exc}")
            try:
                spot = fetch_sina_spot_records()
            except Exception as fallback_exc:  # noqa: BLE001
                source_errors.append(f"stock_zh_a_spot: {fallback_exc}")
        try:
            names = fetch_name_records()
        except Exception as exc:  # noqa: BLE001
            source_errors.append(f"stock_info_a_code_name: {exc}")

    all_codes = set(existing) | set(latest) | set(spot) | set(names)
    if len(all_codes) < 4_000:
        details = "; ".join(source_errors) or "no external stock directory available"
        raise RuntimeError(f"stock catalog is incomplete ({len(all_codes)} codes): {details}")

    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
    rows: list[dict[str, Any]] = []
    for code in sorted(all_codes):
        old = existing.get(code, {})
        live = latest.get(code, {})
        quote = spot.get(code, {})
        named = names.get(code, {})
        row_themes = themes.get(code) or normalize_themes(live.get("themes") or live.get("theme"))
        if not row_themes:
            row_themes = normalize_themes(old.get("themes") or old.get("theme"))
        name = str(
            clean_value(named.get("name"))
            or clean_value(quote.get("name"))
            or clean_value(live.get("name"))
            or clean_value(old.get("name"))
            or code
        ).strip()
        industry = str(
            clean_value(quote.get("industry"))
            or clean_value(live.get("industry"))
            or clean_value(old.get("industry"))
            or ""
        ).strip()
        board = str(
            clean_value(live.get("market_board"))
            or clean_value(old.get("market_board"))
            or infer_market_board(code)
        ).strip()
        rows.append(
            {
                "code": code,
                "name": name,
                "industry": industry,
                "themes": row_themes,
                "theme": "、".join(row_themes),
                "market_board": board,
                "latest_price": number(quote.get("latest_price") or live.get("latest_price") or old.get("latest_price")),
                "change_pct": number(quote.get("change_pct") or live.get("change_pct") or old.get("change_pct")),
                "turnover_amount": number(
                    quote.get("turnover_amount")
                    or live.get("turnover_amount")
                    or old.get("turnover_amount")
                ),
                "turnover_rate": number(
                    quote.get("turnover_rate") or live.get("turnover_rate") or old.get("turnover_rate")
                ),
                "float_market_cap": number(
                    quote.get("float_market_cap") or live.get("float_market_cap") or old.get("float_market_cap")
                ),
                "total_market_cap": number(
                    quote.get("total_market_cap") or live.get("total_market_cap") or old.get("total_market_cap")
                ),
                "quote_time": str(clean_value(quote.get("quote_time")) or clean_value(old.get("quote_time")) or ""),
            }
        )

    return {
        "meta": {
            "generated_at": generated_at,
            "trade_date": latest_meta.get("trade_date") or existing_meta.get("trade_date") or "",
            "stock_count": len(rows),
            "source": "Eastmoney full A-share snapshot + AKShare stock lists",
            "fallback_used": not bool(spot or names),
            "source_errors": source_errors,
        },
        "stocks": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the full A-share stock catalog used by SEO pages.")
    parser.add_argument("--offline", action="store_true", help="Only merge the existing catalog and saved market data.")
    args = parser.parse_args()
    payload = build_catalog(offline=args.offline)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    meta = payload["meta"]
    print(f"stock catalog generated: {meta['stock_count']} stocks -> {CATALOG_PATH}")
    if meta.get("source_errors"):
        print("source warnings:")
        for error in meta["source_errors"]:
            print(f"- {error}")


if __name__ == "__main__":
    main()
