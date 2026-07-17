from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
LATEST_PATH = DATA_DIR / "latest.json"
CATALOG_PATH = DATA_DIR / "stock-catalog.json"
INDEX_PATH = ROOT / "index.html"
MANIFEST_PATH = DATA_DIR / "seo-manifest.json"
SITE_ROOT = "https://xiaoma-feng.github.io/fenggu-top/"
SITE_BASE = "/fenggu-top/"
SITE_NAME = "锋股top"
SOCIAL_IMAGE = f"{SITE_ROOT}social-preview.png"
FALLBACK_START = "<!-- SEO_FALLBACK_START -->"
FALLBACK_END = "<!-- SEO_FALLBACK_END -->"
GENERATED_ROOTS = ("stock", "industry", "theme", "limit-up", "review")
LEGACY_GENERATED_ROOTS = ("news",)
STOCKS_PER_INDEX_PAGE = 180
TOPIC_SPLIT_RE = re.compile(r"[,，、;；/]+")
EXCLUDED_LABELS = {"", "-", "--", "其他", "未知", "暂无", "暂无数据", "空值", "数据积累中"}


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def decimal(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_text(value: Any, fallback: str = "-") -> str:
    result = str(value or "").strip()
    return result if result else fallback


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def normalize_code(value: Any) -> str:
    match = re.search(r"(\d{6})$", str(value or "").strip())
    return match.group(1) if match else ""


def infer_market_board(code: str) -> str:
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("4", "8", "92")):
        return "北交所"
    return "主板"


def topics(stock: dict[str, Any]) -> list[str]:
    raw: list[str] = []
    values = stock.get("themes")
    if isinstance(values, list):
        raw.extend(str(value) for value in values)
    for key in ("theme", "concept"):
        value = stock.get(key)
        if value:
            raw.extend(TOPIC_SPLIT_RE.split(str(value)))
    result: list[str] = []
    seen: set[str] = set()
    for value in raw:
        label = value.strip()
        if label in EXCLUDED_LABELS or label in seen:
            continue
        seen.add(label)
        result.append(label)
    return result


def valid_label(value: Any) -> str:
    label = clean_text(value, "")
    return "" if label in EXCLUDED_LABELS else label


def format_date_cn(value: str) -> str:
    day = datetime.strptime(value, "%Y-%m-%d")
    return f"{day.year}年{day.month}月{day.day}日"


def format_money(value: Any) -> str:
    amount = decimal(value)
    absolute = abs(amount)
    if absolute >= 100_000_000:
        return f"{amount / 100_000_000:.2f}亿"
    if absolute >= 10_000:
        return f"{amount / 10_000:.0f}万"
    return f"{amount:.0f}"


def format_percent(value: Any) -> str:
    number = decimal(value)
    prefix = "+" if number > 0 else ""
    return f"{prefix}{number:.2f}%"


def path_segment(label: str) -> str:
    normalized = unicodedata.normalize("NFKC", label).strip()
    normalized = re.sub(r"[<>:\"/\\|?*]+", "-", normalized)
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-. ")
    return normalized[:80] or hashlib.sha1(label.encode("utf-8")).hexdigest()[:12]


def slug_map(labels: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    used: dict[str, str] = {}
    for label in sorted(set(labels)):
        base = path_segment(label)
        slug = base
        if slug in used and used[slug] != label:
            slug = f"{base}-{hashlib.sha1(label.encode('utf-8')).hexdigest()[:8]}"
        used[slug] = label
        result[label] = slug
    return result


def encoded_path(path: str) -> str:
    return quote(path.strip("/"), safe="/-._~")


def public_href(path: str = "") -> str:
    suffix = encoded_path(path)
    return f"{SITE_BASE}{suffix + '/' if suffix else ''}"


def canonical_url(path: str = "") -> str:
    suffix = encoded_path(path)
    return f"{SITE_ROOT}{suffix + '/' if suffix else ''}"


def json_ld(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def collect_payloads() -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    if HISTORY_DIR.exists():
        for path in sorted(HISTORY_DIR.glob("*.json")):
            payload = read_json(path, {})
            meta = payload.get("meta") or {}
            if meta.get("data_status") != "ok":
                continue
            trade_date = clean_text(meta.get("trade_date") or path.stem, "")
            try:
                datetime.strptime(trade_date, "%Y-%m-%d")
            except ValueError:
                continue
            payloads[trade_date] = payload
    latest = read_json(LATEST_PATH, {})
    latest_meta = latest.get("meta") or {}
    trade_date = clean_text(latest_meta.get("trade_date"), "")
    if latest_meta.get("data_status") == "ok":
        try:
            datetime.strptime(trade_date, "%Y-%m-%d")
        except ValueError:
            pass
        else:
            payloads[trade_date] = latest
    if not payloads:
        raise RuntimeError("no complete trading-day payloads are available")
    return dict(sorted(payloads.items()))


def ranking(payload: dict[str, Any], key: str, field: str, *, use_topics: bool = False) -> list[tuple[str, int]]:
    raw = (payload.get("rankings") or {}).get(key)
    if isinstance(raw, list):
        values = [
            (valid_label(item.get("name")), integer(item.get("count")))
            for item in raw
            if isinstance(item, dict)
        ]
        values = [(name, count) for name, count in values if name and count > 0]
        if values:
            return values
    counts: Counter[str] = Counter()
    for stock in payload.get("limit_ups") or []:
        if not isinstance(stock, dict):
            continue
        labels = topics(stock) if use_topics else [valid_label(stock.get(field))]
        for label in labels:
            if label:
                counts[label] += 1
    return counts.most_common()


def sentiment_summary(payload: dict[str, Any]) -> dict[str, Any]:
    ups = [item for item in payload.get("limit_ups") or [] if isinstance(item, dict)]
    broken = [item for item in payload.get("broken_limits") or [] if isinstance(item, dict)]
    downs = [item for item in payload.get("limit_downs") or [] if isinstance(item, dict)]
    sentiment = payload.get("sentiment") or {}
    highest = integer(sentiment.get("highest_board")) or max(
        (integer(item.get("consecutive_days"), 1) for item in ups), default=0
    )
    first_board = integer(sentiment.get("first_board_count")) or sum(
        integer(item.get("consecutive_days"), 1) <= 1 for item in ups
    )
    broken_rate = decimal(sentiment.get("broken_rate"))
    if not broken_rate and (ups or broken):
        broken_rate = len(broken) / (len(ups) + len(broken)) * 100
    promotion_rate = decimal(sentiment.get("promotion_rate"))
    score = round(max(0, min(100, 50 + len(ups) * 0.22 + highest * 3 - len(downs) * 0.28 - broken_rate * 0.18)))
    mood = "强势" if score >= 70 else "偏强" if score >= 58 else "平衡" if score >= 45 else "偏弱" if score >= 30 else "弱势"
    return {
        "ups": ups,
        "broken": broken,
        "downs": downs,
        "up_count": len(ups),
        "broken_count": len(broken),
        "down_count": len(downs),
        "highest": highest,
        "first_board": first_board,
        "broken_rate": broken_rate,
        "promotion_rate": promotion_rate,
        "score": score,
        "mood": mood,
        "industry_rank": ranking(payload, "industry_limit_rank", "industry"),
        "theme_rank": ranking(payload, "theme_limit_rank", "theme", use_topics=True),
    }


class StaticSiteGenerator:
    def __init__(self) -> None:
        self.payloads = collect_payloads()
        self.trade_dates = list(self.payloads)
        self.latest_date = self.trade_dates[-1]
        self.latest = self.payloads[self.latest_date]
        self.latest_meta = self.latest.get("meta") or {}
        self.archive_start = clean_text(
            self.latest_meta.get("down_archive_start") or self.trade_dates[0], self.trade_dates[0]
        )
        self.records = self._build_records()
        self.by_code = {record["code"]: record for record in self.records}
        self.industries: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.themes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.boards: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in self.records:
            industry = valid_label(record.get("industry"))
            if industry:
                self.industries[industry].append(record)
            for theme in topics(record):
                self.themes[theme].append(record)
            self.boards[record["market_board"]].append(record)
        self.industry_slugs = slug_map(self.industries)
        self.theme_slugs = slug_map(self.themes)
        self.trends_industry: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
        self.trends_theme: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
        self._build_trends()
        self.page_count: Counter[str] = Counter()
        self.internal_link_count = 0
        self.generated_paths: list[str] = []

    def _build_records(self) -> list[dict[str, Any]]:
        catalog = read_json(CATALOG_PATH, {})
        catalog_rows = catalog.get("stocks") or []
        if len(catalog_rows) < 4_000:
            raise RuntimeError("stock-catalog.json is missing or incomplete; run update_stock_catalog.py first")
        stats_by_code = {
            normalize_code(item.get("code")): item
            for item in self.latest.get("stats") or []
            if isinstance(item, dict) and normalize_code(item.get("code"))
        }
        event_by_code: dict[str, dict[str, Any]] = {}
        event_kind: dict[str, set[str]] = defaultdict(set)
        for group, kind in (
            ("limit_ups", "limit"),
            ("broken_limits", "broken"),
            ("limit_downs", "down"),
        ):
            for item in self.latest.get(group) or []:
                if not isinstance(item, dict):
                    continue
                code = normalize_code(item.get("code"))
                if not code:
                    continue
                event_by_code.setdefault(code, {}).update(item)
                event_kind[code].add(kind)
        records: list[dict[str, Any]] = []
        for item in catalog_rows:
            if not isinstance(item, dict):
                continue
            code = normalize_code(item.get("code"))
            if not code:
                continue
            catalog_industry = valid_label(item.get("industry"))
            record = dict(item)
            record.update(stats_by_code.get(code, {}))
            event = event_by_code.get(code, {})
            for key in (
                "name", "market_board", "latest_price", "change_pct", "turnover_amount",
                "float_market_cap", "total_market_cap", "turnover_rate", "themes", "theme", "concept",
                "consecutive_days", "consecutive_down_days",
            ):
                if event.get(key) not in (None, "", [], "-", "--"):
                    record[key] = event[key]
            merged_topics = topics(item) + [value for value in topics(event) if value not in topics(item)]
            if merged_topics:
                record["themes"] = merged_topics
                record["theme"] = "、".join(merged_topics)
            record["code"] = code
            record["name"] = clean_text(record.get("name"), code)
            record["industry"] = catalog_industry or valid_label(event.get("industry")) or valid_label(record.get("industry"))
            record["market_board"] = clean_text(record.get("market_board"), infer_market_board(code))
            record["is_limit_today"] = "limit" in event_kind[code]
            record["is_broken_today"] = "broken" in event_kind[code]
            record["is_down_today"] = "down" in event_kind[code]
            records.append(record)
        return sorted(records, key=lambda value: value["code"])

    def _build_trends(self) -> None:
        for trade_date, payload in self.payloads.items():
            for group, kind in (
                ("limit_ups", "up"),
                ("broken_limits", "broken"),
                ("limit_downs", "down"),
            ):
                for stock in payload.get(group) or []:
                    if not isinstance(stock, dict):
                        continue
                    industry = self.canonical_industry(stock)
                    if industry:
                        self.trends_industry[industry][trade_date][kind] += 1
                    for theme in topics(stock):
                        self.trends_theme[theme][trade_date][kind] += 1

    def canonical_industry(self, stock: dict[str, Any]) -> str:
        code = normalize_code(stock.get("code"))
        record = self.by_code.get(code, {})
        return valid_label(record.get("industry")) or valid_label(stock.get("industry"))

    def payload_ranking(self, payload: dict[str, Any], kind: str) -> list[tuple[str, int]]:
        counts: Counter[str] = Counter()
        for stock in payload.get("limit_ups") or []:
            if not isinstance(stock, dict):
                continue
            labels = [self.canonical_industry(stock)] if kind == "industry" else topics(stock)
            for label in labels:
                if label:
                    counts[label] += 1
        return counts.most_common()

    def summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = sentiment_summary(payload)
        result["industry_rank"] = self.payload_ranking(payload, "industry")
        result["theme_rank"] = self.payload_ranking(payload, "theme")
        return result

    def stock_path(self, code: str) -> str:
        return f"stock/{code}"

    def industry_path(self, label: str) -> str:
        return f"industry/{self.industry_slugs[label]}"

    def theme_path(self, label: str) -> str:
        return f"theme/{self.theme_slugs[label]}"

    def breadcrumb_schema(self, breadcrumbs: list[tuple[str, str]]) -> dict[str, Any]:
        return {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": index,
                    "name": label,
                    "item": canonical_url(path),
                }
                for index, (label, path) in enumerate(breadcrumbs, start=1)
            ],
        }

    def page_html(
        self,
        *,
        title: str,
        description: str,
        path: str,
        breadcrumbs: list[tuple[str, str]],
        content: str,
        schemas: list[dict[str, Any]],
        article: bool = False,
    ) -> str:
        canonical = canonical_url(path)
        breadcrumb_html = "".join(
            f'<span><a href="{esc(public_href(item_path))}">{esc(label)}</a></span>'
            if index < len(breadcrumbs) - 1
            else f"<span>{esc(label)}</span>"
            for index, (label, item_path) in enumerate(breadcrumbs)
        )
        graph = [self.breadcrumb_schema(breadcrumbs), *schemas]
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
  <link rel="canonical" href="{esc(canonical)}">
  <link rel="icon" href="{SITE_BASE}favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="{SITE_BASE}src/seo-pages.css?v=20260717">
  <meta property="og:locale" content="zh_CN">
  <meta property="og:type" content="{'article' if article else 'website'}">
  <meta property="og:site_name" content="{SITE_NAME}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical)}">
  <meta property="og:image" content="{SOCIAL_IMAGE}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(title)}">
  <meta name="twitter:description" content="{esc(description)}">
  <meta name="twitter:image" content="{SOCIAL_IMAGE}">
  <script type="application/ld+json">{json_ld({'@context': 'https://schema.org', '@graph': graph})}</script>
</head>
<body>
  <header class="site-header">
    <div class="site-header__inner">
      <a class="brand" href="{SITE_BASE}"><b>锋</b>股top</a>
      <nav class="site-nav" aria-label="主要导航">
        <a href="{public_href('limit-up')}">每日行情</a>
        <a href="{public_href('review')}">每日复盘</a>
        <a href="{public_href('stock')}">股票</a>
        <a href="{public_href('industry')}">行业</a>
        <a href="{public_href('theme')}">题材</a>
      </nav>
    </div>
  </header>
  <main class="page-shell">
    <nav class="breadcrumbs" aria-label="面包屑">{breadcrumb_html}</nav>
    {content}
    <footer class="site-footer">
      <nav><a href="{SITE_BASE}">行情首页</a><a href="{public_href('limit-up')}">每日行情</a><a href="{public_href('review')}">每日复盘</a><a href="{public_href('stock')}">股票目录</a><a href="{public_href('industry')}">行业目录</a><a href="{public_href('theme')}">题材目录</a></nav>
      <p>数据来源：AKShare 与东方财富公开行情数据。页面仅作市场数据整理，不构成投资建议。</p>
    </footer>
  </main>
</body>
</html>
"""

    def write_page(self, path: str, page_type: str, content: str) -> None:
        target = ROOT / path / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        self.page_count[page_type] += 1
        self.generated_paths.append(path)
        self.internal_link_count += len(re.findall(r'<a\s+[^>]*href="/fenggu-top/', content))

    def record_link(self, record: dict[str, Any], subtitle: str = "") -> str:
        subtitle_html = f"<span>{esc(subtitle)}</span>" if subtitle else ""
        return (
            f'<a class="link-card" href="{public_href(self.stock_path(record["code"]))}">'
            f'<strong>{esc(record["name"])}（{esc(record["code"])}）</strong>{subtitle_html}</a>'
        )

    def topic_links(self, values: list[str], kind: str, limit: int = 20) -> str:
        links: list[str] = []
        for value in values[:limit]:
            if kind == "industry" and value in self.industry_slugs:
                path = self.industry_path(value)
            elif kind == "theme" and value in self.theme_slugs:
                path = self.theme_path(value)
            else:
                continue
            links.append(f'<a href="{public_href(path)}">{esc(value)}</a>')
        return "".join(links) or '<span class="section-note">数据积累中</span>'

    def stock_table(self, stocks: list[dict[str, Any]], kind: str, limit: int | None = None) -> str:
        rows = stocks if limit is None else stocks[:limit]
        if not rows:
            return '<div class="empty">当日无相关股票</div>'
        body: list[str] = []
        for stock in rows:
            code = normalize_code(stock.get("code"))
            record = self.by_code.get(code, stock)
            consecutive = integer(
                stock.get("consecutive_down_days") if kind == "down" else stock.get("consecutive_days"), 1
            )
            if kind == "up":
                state = f"{consecutive}板"
            elif kind == "down":
                state = f"{consecutive}连跌"
            else:
                state = f"炸板{integer(stock.get('open_times'))}次"
            industry = valid_label(record.get("industry")) or valid_label(stock.get("industry"))
            industry_html = (
                f'<a href="{public_href(self.industry_path(industry))}">{esc(industry)}</a>'
                if industry in self.industry_slugs
                else "-"
            )
            stock_themes = topics(stock) or topics(record)
            theme_html = "、".join(
                f'<a href="{public_href(self.theme_path(theme))}">{esc(theme)}</a>'
                for theme in stock_themes[:3]
                if theme in self.theme_slugs
            ) or "-"
            change_class = "number-down" if decimal(stock.get("change_pct")) < 0 else "number-up"
            body.append(
                "<tr>"
                f"<td>{esc(code)}</td>"
                f'<td><a href="{public_href(self.stock_path(code))}">{esc(clean_text(record.get("name"), code))}</a></td>'
                f'<td class="{change_class}">{esc(format_percent(stock.get("change_pct")))}</td>'
                f"<td>{esc(clean_text(record.get('market_board'), infer_market_board(code)))}</td>"
                f"<td>{esc(state)}</td><td>{industry_html}</td><td>{theme_html}</td>"
                "</tr>"
            )
        return (
            '<div class="table-wrap"><table><thead><tr><th>代码</th><th>名称</th><th>涨跌幅</th>'
            '<th>上市板块</th><th>状态</th><th>行业</th><th>题材</th></tr></thead><tbody>'
            + "".join(body)
            + "</tbody></table></div>"
        )

    def trend_table(self, trend: dict[str, Counter[str]]) -> str:
        rows = []
        for trade_date in self.trade_dates[-20:]:
            counts = trend.get(trade_date, Counter())
            rows.append(
                f"<tr><td><a href=\"{public_href(f'limit-up/{trade_date}')}\">{esc(trade_date)}</a></td>"
                f"<td class=\"number-up\">{counts.get('up', 0)}</td>"
                f"<td>{counts.get('broken', 0)}</td>"
                f"<td class=\"number-down\">{counts.get('down', 0)}</td></tr>"
            )
        return (
            '<div class="table-wrap"><table><thead><tr><th>交易日</th><th>涨停</th><th>炸板</th><th>跌停</th>'
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        )

    def related_records(self, record: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        industry = valid_label(record.get("industry"))
        if industry:
            candidates.extend(self.industries.get(industry, []))
        for theme in topics(record)[:3]:
            candidates.extend(self.themes.get(theme, []))
        candidates.extend(self.boards.get(record["market_board"], []))
        result: list[dict[str, Any]] = []
        seen = {record["code"]}
        for candidate in candidates:
            if candidate["code"] in seen:
                continue
            seen.add(candidate["code"])
            result.append(candidate)
            if len(result) >= limit:
                break
        return result

    def generate_stock_pages(self) -> None:
        total = len(self.records)
        for index, record in enumerate(self.records):
            code = record["code"]
            name = record["name"]
            industry = valid_label(record.get("industry"))
            stock_topics = topics(record)
            board = record["market_board"]
            state_badges = [
                f'<span class="badge badge--up">今日涨停：{"是" if record["is_limit_today"] else "否"}</span>',
                f'<span class="badge badge--down">今日跌停：{"是" if record["is_down_today"] else "否"}</span>',
                f'<span class="badge badge--broken">今日炸板：{"是" if record["is_broken_today"] else "否"}</span>',
            ]
            related = self.related_records(record)
            related_html = "".join(
                self.record_link(item, valid_label(item.get("industry")) or item["market_board"])
                for item in related
            )
            prev_record = self.records[index - 1] if index > 0 else None
            next_record = self.records[index + 1] if index + 1 < total else None
            pager = '<nav class="pager" aria-label="上一篇下一篇">'
            pager += (
                f'<a rel="prev" href="{public_href(self.stock_path(prev_record["code"]))}">上一篇：{esc(prev_record["name"])}</a>'
                if prev_record
                else "<span></span>"
            )
            pager += (
                f'<a rel="next" href="{public_href(self.stock_path(next_record["code"]))}">下一篇：{esc(next_record["name"])}</a>'
                if next_record
                else "<span></span>"
            )
            pager += "</nav>"
            industry_link = (
                f'<a href="{public_href(self.industry_path(industry))}">{esc(industry)}</a>'
                if industry in self.industry_slugs
                else "行业数据积累中"
            )
            theme_links = self.topic_links(stock_topics, "theme")
            title = f"{name}（{code}）涨停历史、行业题材与行情数据 - 锋股top"
            description = (
                f"锋股top提供{name}（{code}）所属行业、题材、今日涨停跌停炸板状态、历史涨停次数、"
                f"历史炸板次数、最高连板、最近涨停日期和最近成交额。数据日期{self.latest_date}。"
            )
            overview = (
                f"{esc(name)}（{esc(code)}）为{esc(board)}股票。当前页面以{esc(self.latest_date)}归档行情为准，"
                f"记录其涨停、跌停、炸板状态和可核验的历史统计。"
            )
            event_states = []
            if record["is_limit_today"]:
                event_states.append("收盘涨停")
            if record["is_broken_today"]:
                event_states.append("盘中炸板")
            if record["is_down_today"]:
                event_states.append("收盘跌停")
            event_text = "、".join(event_states) if event_states else "未进入当日涨停、炸板或跌停池"
            taxonomy_text = (
                f"所属行业为{industry}，已识别题材包括{'、'.join(stock_topics[:8])}。"
                if industry and stock_topics
                else f"所属行业为{industry}，题材数据仍在积累。"
                if industry
                else f"行业分类仍在补充，已识别题材包括{'、'.join(stock_topics[:8])}。"
                if stock_topics
                else "行业和题材分类正在从公开数据源持续补充。"
            )
            latest_price = decimal(record.get("latest_price"))
            turnover_amount = decimal(record.get("turnover_amount"))
            price_text = f"{latest_price:.2f}元" if latest_price > 0 else "数据源暂未提供"
            change_text = format_percent(record.get("change_pct")) if latest_price > 0 else "数据源暂未提供"
            turnover_text = format_money(turnover_amount) if turnover_amount > 0 else "数据源暂未提供"
            data_summary = (
                f"截至{self.latest_date}，{name}（{code}）{event_text}。最近行情快照显示，最新价为"
                f"{price_text}，涨跌幅为{change_text}，成交额为{turnover_text}。{taxonomy_text}"
                f"在本站已归档交易日中，该股记录到涨停{integer(record.get('total_limit_count'))}次、"
                f"炸板{integer(record.get('broken_count_total'))}次、跌停{integer(record.get('total_down_count'))}次，"
                f"历史最高连板为{integer(record.get('max_consecutive_days'))}板。"
            )
            content = f"""
<section class="hero">
  <p class="eyebrow">股票数据 · {esc(self.latest_date)}</p>
  <h1>{esc(name)} <small>{esc(code)}</small></h1>
  <p class="lead">{overview}</p>
  <div class="badges"><span class="badge">{esc(board)}</span>{''.join(state_badges)}</div>
  <div class="metric-grid">
    <div class="metric"><span>最新价</span><strong>{decimal(record.get('latest_price')):.2f}</strong></div>
    <div class="metric {'metric--up' if decimal(record.get('change_pct')) >= 0 else 'metric--down'}"><span>最新涨跌幅</span><strong>{esc(format_percent(record.get('change_pct')))}</strong></div>
    <div class="metric"><span>最近成交额</span><strong>{esc(format_money(record.get('turnover_amount')))}</strong></div>
    <div class="metric"><span>所属行业</span><strong>{industry_link}</strong></div>
  </div>
</section>
<section class="section"><h2>股票数据摘要</h2><p>{esc(data_summary)}</p></section>
<section class="section">
  <div class="section-head"><h2>涨停与炸板历史</h2><span class="section-note">统计截至 {esc(self.latest_date)}</span></div>
  <div class="metric-grid">
    <div class="metric metric--up"><span>历史涨停次数</span><strong>{integer(record.get('total_limit_count'))}</strong></div>
    <div class="metric metric--warm"><span>历史炸板次数</span><strong>{integer(record.get('broken_count_total'))}</strong></div>
    <div class="metric metric--up"><span>历史最高连板</span><strong>{integer(record.get('max_consecutive_days'))}板</strong></div>
    <div class="metric"><span>最近涨停日期</span><strong>{esc(clean_text(record.get('last_limit_date'), '暂无记录'))}</strong></div>
    <div class="metric"><span>最近炸板日期</span><strong>{esc(clean_text(record.get('last_broken_date'), '暂无记录'))}</strong></div>
    <div class="metric metric--down"><span>历史跌停次数</span><strong>{integer(record.get('total_down_count'))}</strong></div>
    <div class="metric metric--down"><span>历史最高连跌</span><strong>{integer(record.get('max_consecutive_down_days'))}</strong></div>
    <div class="metric"><span>上市板块</span><strong>{esc(board)}</strong></div>
  </div>
  <p class="notice">历史统计基于本站已归档交易日计算；精确跌停归档起点为 {esc(self.archive_start)}，归档起点以前的次数不作推测。</p>
</section>
<section class="section">
  <h2>行业与题材</h2>
  <p><strong>所属行业：</strong>{industry_link}</p>
  <div class="tag-list">{theme_links}</div>
</section>
<section class="section">
  <div class="section-head"><h2>K线图</h2><span class="section-note">后续预留</span></div>
  <div class="chart-placeholder">K线截图位置已预留；上线前不会使用虚构图片。</div>
</section>
<section class="section">
  <h2>相关推荐</h2>
  <div class="link-grid">{related_html or '<div class="empty">暂无相关推荐</div>'}</div>
  {pager}
</section>
"""
            schemas = [
                {
                    "@type": "Dataset",
                    "name": f"{name}（{code}）行情与涨跌停历史数据",
                    "description": description,
                    "url": canonical_url(self.stock_path(code)),
                    "dateModified": self.latest_date,
                    "creator": {"@type": "Organization", "name": SITE_NAME, "url": SITE_ROOT},
                    "keywords": [name, code, industry or board, *stock_topics[:8]],
                    "variableMeasured": [
                        "今日是否涨停", "今日是否跌停", "今日是否炸板", "历史涨停次数", "历史炸板次数",
                        "历史最高连板", "最近涨停日期", "最近炸板日期", "最近成交额",
                    ],
                }
            ]
            page = self.page_html(
                title=title,
                description=description,
                path=self.stock_path(code),
                breadcrumbs=[("首页", ""), ("股票", "stock"), (f"{name}（{code}）", self.stock_path(code))],
                content=content,
                schemas=schemas,
            )
            self.write_page(self.stock_path(code), "stock", page)

        page_total = (total + STOCKS_PER_INDEX_PAGE - 1) // STOCKS_PER_INDEX_PAGE
        for page_number in range(1, page_total + 1):
            start = (page_number - 1) * STOCKS_PER_INDEX_PAGE
            page_records = self.records[start : start + STOCKS_PER_INDEX_PAGE]
            path = "stock" if page_number == 1 else f"stock/page/{page_number}"
            links = "".join(
                self.record_link(record, f"{record['market_board']} · {valid_label(record.get('industry')) or '行业待补充'}")
                for record in page_records
            )
            pager = '<nav class="pager" aria-label="股票目录分页">'
            if page_number > 1:
                previous = "stock" if page_number == 2 else f"stock/page/{page_number - 1}"
                pager += f'<a rel="prev" href="{public_href(previous)}">上一页</a>'
            else:
                pager += "<span></span>"
            if page_number < page_total:
                pager += f'<a rel="next" href="{public_href(f"stock/page/{page_number + 1}")}">下一页</a>'
            pager += "</nav>"
            content = f"""
<section class="hero"><p class="eyebrow">全 A 股静态目录</p><h1>股票数据页</h1><p class="lead">共收录 {total} 只股票，每只股票均有可直接抓取的独立静态详情页。</p></section>
<section class="section"><div class="section-head"><h2>股票目录</h2><span class="section-note">第 {page_number}/{page_total} 页</span></div><div class="link-grid">{links}</div>{pager}</section>
"""
            description = f"锋股top全A股股票数据目录第{page_number}页，提供股票代码、名称、上市板块、行业题材与涨跌停历史静态详情页。"
            page = self.page_html(
                title=f"A股股票数据目录第{page_number}页 - 锋股top",
                description=description,
                path=path,
                breadcrumbs=[("首页", ""), ("股票", path)],
                content=content,
                schemas=[{"@type": "CollectionPage", "name": f"A股股票数据目录第{page_number}页", "url": canonical_url(path)}],
            )
            self.write_page(path, "stock_index", page)

    def current_for_label(self, label: str, kind: str, group: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for stock in self.latest.get(group) or []:
            if not isinstance(stock, dict):
                continue
            matches = self.canonical_industry(stock) == label if kind == "industry" else label in topics(stock)
            if matches:
                rows.append(stock)
        return rows

    def generate_taxonomy_pages(self, kind: str) -> None:
        groups = self.industries if kind == "industry" else self.themes
        slugs = self.industry_slugs if kind == "industry" else self.theme_slugs
        title_name = "行业" if kind == "industry" else "题材"
        trend_map = self.trends_industry if kind == "industry" else self.trends_theme
        hot_labels = sorted(
            groups,
            key=lambda label: (
                -len(self.current_for_label(label, kind, "limit_ups")),
                -len(groups[label]),
                label,
            ),
        )
        for label in sorted(groups):
            records = sorted(groups[label], key=lambda item: item["code"])
            ups = self.current_for_label(label, kind, "limit_ups")
            broken = self.current_for_label(label, kind, "broken_limits")
            downs = self.current_for_label(label, kind, "limit_downs")
            heat = max(0, min(100, 35 + len(ups) * 9 + len(broken) * 2 - len(downs) * 5))
            leader = sorted(
                ups,
                key=lambda item: (-integer(item.get("consecutive_days"), 1), -decimal(item.get("turnover_amount"))),
            )
            leader_name = clean_text((leader[0] if leader else records[0]).get("name"), "-")
            list_html = "".join(
                self.record_link(record, f"{record['market_board']} · {format_money(record.get('turnover_amount'))}")
                for record in records[:120]
            )
            related_labels = [value for value in hot_labels if value != label][:10]
            related_links = self.topic_links(related_labels, kind)
            event_table = self.stock_table(ups, "up")
            if kind == "theme":
                intro = (
                    f"{label}题材页依据东方财富个股核心题材与本站行情归档聚合生成，当前关联{len(records)}只股票。"
                    "同一股票可以归属多个题材，因此题材计数与行业计数的口径不同。本页只呈现可核验的数据关系，不以行业字段替代题材。"
                )
            else:
                intro = (
                    f"{label}行业页汇总当前已识别的{len(records)}只相关股票，并跟踪该行业每日涨停、炸板、跌停数量。"
                    "行业归属沿用行情数据已有字段，避免另建一套互相冲突的分类规则。"
                )
            path = f"{kind}/{slugs[label]}"
            description = (
                f"锋股top{label}{title_name}数据页：{self.latest_date}涨停{len(ups)}只、跌停{len(downs)}只、"
                f"炸板{len(broken)}只，包含龙头股票、相关股票和历史涨跌停趋势。"
            )
            content = f"""
<section class="hero">
  <p class="eyebrow">{esc(title_name)}数据 · {esc(self.latest_date)}</p>
  <h1>{esc(label)}{esc(title_name)}</h1>
  <p class="lead">{esc(intro)}</p>
  <div class="metric-grid">
    <div class="metric metric--up"><span>今日涨停数量</span><strong>{len(ups)}只</strong></div>
    <div class="metric metric--down"><span>今日跌停数量</span><strong>{len(downs)}只</strong></div>
    <div class="metric metric--warm"><span>{esc(title_name)}热度</span><strong>{heat}</strong></div>
    <div class="metric"><span>{esc(title_name)}龙头</span><strong>{esc(leader_name)}</strong></div>
  </div>
</section>
<section class="section"><div class="section-head"><h2>今日涨停股票</h2><span class="section-note">{len(ups)}只</span></div>{event_table}</section>
<section class="section"><div class="section-head"><h2>历史涨停与炸板趋势</h2><span class="section-note">最近20个已归档交易日</span></div>{self.trend_table(trend_map.get(label, {}))}</section>
<section class="section"><div class="section-head"><h2>{esc(title_name)}所有股票</h2><span class="section-note">当前已识别 {len(records)} 只</span></div><div class="link-grid">{list_html}</div></section>
<section class="section"><h2>相关文章与相关{esc(title_name)}</h2><div class="tag-list">{related_links}</div><p class="section-note">可在每日复盘中继续查看该{esc(title_name)}出现涨停或跌停时的市场结构。</p></section>
"""
            schema = {
                "@type": "Dataset",
                "name": f"{label}{title_name}涨跌停与相关股票数据",
                "description": description,
                "url": canonical_url(path),
                "dateModified": self.latest_date,
                "creator": {"@type": "Organization", "name": SITE_NAME, "url": SITE_ROOT},
                "variableMeasured": ["今日涨停数量", "今日跌停数量", "炸板数量", "历史涨停趋势", "历史炸板趋势"],
            }
            page = self.page_html(
                title=f"{label}{title_name}涨停、跌停、龙头股与历史趋势 - 锋股top",
                description=description,
                path=path,
                breadcrumbs=[("首页", ""), (title_name, kind), (label, path)],
                content=content,
                schemas=[schema],
            )
            self.write_page(path, kind, page)

        cards = "".join(
            f'<a class="link-card" href="{public_href(f"{kind}/{slugs[label]}")}"><strong>{esc(label)}</strong>'
            f'<span>相关股票 {len(groups[label])} 只 · 今日涨停 {len(self.current_for_label(label, kind, "limit_ups"))} 只</span></a>'
            for label in hot_labels
        )
        content = f"""
<section class="hero"><p class="eyebrow">市场分类目录</p><h1>{esc(title_name)}数据</h1><p class="lead">共生成 {len(groups)} 个{esc(title_name)}静态页，可按当前涨停热度和相关股票数量浏览。</p></section>
<section class="section"><div class="link-grid">{cards}</div></section>
"""
        page = self.page_html(
            title=f"A股{title_name}涨停排行与股票目录 - 锋股top",
            description=f"锋股top A股{title_name}数据目录，收录{len(groups)}个{title_name}页面，提供涨停、跌停、炸板、龙头股票和历史趋势。",
            path=kind,
            breadcrumbs=[("首页", ""), (title_name, kind)],
            content=content,
            schemas=[{"@type": "CollectionPage", "name": f"A股{title_name}数据目录", "url": canonical_url(kind)}],
        )
        self.write_page(kind, f"{kind}_index", page)

    def board_distribution(self, stocks: list[dict[str, Any]]) -> list[tuple[str, int]]:
        counts = Counter(
            clean_text(stock.get("market_board"), infer_market_board(normalize_code(stock.get("code"))))
            for stock in stocks
        )
        return counts.most_common()

    def rank_list(self, items: list[tuple[str, int]], kind: str) -> str:
        rows = []
        for index, (label, count) in enumerate(items[:10], start=1):
            if kind == "industry" and label in self.industry_slugs:
                label_html = f'<a href="{public_href(self.industry_path(label))}">{esc(label)}</a>'
            elif kind == "theme" and label in self.theme_slugs:
                label_html = f'<a href="{public_href(self.theme_path(label))}">{esc(label)}</a>'
            else:
                label_html = esc(label)
            rows.append(f"<li><b>{index}</b><strong>{label_html}</strong><span>{count}只</span></li>")
        return f'<ol class="rank-list">{"".join(rows)}</ol>' if rows else '<div class="empty">暂无排行数据</div>'

    def generate_daily_market_pages(self) -> None:
        for date_index, trade_date in enumerate(self.trade_dates):
            payload = self.payloads[trade_date]
            summary = self.summary(payload)
            previous = self.trade_dates[date_index - 1] if date_index > 0 else ""
            next_date = self.trade_dates[date_index + 1] if date_index + 1 < len(self.trade_dates) else ""
            board_rank = self.board_distribution(summary["ups"])
            pager = '<nav class="pager" aria-label="前后交易日">'
            pager += (
                f'<a rel="prev" href="{public_href(f"limit-up/{previous}")}">上一交易日：{esc(previous)}</a>'
                if previous else "<span></span>"
            )
            pager += (
                f'<a rel="next" href="{public_href(f"limit-up/{next_date}")}">下一交易日：{esc(next_date)}</a>'
                if next_date else "<span></span>"
            )
            pager += "</nav>"
            path = f"limit-up/{trade_date}"
            description = (
                f"{format_date_cn(trade_date)}A股涨停行情：收盘涨停{summary['up_count']}只、炸板{summary['broken_count']}只、"
                f"跌停{summary['down_count']}只，最高{summary['highest']}板，包含行业和题材排行。"
            )
            content = f"""
<section class="hero">
  <p class="eyebrow">每日行情归档</p><h1>{esc(format_date_cn(trade_date))}A股涨停排行</h1>
  <p class="lead">当日涨停、炸板、跌停、连板高度、行业排行、题材排行与市场情绪的完整静态归档。</p>
  <div class="metric-grid">
    <div class="metric metric--up"><span>今日涨停</span><strong>{summary['up_count']}只</strong></div>
    <div class="metric metric--warm"><span>今日炸板</span><strong>{summary['broken_count']}只</strong></div>
    <div class="metric metric--down"><span>今日跌停</span><strong>{summary['down_count']}只</strong></div>
    <div class="metric metric--up"><span>连板高度</span><strong>{summary['highest']}板</strong></div>
    <div class="metric"><span>首板数量</span><strong>{summary['first_board']}只</strong></div>
    <div class="metric"><span>炸板率</span><strong>{summary['broken_rate']:.1f}%</strong></div>
    <div class="metric"><span>市场情绪</span><strong>{summary['mood']}</strong></div>
    <div class="metric"><span>情绪评分</span><strong>{summary['score']}</strong></div>
  </div>
</section>
<section class="section"><div class="section-head"><h2>今日涨停排行</h2><span class="section-note">{summary['up_count']}只</span></div>{self.stock_table(summary['ups'], 'up')}</section>
<section class="section"><div class="section-head"><h2>今日炸板排行</h2><span class="section-note">{summary['broken_count']}只</span></div>{self.stock_table(summary['broken'], 'broken')}</section>
<section class="section"><div class="section-head"><h2>今日跌停排行</h2><span class="section-note">{summary['down_count']}只</span></div>{self.stock_table(summary['downs'], 'down')}</section>
<div class="two-column">
  <section class="section"><h2>行业涨停排行</h2>{self.rank_list(summary['industry_rank'], 'industry')}</section>
  <section class="section"><h2>题材涨停排行</h2>{self.rank_list(summary['theme_rank'], 'theme')}</section>
</div>
<section class="section"><h2>上市板块分布</h2>{self.rank_list(board_rank, 'board')}{pager}<p><a href="{public_href(f'review/{trade_date}')}">阅读当日市场复盘</a></p></section>
"""
            item_list = [
                {
                    "@type": "ListItem",
                    "position": position,
                    "url": canonical_url(self.stock_path(normalize_code(stock.get("code")))),
                    "name": clean_text(stock.get("name"), normalize_code(stock.get("code"))),
                }
                for position, stock in enumerate(summary["ups"], start=1)
            ]
            schemas = [
                {
                    "@type": "Dataset",
                    "name": f"{format_date_cn(trade_date)}A股涨停、炸板与跌停数据",
                    "description": description,
                    "url": canonical_url(path),
                    "dateModified": trade_date,
                    "creator": {"@type": "Organization", "name": SITE_NAME, "url": SITE_ROOT},
                    "variableMeasured": ["涨停数量", "炸板数量", "跌停数量", "连板高度", "行业排行", "题材排行", "市场情绪"],
                },
                {"@type": "ItemList", "name": f"{trade_date}涨停股票排行", "itemListElement": item_list},
            ]
            page = self.page_html(
                title=f"{format_date_cn(trade_date)}A股涨停排行、炸板跌停与连板高度 - 锋股top",
                description=description,
                path=path,
                breadcrumbs=[("首页", ""), ("每日行情", "limit-up"), (trade_date, path)],
                content=content,
                schemas=schemas,
            )
            self.write_page(path, "limit_up_daily", page)

        links = "".join(
            f'<a class="link-card" href="{public_href(f"limit-up/{trade_date}")}"><strong>{esc(format_date_cn(trade_date))}</strong>'
            f'<span>涨停 {self.summary(self.payloads[trade_date])["up_count"]} · 炸板 {self.summary(self.payloads[trade_date])["broken_count"]} · 跌停 {self.summary(self.payloads[trade_date])["down_count"]}</span></a>'
            for trade_date in reversed(self.trade_dates)
        )
        content = f"""
<section class="hero"><p class="eyebrow">每日市场数据</p><h1>A股涨停行情归档</h1><p class="lead">按交易日浏览涨停、炸板、跌停、连板高度、行业题材排行和市场情绪。</p></section>
<section class="section"><div class="link-grid">{links}</div></section>
"""
        page = self.page_html(
            title="A股每日涨停排行、炸板跌停与连板高度归档 - 锋股top",
            description="锋股top每日A股涨停行情归档，提供涨停、炸板、跌停、连板高度、行业题材排行和市场情绪。",
            path="limit-up",
            breadcrumbs=[("首页", ""), ("每日行情", "limit-up")],
            content=content,
            schemas=[{"@type": "CollectionPage", "name": "A股每日涨停行情归档", "url": canonical_url("limit-up")}],
        )
        self.write_page("limit-up", "limit_up_index", page)

    def review_sections(self, trade_date: str, payload: dict[str, Any]) -> list[tuple[str, str]]:
        summary = self.summary(payload)
        industry_text = "、".join(f"{name}{count}只" for name, count in summary["industry_rank"][:5]) or "行业涨停分布较为分散"
        theme_text = "、".join(f"{name}{count}只" for name, count in summary["theme_rank"][:6]) or "题材数据未形成集中排行"
        leader_rows = sorted(
            summary["ups"],
            key=lambda item: (-integer(item.get("consecutive_days"), 1), -decimal(item.get("turnover_amount"))),
        )[:8]
        leader_text = "、".join(
            f"{clean_text(item.get('name'))}{integer(item.get('consecutive_days'), 1)}板"
            for item in leader_rows
        ) or "当日没有形成可列示的连板股票"
        broken_industries = Counter(valid_label(item.get("industry")) for item in summary["broken"])
        broken_industries.pop("", None)
        broken_text = "、".join(f"{name}{count}只" for name, count in broken_industries.most_common(5)) or "炸板行业分布不集中"
        down_industries = Counter(valid_label(item.get("industry")) for item in summary["downs"])
        down_industries.pop("", None)
        down_text = "、".join(f"{name}{count}只" for name, count in down_industries.most_common(5)) or "跌停行业未形成明显集中"
        board_text = "、".join(f"{name}{count}只" for name, count in self.board_distribution(summary["ups"]))
        sections = [
            (
                "市场概览",
                f"{format_date_cn(trade_date)}收盘数据中，A股共有{summary['up_count']}只股票保持涨停，{summary['broken_count']}只股票在盘中触及涨停后未能封住，另有{summary['down_count']}只股票收盘跌停。"
                f"当日首板数量为{summary['first_board']}只，市场最高连板为{summary['highest']}板，按涨停池与炸板池合并计算的炸板率约为{summary['broken_rate']:.1f}%。"
                f"本站依据涨停数量、跌停数量、连板高度和炸板率得到情绪评分{summary['score']}分，对应状态为“{summary['mood']}”。这是一项结构化数据评分，不代表对指数涨跌或次日收益的预测。",
            ),
            (
                "连板结构与龙头股",
                f"连板结构方面，当日高度标杆为{summary['highest']}板。按连板高度和成交额排序，活跃股票包括{leader_text}。"
                "高位股数量能够反映短线资金愿意承受的接力高度，但单一高度并不能独立判断市场强弱，还需要同时观察首板供给、二板晋级、炸板率和跌停扩散。"
                f"本日首板占涨停股的比例约为{(summary['first_board'] / max(summary['up_count'], 1) * 100):.1f}%，说明新增热点与存量连板之间的结构可以通过每日归档继续对比。",
            ),
            (
                "热点行业",
                f"行业涨停数量靠前的方向为{industry_text}。行业排行按当日收盘仍然涨停的股票统计，不包含炸板股和跌停股，因此与页面涨停表保持同一口径。"
                "观察行业强度时，除了绝对数量，还应对比该行业相关股票总数、涨停持续天数以及是否出现同步跌停。若同一行业同时存在较多涨停与跌停，通常意味着内部走势分化，不能只凭排行名称作简单结论。"
                "页面中的行业链接可继续查看相关股票和最近二十个已归档交易日的涨停、炸板、跌停趋势。",
            ),
            (
                "热点题材",
                f"题材维度中，数量靠前的标签为{theme_text}。题材来自东方财富个股核心题材，一只股票可以同时计入多个题材，因此各题材数量相加会大于当日涨停股票总数。"
                "这种多标签口径更适合观察资金围绕同一产业链或事件线索的扩散范围，但不应把行业名称直接当作题材。本站会对逗号、顿号和分号分隔的题材进行拆分、去重，并过滤“其他”“未知”等无效标签。"
                "进入单个题材页后，可以查看龙头股、相关股票以及历史趋势。",
            ),
            (
                "炸板结构",
                f"当日炸板股共{summary['broken_count']}只，主要分布在{broken_text}。当前公开池数据记录股票是否炸板、开板次数和收盘状态，但并不直接提供每只股票炸板的确定因果。"
                "因此复盘只从可验证的结构讨论：炸板率上升通常意味着封板稳定性下降；若炸板集中在高位连板股，接力风险与首板扩散的含义不同；若炸板分散在多个行业，则可能更接近整体风险偏好的变化。"
                "本站不会把盘口波动、消息传闻或主力意图写成未经证实的“炸板原因”。",
            ),
            (
                "跌停与风险分布",
                f"收盘跌停股票共{summary['down_count']}只，行业分布靠前的是{down_text}。跌停数量用于衡量风险端是否扩散，并与涨停数量共同构成市场宽度。"
                f"当日涨停与跌停数量之比约为{summary['up_count'] / max(summary['down_count'], 1):.2f}。这一比例高于一，代表涨停数量更多；低于一，则代表跌停数量占优，但仍需结合指数、成交额和连续多日变化观察。"
                f"跌停历史采用精确归档口径，本站当前明确的跌停归档起点为{self.archive_start}，起点以前的数据不通过涨跌幅反推。",
            ),
            (
                "市场情绪判断",
                f"综合当日{summary['up_count']}只涨停、{summary['broken_count']}只炸板、{summary['down_count']}只跌停、{summary['highest']}板高度和{summary['broken_rate']:.1f}%炸板率，市场情绪评分为{summary['score']}分。"
                f"评分对应“{summary['mood']}”区间，主要用于统一比较不同交易日，不是买卖信号。次日跟踪可以关注三个数据点：高位连板股是否继续晋级，今日首板是否出现稳定的二板反馈，以及今日强势行业的跌停或炸板数量是否明显上升。"
                "当这三项同时改善时，短线情绪通常更有持续性；若连板高度下降且炸板、跌停同步增加，则应把风险变化放在更优先的位置。",
            ),
            (
                "数据口径与使用方法",
                "本页正文由每日收盘后的结构化行情自动生成，所有股票数量、行业排行、题材排行、连板高度和日期均来自当日归档数据。自动生成的目的，是把同一套统计口径持续应用到每个交易日，而不是批量堆叠与数据无关的关键词。"
                "阅读时可先从市场概览判断涨停与跌停的宽度，再看连板结构判断短线高度，随后进入行业和题材页面核对具体股票，最后结合炸板与跌停分布评估风险。"
                "数据源可能因接口调整、停牌或归类变化出现延迟，本站保留原始交易日字段并在页面上明确数据日期，避免把上一交易日数据误当作今日数据。",
            ),
        ]
        return sections

    def generate_review_pages(self) -> None:
        for index, trade_date in enumerate(self.trade_dates):
            payload = self.payloads[trade_date]
            summary = self.summary(payload)
            sections = self.review_sections(trade_date, payload)
            article_html = "".join(f"<h2>{esc(title)}</h2><p>{esc(body)}</p>" for title, body in sections)
            previous = self.trade_dates[index - 1] if index > 0 else ""
            next_date = self.trade_dates[index + 1] if index + 1 < len(self.trade_dates) else ""
            pager = '<nav class="pager" aria-label="前后复盘">'
            pager += (
                f'<a rel="prev" href="{public_href(f"review/{previous}")}">上一篇：{esc(previous)}复盘</a>'
                if previous else "<span></span>"
            )
            pager += (
                f'<a rel="next" href="{public_href(f"review/{next_date}")}">下一篇：{esc(next_date)}复盘</a>'
                if next_date else "<span></span>"
            )
            pager += "</nav>"
            path = f"review/{trade_date}"
            description = (
                f"{format_date_cn(trade_date)}A股涨停复盘：涨停{summary['up_count']}只、炸板{summary['broken_count']}只、"
                f"跌停{summary['down_count']}只，分析连板高度、热点行业、热门题材与市场情绪。"
            )
            content = f"""
<article>
  <header class="hero"><p class="eyebrow">每日收盘复盘</p><h1>{esc(format_date_cn(trade_date))}A股涨停复盘</h1><p class="lead">基于当日真实涨停、炸板、跌停、行业和题材数据自动整理。</p></header>
  <section class="section article-body">{article_html}<p><a href="{public_href(f'limit-up/{trade_date}')}">查看当日完整涨停、炸板和跌停股票表</a></p>{pager}</section>
</article>
"""
            schema = {
                "@type": "Article",
                "headline": f"{format_date_cn(trade_date)}A股涨停复盘",
                "description": description,
                "datePublished": trade_date,
                "dateModified": trade_date,
                "mainEntityOfPage": canonical_url(path),
                "author": {"@type": "Organization", "name": SITE_NAME, "url": SITE_ROOT},
                "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE_ROOT},
                "image": SOCIAL_IMAGE,
                "articleSection": ["A股复盘", "涨停数据", "市场情绪"],
            }
            page = self.page_html(
                title=f"{format_date_cn(trade_date)}A股涨停复盘：热点板块、题材与市场情绪 - 锋股top",
                description=description,
                path=path,
                breadcrumbs=[("首页", ""), ("每日复盘", "review"), (trade_date, path)],
                content=content,
                schemas=[schema],
                article=True,
            )
            self.write_page(path, "review_daily", page)

        links = "".join(
            f'<a class="link-card" href="{public_href(f"review/{trade_date}")}"><strong>{esc(format_date_cn(trade_date))}复盘</strong>'
            f'<span>热点行业、题材、龙头与情绪评分</span></a>'
            for trade_date in reversed(self.trade_dates)
        )
        content = f"""
<section class="hero"><p class="eyebrow">数据驱动的每日复盘</p><h1>A股市场复盘</h1><p class="lead">每个交易日收盘后，根据真实涨停、炸板、跌停、行业和题材数据生成静态复盘。</p></section>
<section class="section"><div class="link-grid">{links}</div></section>
"""
        page = self.page_html(
            title="A股每日涨停复盘、热点行业题材与市场情绪 - 锋股top",
            description="锋股top A股每日复盘归档，基于真实涨停、炸板、跌停、行业题材与连板数据分析市场情绪。",
            path="review",
            breadcrumbs=[("首页", ""), ("每日复盘", "review")],
            content=content,
            schemas=[{"@type": "CollectionPage", "name": "A股每日市场复盘", "url": canonical_url("review")}],
        )
        self.write_page("review", "review_index", page)

    def update_home_fallback(self) -> None:
        source = INDEX_PATH.read_text(encoding="utf-8")
        if FALLBACK_START not in source or FALLBACK_END not in source:
            return
        summary = self.summary(self.latest)
        top_stocks = sorted(
            summary["ups"],
            key=lambda item: (-integer(item.get("consecutive_days"), 1), normalize_code(item.get("code"))),
        )[:10]
        stock_items = "".join(
            f'<li><a href="{public_href(self.stock_path(normalize_code(stock.get("code"))))}">{esc(clean_text(stock.get("name")))}</a>'
            f'（{esc(normalize_code(stock.get("code")))}）{integer(stock.get("consecutive_days"), 1)}板</li>'
            for stock in top_stocks
        )
        fallback = f"""{FALLBACK_START}
    <noscript>
      <section class="seo-fallback" aria-label="锋股top静态行情摘要">
        <h1>{esc(format_date_cn(self.latest_date))}A股涨停股票排行</h1>
        <p>今日涨停股票 {summary['up_count']} 只，炸板 {summary['broken_count']} 只，跌停 {summary['down_count']} 只，市场最高 {summary['highest']} 板。</p>
        <h2>今日涨停股票</h2><ol>{stock_items}</ol>
        <p><a href="{public_href(f'limit-up/{self.latest_date}')}">查看完整每日行情</a> · <a href="{public_href(f'review/{self.latest_date}')}">查看每日复盘</a> · <a href="{public_href('stock')}">浏览全部股票</a></p>
      </section>
    </noscript>
    {FALLBACK_END}"""
        start = source.index(FALLBACK_START)
        end = source.index(FALLBACK_END, start) + len(FALLBACK_END)
        INDEX_PATH.write_text(source[:start] + fallback + source[end:], encoding="utf-8", newline="\n")

    def clean_generated_roots(self) -> None:
        for name in (*GENERATED_ROOTS, *LEGACY_GENERATED_ROOTS):
            target = (ROOT / name).resolve()
            if target.parent != ROOT.resolve() or target.name != name:
                raise RuntimeError(f"refusing to remove unexpected path: {target}")
            if target.exists():
                shutil.rmtree(target)

    def generate(self) -> dict[str, Any]:
        self.clean_generated_roots()
        self.generate_stock_pages()
        self.generate_taxonomy_pages("industry")
        self.generate_taxonomy_pages("theme")
        self.generate_daily_market_pages()
        self.generate_review_pages()
        self.update_home_fallback()
        manifest = {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "trade_date": self.latest_date,
            "archive_start": self.trade_dates[0],
            "counts": dict(sorted(self.page_count.items())),
            "total_pages": sum(self.page_count.values()),
            "internal_links": self.internal_link_count,
            "stock_count": len(self.records),
            "industry_count": len(self.industries),
            "theme_count": len(self.themes),
            "trading_day_count": len(self.trade_dates),
        }
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
        return manifest


def main() -> None:
    manifest = StaticSiteGenerator().generate()
    print(
        "static SEO pages generated: "
        f"{manifest['total_pages']} pages, {manifest['internal_links']} internal links, "
        f"{manifest['stock_count']} stocks, {manifest['industry_count']} industries, "
        f"{manifest['theme_count']} themes, {manifest['trading_day_count']} trading days"
    )


if __name__ == "__main__":
    main()
