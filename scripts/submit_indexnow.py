from __future__ import annotations

import argparse
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = "https://xiaoma-feng.github.io/fenggu-top/"
HOST = "xiaoma-feng.github.io"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
INDEXNOW_KEY = "8b00f36f35c44d7594da3a76b00677d4"
KEY_LOCATION = f"{SITE_ROOT}{INDEXNOW_KEY}.txt"
SITEMAP_NAMESPACE = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
DAILY_PAGE_RE = re.compile(r"/(?:limit-up|review)/\d{4}-\d{2}-\d{2}/$")


def read_sitemap(source: str | None) -> bytes:
    if source:
        request = urllib.request.Request(
            source,
            headers={"User-Agent": "fenggu-top-indexnow/1.0", "Cache-Control": "no-cache"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    return (ROOT / "sitemap.xml").read_bytes()


def sitemap_urls(content: bytes) -> list[str]:
    root = ET.fromstring(content)
    urls = [
        str(node.text or "").strip()
        for node in root.findall("sm:url/sm:loc", SITEMAP_NAMESPACE)
        if str(node.text or "").strip().startswith(SITE_ROOT)
    ]
    return list(dict.fromkeys(urls))


def changed_urls(urls: list[str]) -> list[str]:
    daily = sorted(url for url in urls if DAILY_PAGE_RE.search(url))
    selected = [
        SITE_ROOT,
        f"{SITE_ROOT}limit-up/",
        f"{SITE_ROOT}review/",
        f"{SITE_ROOT}stock/",
        f"{SITE_ROOT}industry/",
        f"{SITE_ROOT}theme/",
    ]
    if daily:
        latest_date = max(url.rstrip("/").rsplit("/", 1)[-1] for url in daily)
        selected.extend(url for url in daily if f"/{latest_date}/" in url)
    return [url for url in selected if url in urls]


def submit(urls: list[str]) -> int:
    payload = json.dumps(
        {
            "host": HOST,
            "key": INDEXNOW_KEY,
            "keyLocation": KEY_LOCATION,
            "urlList": urls,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        INDEXNOW_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "fenggu-top-indexnow/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit changed fenggu-top URLs to IndexNow.")
    parser.add_argument("--sitemap-url", help="Read the deployed sitemap instead of the local file.")
    parser.add_argument("--all", action="store_true", help="Submit every URL in the sitemap.")
    args = parser.parse_args()

    urls = sitemap_urls(read_sitemap(args.sitemap_url))
    targets = urls if args.all else changed_urls(urls)
    if not targets:
        raise SystemExit("no IndexNow URLs found")
    status = submit(targets)
    print(f"IndexNow accepted {len(targets)} URLs with HTTP {status}")


if __name__ == "__main__":
    main()
