from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LATEST_PATH = DATA_DIR / "latest.json"
MANIFEST_PATH = DATA_DIR / "seo-manifest.json"
SITEMAP_PATH = ROOT / "sitemap.xml"
SITE_ROOT = "https://xiaoma-feng.github.io/fenggu-top/"
PAGE_ROOTS = ("stock", "industry", "theme", "limit-up", "review")
SITEMAP_LIMIT = 50_000


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def latest_trade_date() -> str:
    payload = read_json(LATEST_PATH)
    value = str((payload.get("meta") or {}).get("trade_date") or "")
    try:
        date.fromisoformat(value)
    except ValueError:
        return date.today().isoformat()
    return value


def page_urls() -> list[tuple[str, str]]:
    latest = latest_trade_date()
    pages: list[tuple[str, str]] = [(SITE_ROOT, latest)]
    for root_name in PAGE_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for page in sorted(root.rglob("index.html")):
            relative = page.parent.relative_to(ROOT).as_posix().strip("/")
            encoded = quote(relative, safe="/-._~")
            last_modified = latest
            if root_name in {"limit-up", "review"}:
                candidate = page.parent.name
                try:
                    date.fromisoformat(candidate)
                except ValueError:
                    pass
                else:
                    last_modified = candidate
            pages.append((f"{SITE_ROOT}{encoded}/", last_modified))
    unique: dict[str, str] = {}
    for location, last_modified in pages:
        unique[location] = last_modified
    return sorted(unique.items(), key=lambda item: (item[0] != SITE_ROOT, item[0]))


def build_sitemap() -> tuple[str, int]:
    pages = page_urls()
    if len(pages) > SITEMAP_LIMIT:
        raise RuntimeError(f"sitemap has {len(pages)} URLs; split it before exceeding {SITEMAP_LIMIT}")
    entries = "\n".join(
        f"  <url><loc>{escape(location)}</loc><lastmod>{last_modified}</lastmod></url>"
        for location, last_modified in pages
    )
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )
    return content, len(pages)


def update_manifest(url_count: int) -> None:
    manifest = read_json(MANIFEST_PATH)
    if not manifest:
        return
    manifest["sitemap_urls"] = url_count
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )


def main() -> None:
    content, count = build_sitemap()
    SITEMAP_PATH.write_text(content, encoding="utf-8", newline="\n")
    update_manifest(count)
    print(f"sitemap generated: {count} URLs -> {SITEMAP_PATH}")


if __name__ == "__main__":
    main()
