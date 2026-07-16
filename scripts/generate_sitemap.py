from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LATEST_DATA = ROOT / "data" / "latest.json"
NEWS_DIR = ROOT / "news"
SITEMAP_PATH = ROOT / "sitemap.xml"
SITE_URL = "https://xiaoma-feng.github.io/fenggu-top/"


def latest_trade_date() -> str:
    try:
        payload = json.loads(LATEST_DATA.read_text(encoding="utf-8"))
        value = str(payload.get("meta", {}).get("trade_date", "")).strip()
        date.fromisoformat(value)
        return value
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
        return date.today().isoformat()


def daily_pages() -> list[tuple[str, str]]:
    pages: list[tuple[str, str]] = []
    if not NEWS_DIR.exists():
        return pages
    for path in sorted(NEWS_DIR.glob("????-??-??/index.html")):
        try:
            date.fromisoformat(path.parent.name)
        except ValueError:
            continue
        pages.append((f"{SITE_URL}news/{path.parent.name}/", path.parent.name))
    return pages


def url_entry(location: str, last_modified: str) -> str:
    return (
        "  <url>\n"
        f"    <loc>{escape(location)}</loc>\n"
        f"    <lastmod>{escape(last_modified)}</lastmod>\n"
        "  </url>"
    )


def build_sitemap(last_modified: str) -> str:
    entries = [
        url_entry(SITE_URL, last_modified),
        url_entry(f"{SITE_URL}news/", last_modified),
    ]
    entries.extend(url_entry(location, trade_date) for location, trade_date in daily_pages())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(entries)}
</urlset>
"""


def main() -> None:
    content = build_sitemap(latest_trade_date())
    if not SITEMAP_PATH.exists() or SITEMAP_PATH.read_text(encoding="utf-8") != content:
        SITEMAP_PATH.write_text(content, encoding="utf-8", newline="\n")
    print(f"sitemap generated: {SITEMAP_PATH}")


if __name__ == "__main__":
    main()
