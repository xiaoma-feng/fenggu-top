from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
LATEST_PATH = DATA_DIR / "latest.json"
INDEX_PATH = ROOT / "index.html"
NEWS_DIR = ROOT / "news"
SITE_ROOT = "https://xiaoma-feng.github.io/fenggu-top/"
SOCIAL_IMAGE = f"{SITE_ROOT}social-preview.png"
ORGANIZATION_ID = f"{SITE_ROOT}#organization"
WEBSITE_ID = f"{SITE_ROOT}#website"
FALLBACK_START = "<!-- SEO_FALLBACK_START -->"
FALLBACK_END = "<!-- SEO_FALLBACK_END -->"
EXCLUDED_TOPICS = {"", "-", "--", "其他", "未知", "暂无", "暂无数据", "空值"}
TOPIC_SPLIT_RE = re.compile(r"[,，、;；|/]+")


def read_payload(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


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


def text(value: Any, fallback: str = "-") -> str:
    value = str(value or "").strip()
    return value if value else fallback


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def format_date_cn(date_text: str) -> str:
    value = datetime.strptime(date_text, "%Y-%m-%d")
    return f"{value.year}年{value.month}月{value.day}日"


def format_percent(value: Any) -> str:
    number = decimal(value)
    prefix = "+" if number > 0 else ""
    return f"{prefix}{number:.2f}%"


def format_money(value: Any) -> str:
    number = decimal(value)
    absolute = abs(number)
    if absolute >= 100_000_000:
        return f"{number / 100_000_000:.2f}亿"
    if absolute >= 10_000:
        return f"{number / 10_000:.0f}万"
    return f"{number:.0f}"


def is_publishable(payload: dict[str, Any]) -> bool:
    meta = payload.get("meta") or {}
    if meta.get("data_status") != "ok":
        return False
    return any(
        isinstance(payload.get(name), list) and payload.get(name)
        for name in ("limit_ups", "broken_limits", "limit_downs")
    )


def collect_payloads() -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    if HISTORY_DIR.exists():
        for path in sorted(HISTORY_DIR.glob("*.json")):
            payload = read_payload(path)
            if not payload or not is_publishable(payload):
                continue
            trade_date = str((payload.get("meta") or {}).get("trade_date") or path.stem)
            try:
                datetime.strptime(trade_date, "%Y-%m-%d")
            except ValueError:
                continue
            payloads[trade_date] = payload

    latest = read_payload(LATEST_PATH)
    if latest and is_publishable(latest):
        trade_date = str((latest.get("meta") or {}).get("trade_date") or "")
        try:
            datetime.strptime(trade_date, "%Y-%m-%d")
        except ValueError:
            pass
        else:
            payloads[trade_date] = latest
    return dict(sorted(payloads.items()))


def stock_topics(stock: dict[str, Any]) -> list[str]:
    raw_topics: list[str] = []
    themes = stock.get("themes")
    if isinstance(themes, list):
        raw_topics.extend(str(item) for item in themes)
    for key in ("theme", "concept"):
        value = stock.get(key)
        if value:
            raw_topics.extend(TOPIC_SPLIT_RE.split(str(value)))

    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_topics:
        topic = raw.strip()
        if topic in EXCLUDED_TOPICS or topic in seen:
            continue
        seen.add(topic)
        result.append(topic)
    return result


def ranking(
    payload: dict[str, Any],
    ranking_key: str,
    stock_field: str,
    *,
    themes: bool = False,
    limit: int = 10,
) -> list[dict[str, Any]]:
    raw = (payload.get("rankings") or {}).get(ranking_key)
    if isinstance(raw, list):
        cleaned = [
            {"name": text(item.get("name")), "count": integer(item.get("count"))}
            for item in raw
            if isinstance(item, dict)
            and text(item.get("name"), "") not in EXCLUDED_TOPICS
            and integer(item.get("count")) > 0
        ]
        if cleaned:
            return cleaned[:limit]

    counts: Counter[str] = Counter()
    for stock in payload.get("limit_ups") or []:
        if not isinstance(stock, dict):
            continue
        values = stock_topics(stock) if themes else [text(stock.get(stock_field), "")]
        for value in values:
            if value and value not in EXCLUDED_TOPICS:
                counts[value] += 1
    return [{"name": name, "count": count} for name, count in counts.most_common(limit)]


def ranked_limit_ups(payload: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
    stocks = [item for item in payload.get("limit_ups") or [] if isinstance(item, dict)]
    return sorted(
        stocks,
        key=lambda item: (
            -integer(item.get("consecutive_days"), 1),
            -decimal(item.get("change_pct")),
            text(item.get("code")),
        ),
    )[:limit]


def summary_values(payload: dict[str, Any]) -> dict[str, Any]:
    ups = [item for item in payload.get("limit_ups") or [] if isinstance(item, dict)]
    broken = [item for item in payload.get("broken_limits") or [] if isinstance(item, dict)]
    downs = [item for item in payload.get("limit_downs") or [] if isinstance(item, dict)]
    sentiment = payload.get("sentiment") or {}
    highest_board = integer(sentiment.get("highest_board"))
    if not highest_board:
        highest_board = max((integer(item.get("consecutive_days"), 1) for item in ups), default=0)
    first_board = integer(sentiment.get("first_board_count"))
    if not first_board:
        first_board = sum(integer(item.get("consecutive_days"), 1) <= 1 for item in ups)
    broken_rate = decimal(sentiment.get("broken_rate"))
    if not broken_rate and ups:
        broken_rate = len(broken) / (len(ups) + len(broken)) * 100

    industry_rank = ranking(payload, "industry_limit_rank", "industry")
    theme_rank = ranking(payload, "theme_limit_rank", "theme", themes=True)
    leaders = [
        text(item.get("name"))
        for item in ups
        if integer(item.get("consecutive_days"), 1) == highest_board
    ]
    return {
        "ups": ups,
        "broken": broken,
        "downs": downs,
        "up_count": len(ups),
        "broken_count": len(broken),
        "down_count": len(downs),
        "highest_board": highest_board,
        "first_board": first_board,
        "broken_rate": broken_rate,
        "industry_rank": industry_rank,
        "theme_rank": theme_rank,
        "leaders": leaders,
    }


def json_ld(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_rank_list(items: list[dict[str, Any]], empty_text: str) -> str:
    if not items:
        return f'<p class="empty">{escape(empty_text)}</p>'
    rows = "".join(
        f"<li><span>{index}</span><strong>{escape(item['name'])}</strong><em>{integer(item['count'])}只</em></li>"
        for index, item in enumerate(items, start=1)
    )
    return f'<ol class="ranking">{rows}</ol>'


def render_stock_table(stocks: list[dict[str, Any]]) -> str:
    if not stocks:
        return '<p class="empty">当日无收盘涨停股票。</p>'
    rows = []
    for stock in stocks:
        topics = "、".join(stock_topics(stock)[:6]) or "-"
        rows.append(
            "<tr>"
            f"<td>{escape(text(stock.get('code')))}</td>"
            f"<td>{escape(text(stock.get('name')))}</td>"
            f'<td class="rise">{escape(format_percent(stock.get("change_pct")))}</td>'
            f"<td>{escape(text(stock.get('market_board')))}</td>"
            f"<td>{integer(stock.get('consecutive_days'), 1)}板</td>"
            f"<td>{escape(text(stock.get('industry')))}</td>"
            f"<td>{escape(topics)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table>'
        "<caption>收盘涨停股票排行</caption>"
        "<thead><tr><th>代码</th><th>名称</th><th>涨幅</th><th>上市板块</th>"
        "<th>连板</th><th>行业</th><th>题材</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def page_css() -> str:
    return """
      :root{color-scheme:dark;font-family:"Microsoft YaHei","PingFang SC","Segoe UI",Arial,sans-serif}
      *{box-sizing:border-box}
      body{margin:0;background:#070b15;color:#edf4ff;line-height:1.65}
      a{color:#8bbcff}
      .wrap{margin:0 auto;max-width:1160px;padding:24px}
      .site-head,.hero,.panel,.metric{border:1px solid rgba(126,151,190,.18);background:#101a2d}
      .site-head{align-items:center;display:flex;justify-content:space-between;padding:14px 18px}
      .brand{color:#fff;font-size:20px;font-weight:800;text-decoration:none}
      .site-head nav{display:flex;gap:18px}
      .hero{margin-top:18px;padding:28px}
      .eyebrow{color:#ff9344;font-size:13px;font-weight:700;margin:0 0 8px}
      h1{font-size:30px;line-height:1.3;margin:0}
      .lead{color:#aebbd0;max-width:850px}
      .metrics{display:grid;gap:12px;grid-template-columns:repeat(6,minmax(0,1fr));margin:16px 0}
      .metric{padding:16px}
      .metric strong{display:block;font-size:26px;line-height:1.2}
      .metric span{color:#9eacc2;font-size:13px}
      .panel{margin:16px 0;padding:22px}
      .panel h2{font-size:20px;margin:0 0 14px}
      .grid{display:grid;gap:16px;grid-template-columns:repeat(2,minmax(0,1fr))}
      .ranking{list-style:none;margin:0;padding:0}
      .ranking li{align-items:center;border-bottom:1px solid rgba(126,151,190,.12);display:grid;gap:12px;grid-template-columns:28px 1fr auto;padding:9px 0}
      .ranking li>span{color:#ff9344;font-weight:800}
      .ranking em{color:#c9d5e6;font-style:normal}
      .table-wrap{overflow-x:auto}
      table{border-collapse:collapse;min-width:820px;width:100%}
      caption{height:1px;overflow:hidden;position:absolute;width:1px}
      th,td{border-bottom:1px solid rgba(126,151,190,.12);padding:10px;text-align:left;vertical-align:top}
      th{background:#192640;color:#b8c5d8;font-size:13px}
      td{font-size:14px}
      .rise{color:#ff5f70;font-weight:700}
      .down{color:#2fd18b}
      .meta,.empty,footer{color:#91a0b8}
      .date-list{display:grid;gap:10px;grid-template-columns:repeat(3,minmax(0,1fr));list-style:none;padding:0}
      .date-list a{background:#101a2d;border:1px solid rgba(126,151,190,.18);display:block;padding:14px;text-decoration:none}
      footer{font-size:13px;padding:18px 0 34px}
      @media(max-width:850px){
        .wrap{padding:12px}
        .site-head{align-items:flex-start;gap:10px}
        .site-head nav{flex-wrap:wrap;gap:8px 12px}
        .hero{padding:20px}
        h1{font-size:24px}
        .metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
        .grid,.date-list{grid-template-columns:1fr}
      }
    """


def schema_graph(
    *,
    trade_date: str,
    description: str,
    title: str,
    page_url: str,
    updated_at: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    published = f"{trade_date}T15:30:00+08:00"
    modified = published
    if updated_at:
        try:
            modified_dt = datetime.strptime(updated_at, "%Y-%m-%d %H:%M")
            modified = modified_dt.strftime("%Y-%m-%dT%H:%M:00+08:00")
        except ValueError:
            pass
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": ORGANIZATION_ID,
                "name": "锋股top",
                "url": SITE_ROOT,
                "logo": f"{SITE_ROOT}favicon.svg",
            },
            {
                "@type": "WebSite",
                "@id": WEBSITE_ID,
                "url": SITE_ROOT,
                "name": "锋股top",
                "inLanguage": "zh-CN",
                "publisher": {"@id": ORGANIZATION_ID},
            },
            {
                "@type": "Article",
                "@id": f"{page_url}#article",
                "headline": title,
                "description": description,
                "url": page_url,
                "mainEntityOfPage": page_url,
                "datePublished": published,
                "dateModified": modified,
                "inLanguage": "zh-CN",
                "image": SOCIAL_IMAGE,
                "author": {"@id": ORGANIZATION_ID},
                "publisher": {"@id": ORGANIZATION_ID},
            },
            {
                "@type": "Dataset",
                "@id": f"{page_url}#dataset",
                "name": f"{format_date_cn(trade_date)}A股涨停、炸板和跌停数据",
                "description": description,
                "url": page_url,
                "dateModified": modified,
                "temporalCoverage": trade_date,
                "inLanguage": "zh-CN",
                "isAccessibleForFree": True,
                "creator": {"@id": ORGANIZATION_ID},
                "variableMeasured": [
                    {"@type": "PropertyValue", "name": "收盘涨停股票数量", "value": values["up_count"]},
                    {"@type": "PropertyValue", "name": "炸板股票数量", "value": values["broken_count"]},
                    {"@type": "PropertyValue", "name": "跌停股票数量", "value": values["down_count"]},
                    {"@type": "PropertyValue", "name": "市场最高连板", "value": values["highest_board"]},
                ],
            },
            {
                "@type": "BreadcrumbList",
                "@id": f"{page_url}#breadcrumb",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "锋股top首页", "item": SITE_ROOT},
                    {"@type": "ListItem", "position": 2, "name": "每日涨停复盘", "item": f"{SITE_ROOT}news/"},
                    {"@type": "ListItem", "position": 3, "name": format_date_cn(trade_date), "item": page_url},
                ],
            },
        ],
    }


def render_daily_page(
    trade_date: str,
    payload: dict[str, Any],
    previous_date: str | None,
    next_date: str | None,
) -> str:
    values = summary_values(payload)
    date_cn = format_date_cn(trade_date)
    page_url = f"{SITE_ROOT}news/{trade_date}/"
    strongest_industry = values["industry_rank"][0]["name"] if values["industry_rank"] else "暂无"
    strongest_theme = values["theme_rank"][0]["name"] if values["theme_rank"] else "暂无"
    leader_text = "、".join(values["leaders"][:5]) or "暂无"
    title = (
        f"{date_cn}A股涨停复盘：{values['up_count']}股涨停、"
        f"最高{values['highest_board']}板 - 锋股top"
    )
    description = (
        f"{date_cn}A股收盘涨停{values['up_count']}只、炸板{values['broken_count']}只、"
        f"跌停{values['down_count']}只，市场最高{values['highest_board']}板；"
        f"行业涨停居前为{strongest_industry}，热门题材为{strongest_theme}。"
    )
    updated_at = text((payload.get("meta") or {}).get("updated_at"), "")
    schema = schema_graph(
        trade_date=trade_date,
        description=description,
        title=title,
        page_url=page_url,
        updated_at=updated_at,
        values=values,
    )
    navigation = []
    if previous_date:
        navigation.append(f'<a rel="prev" href="../{previous_date}/">上一交易日：{escape(previous_date)}</a>')
    if next_date:
        navigation.append(f'<a rel="next" href="../{next_date}/">下一交易日：{escape(next_date)}</a>')
    navigation_html = " ".join(navigation)
    top_stocks = ranked_limit_ups(payload)

    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{escape(title)}</title>
    <meta name="description" content="{escape(description)}" />
    <meta name="keywords" content="锋股top,{escape(date_cn)}涨停,A股涨停复盘,涨停排行,连板高度,炸板统计,行业涨停,题材涨停" />
    <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1" />
    <meta name="theme-color" content="#070b15" />
    <link rel="canonical" href="{page_url}" />
    <link rel="icon" href="../../favicon.svg" type="image/svg+xml" />
    <meta property="og:type" content="article" />
    <meta property="og:locale" content="zh_CN" />
    <meta property="og:site_name" content="锋股top" />
    <meta property="og:title" content="{escape(title)}" />
    <meta property="og:description" content="{escape(description)}" />
    <meta property="og:url" content="{page_url}" />
    <meta property="og:image" content="{SOCIAL_IMAGE}" />
    <meta property="article:published_time" content="{trade_date}T15:30:00+08:00" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{escape(title)}" />
    <meta name="twitter:description" content="{escape(description)}" />
    <meta name="twitter:image" content="{SOCIAL_IMAGE}" />
    <script type="application/ld+json">{json_ld(schema)}</script>
    <style>{page_css()}</style>
  </head>
  <body>
    <div class="wrap">
      <header class="site-head">
        <a class="brand" href="../../">锋股top</a>
        <nav aria-label="页面导航"><a href="../../">行情首页</a><a href="../">每日复盘</a></nav>
      </header>
      <main>
        <article>
          <header class="hero">
            <p class="eyebrow">A股涨停情绪数据中心</p>
            <h1>{escape(date_cn)}A股涨停复盘</h1>
            <p class="lead">{escape(description)}</p>
            <p class="meta">数据更新时间：{escape(updated_at or f"{trade_date} 15:30")}　数据源：AKShare / 东方财富公开行情</p>
          </header>
          <section class="metrics" aria-label="市场情绪统计">
            <div class="metric"><strong>{values['up_count']}</strong><span>收盘涨停</span></div>
            <div class="metric"><strong>{values['broken_count']}</strong><span>炸板统计</span></div>
            <div class="metric"><strong class="down">{values['down_count']}</strong><span>收盘跌停</span></div>
            <div class="metric"><strong>{values['highest_board']}板</strong><span>连板高度</span></div>
            <div class="metric"><strong>{values['first_board']}</strong><span>首板数量</span></div>
            <div class="metric"><strong>{values['broken_rate']:.1f}%</strong><span>炸板率</span></div>
          </section>
          <section class="panel">
            <h2>市场概况</h2>
            <p>{escape(date_cn)}共有{values['up_count']}只股票收盘涨停，{values['broken_count']}只股票盘中涨停后炸板，{values['down_count']}只股票收盘跌停。市场最高连板为{values['highest_board']}板，最高板股票包括{escape(leader_text)}。</p>
          </section>
          <section class="panel">
            <h2>今日涨停股票排行</h2>
            {render_stock_table(top_stocks)}
          </section>
          <div class="grid">
            <section class="panel">
              <h2>行业涨停排行</h2>
              {render_rank_list(values['industry_rank'], "当日暂无行业排行数据。")}
            </section>
            <section class="panel">
              <h2>题材涨停排行</h2>
              {render_rank_list(values['theme_rank'], "当日暂无题材排行数据。")}
              <p class="meta">题材为系统识别，仅供参考。</p>
            </section>
          </div>
          <section class="panel">
            <h2>数据说明</h2>
            <p>本页为{escape(date_cn)}收盘数据的静态归档。涨停、炸板、跌停分别使用各自行情池统计；页面不构成任何投资建议，实际交易请以交易所和券商行情为准。</p>
            <p>{navigation_html}</p>
          </section>
        </article>
      </main>
      <footer>锋股top · A股涨停、连板、炸板与行业题材数据查询</footer>
    </div>
  </body>
</html>
"""


def render_archive(payloads: dict[str, dict[str, Any]]) -> str:
    cards = []
    dates = list(payloads)
    for trade_date in reversed(dates):
        values = summary_values(payloads[trade_date])
        cards.append(
            f'<li><a href="./{trade_date}/"><strong>{escape(format_date_cn(trade_date))}A股涨停复盘</strong>'
            f"<span>涨停{values['up_count']}只 · 炸板{values['broken_count']}只 · "
            f"跌停{values['down_count']}只 · 最高{values['highest_board']}板</span></a></li>"
        )
    latest_date = dates[-1]
    description = "锋股top每日A股涨停复盘归档，提供涨停数量、炸板统计、连板高度、行业排行和题材排行。"
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": ORGANIZATION_ID,
                "name": "锋股top",
                "url": SITE_ROOT,
                "logo": f"{SITE_ROOT}favicon.svg",
            },
            {
                "@type": "WebSite",
                "@id": WEBSITE_ID,
                "url": SITE_ROOT,
                "name": "锋股top",
                "publisher": {"@id": ORGANIZATION_ID},
            },
            {
                "@type": "CollectionPage",
                "@id": f"{SITE_ROOT}news/#collection",
                "url": f"{SITE_ROOT}news/",
                "name": "A股每日涨停复盘 - 锋股top",
                "description": description,
                "inLanguage": "zh-CN",
                "isPartOf": {"@id": WEBSITE_ID},
            },
            {
                "@type": "BreadcrumbList",
                "@id": f"{SITE_ROOT}news/#breadcrumb",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "锋股top首页", "item": SITE_ROOT},
                    {"@type": "ListItem", "position": 2, "name": "每日涨停复盘", "item": f"{SITE_ROOT}news/"},
                ],
            },
        ],
    }
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>A股每日涨停复盘归档-涨停排行与连板高度-锋股top</title>
    <meta name="description" content="{description}" />
    <meta name="keywords" content="锋股top,A股每日复盘,今日涨停,涨停排行,连板高度,炸板统计,行业排行,题材排行" />
    <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1" />
    <meta name="theme-color" content="#070b15" />
    <link rel="canonical" href="{SITE_ROOT}news/" />
    <link rel="icon" href="../favicon.svg" type="image/svg+xml" />
    <meta property="og:type" content="website" />
    <meta property="og:locale" content="zh_CN" />
    <meta property="og:site_name" content="锋股top" />
    <meta property="og:title" content="A股每日涨停复盘归档 - 锋股top" />
    <meta property="og:description" content="{description}" />
    <meta property="og:url" content="{SITE_ROOT}news/" />
    <meta property="og:image" content="{SOCIAL_IMAGE}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="A股每日涨停复盘归档 - 锋股top" />
    <meta name="twitter:description" content="{description}" />
    <meta name="twitter:image" content="{SOCIAL_IMAGE}" />
    <script type="application/ld+json">{json_ld(schema)}</script>
    <style>{page_css()}
      .archive{{list-style:none;margin:18px 0;padding:0}}
      .archive a{{background:#101a2d;border:1px solid rgba(126,151,190,.18);display:flex;gap:10px;justify-content:space-between;margin:10px 0;padding:16px;text-decoration:none}}
      .archive span{{color:#9eacc2}}
      @media(max-width:700px){{.archive a{{align-items:flex-start;flex-direction:column}}}}
    </style>
  </head>
  <body>
    <div class="wrap">
      <header class="site-head"><a class="brand" href="../">锋股top</a><nav><a href="../">行情首页</a></nav></header>
      <main>
        <header class="hero">
          <p class="eyebrow">静态数据归档</p>
          <h1>A股每日涨停复盘</h1>
          <p class="lead">{description}</p>
          <p class="meta">最新交易日：{escape(latest_date)}</p>
        </header>
        <ol class="archive">{''.join(cards)}</ol>
      </main>
      <footer>锋股top · 每个交易日收盘后更新</footer>
    </div>
  </body>
</html>
"""


def render_home_fallback(trade_date: str, payload: dict[str, Any]) -> str:
    values = summary_values(payload)
    top_stocks = ranked_limit_ups(payload, limit=10)
    stock_items = "".join(
        f"<li><strong>{escape(text(stock.get('name')))}</strong>（{escape(text(stock.get('code'))) }）"
        f"{integer(stock.get('consecutive_days'), 1)}板，{escape(text(stock.get('industry')))}</li>"
        for stock in top_stocks
    )
    return f"""{FALLBACK_START}
    <noscript>
      <style>#boot-status{{display:none!important}}</style>
      <main class="seo-fallback">
        <header>
          <p class="seo-eyebrow">A股涨停情绪数据中心</p>
          <h1>锋股top - {escape(format_date_cn(trade_date))}A股涨停股票排行榜</h1>
          <p>收盘涨停{values['up_count']}只，炸板{values['broken_count']}只，跌停{values['down_count']}只，连板高度{values['highest_board']}板。</p>
          <p><a href="./news/{trade_date}/">查看{escape(format_date_cn(trade_date))}完整涨停复盘</a>　<a href="./news/">浏览每日复盘归档</a></p>
        </header>
        <section class="seo-fallback-grid" aria-label="收盘统计">
          <article><strong>{values['up_count']}</strong><span>今日涨停股票</span></article>
          <article><strong>{values['broken_count']}</strong><span>炸板统计</span></article>
          <article><strong>{values['down_count']}</strong><span>收盘跌停</span></article>
          <article><strong>{values['highest_board']}板</strong><span>连板高度</span></article>
        </section>
        <section><h2>今日涨停股票排行</h2><ol>{stock_items}</ol></section>
        <section class="seo-fallback-columns">
          <div><h2>行业涨停排行</h2>{render_rank_list(values['industry_rank'][:5], "暂无行业排行数据。")}</div>
          <div><h2>题材涨停排行</h2>{render_rank_list(values['theme_rank'][:5], "暂无题材排行数据。")}</div>
        </section>
        <p class="seo-disclaimer">数据来自公开行情接口，仅供信息参考，不构成投资建议。</p>
      </main>
    </noscript>
    {FALLBACK_END}"""


def update_home_fallback(trade_date: str, payload: dict[str, Any]) -> None:
    source = INDEX_PATH.read_text(encoding="utf-8")
    replacement = render_home_fallback(trade_date, payload)
    pattern = re.compile(re.escape(FALLBACK_START) + r".*?" + re.escape(FALLBACK_END), re.S)
    if not pattern.search(source):
        raise RuntimeError("index.html is missing SEO fallback markers")
    updated = pattern.sub(lambda _: replacement, source, count=1)
    if updated != source:
        INDEX_PATH.write_text(updated, encoding="utf-8", newline="\n")


def main() -> None:
    payloads = collect_payloads()
    if not payloads:
        raise SystemExit("no publishable market data found")

    NEWS_DIR.mkdir(exist_ok=True)
    dates = list(payloads)
    for index, trade_date in enumerate(dates):
        target_dir = NEWS_DIR / trade_date
        target_dir.mkdir(exist_ok=True)
        page = render_daily_page(
            trade_date,
            payloads[trade_date],
            dates[index - 1] if index > 0 else None,
            dates[index + 1] if index + 1 < len(dates) else None,
        )
        (target_dir / "index.html").write_text(page, encoding="utf-8", newline="\n")

    (NEWS_DIR / "index.html").write_text(render_archive(payloads), encoding="utf-8", newline="\n")
    latest_date = dates[-1]
    update_home_fallback(latest_date, payloads[latest_date])
    print(f"SEO pages generated: {len(dates)} daily pages, latest={latest_date}")


if __name__ == "__main__":
    main()
