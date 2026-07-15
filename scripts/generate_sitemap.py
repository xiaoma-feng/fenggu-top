from __future__ import annotations

import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LATEST_DATA = ROOT / "data" / "latest.json"
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


def build_sitemap(last_modified: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{SITE_URL}</loc>
    <lastmod>{last_modified}</lastmod>
  </url>
</urlset>
"""


def main() -> None:
    content = build_sitemap(latest_trade_date())
    if not SITEMAP_PATH.exists() or SITEMAP_PATH.read_text(encoding="utf-8") != content:
        SITEMAP_PATH.write_text(content, encoding="utf-8", newline="\n")
    print(f"sitemap generated: {SITEMAP_PATH}")


if __name__ == "__main__":
    main()
