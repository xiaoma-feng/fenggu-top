from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "seo-manifest.json"
SITEMAP_PATH = ROOT / "sitemap.xml"
SITE_PREFIX = "/fenggu-top/"
GENERATED_ROOTS = ("stock", "industry", "theme", "limit-up", "review")
REQUIRED_STOCKS = ("000001", "600519", "300750")


def pages() -> list[Path]:
    result: list[Path] = []
    for root_name in GENERATED_ROOTS:
        result.extend((ROOT / root_name).rglob("index.html"))
    return sorted(result)


def local_target(href: str) -> Path | None:
    parsed = urlparse(unescape(href))
    if parsed.netloc or not parsed.path.startswith(SITE_PREFIX):
        return None
    relative = unquote(parsed.path[len(SITE_PREFIX) :]).strip("/")
    if not relative:
        return ROOT / "index.html"
    candidate = ROOT / relative
    if candidate.suffix:
        return candidate
    return candidate / "index.html"


def fail(message: str) -> None:
    raise SystemExit(f"SEO validation failed: {message}")


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    all_pages = pages()
    if len(all_pages) != int(manifest.get("total_pages", -1)):
        fail(f"manifest expects {manifest.get('total_pages')} pages, found {len(all_pages)}")
    if len(all_pages) < 5_000:
        fail(f"only {len(all_pages)} static pages were generated")

    broken_links: list[tuple[Path, str]] = []
    missing_metadata: list[Path] = []
    for page in all_pages:
        source = page.read_text(encoding="utf-8")
        required = (
            "<title>",
            '<meta name="description"',
            '<meta name="robots" content="index,follow',
            '<link rel="canonical"',
            "<h1>",
            "BreadcrumbList",
            '<script type="application/ld+json">',
        )
        if any(marker not in source for marker in required) or "noindex" in source.lower():
            missing_metadata.append(page)
        for href in re.findall(r'<a\s+[^>]*href="([^"]+)"', source):
            target = local_target(href)
            if target is not None and not target.exists():
                broken_links.append((page, href))
                if len(broken_links) >= 20:
                    break
        if len(broken_links) >= 20:
            break

    if missing_metadata:
        fail(f"metadata or indexability problem in {missing_metadata[0]}")
    if broken_links:
        page, href = broken_links[0]
        fail(f"broken internal link in {page}: {href}")

    for code in REQUIRED_STOCKS:
        stock_page = ROOT / "stock" / code / "index.html"
        if not stock_page.exists():
            fail(f"required stock page is missing: {code}")
        source = stock_page.read_text(encoding="utf-8")
        for text in (
            "今日涨停", "今日跌停", "今日炸板", "历史涨停次数", "历史炸板次数", "历史最高连板",
            "最近涨停日期", "最近炸板日期", "最近成交额", "K线图", "相关推荐", "上一篇", "下一篇",
        ):
            if text not in source:
                fail(f"{code} page is missing section: {text}")

    review_pages = sorted((ROOT / "review").glob("????-??-??/index.html"))
    if not review_pages:
        fail("no daily review pages were generated")
    for page in review_pages:
        source = page.read_text(encoding="utf-8")
        match = re.search(r'<section class="section article-body">(.*?)</section>', source, re.S)
        if not match:
            fail(f"review body is missing in {page}")
        plain = re.sub(r"<[^>]+>", "", match.group(1))
        if len(plain) < 1_200:
            fail(f"review content is too short ({len(plain)} chars): {page}")

    tree = ET.parse(SITEMAP_PATH)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    sitemap_urls = tree.findall("sm:url", namespace)
    expected_urls = len(all_pages) + 1
    if len(sitemap_urls) != expected_urls:
        fail(f"sitemap has {len(sitemap_urls)} URLs, expected {expected_urls}")
    if int(manifest.get("sitemap_urls", -1)) != expected_urls:
        fail("manifest sitemap count is stale")

    print(
        f"SEO validation passed: {len(all_pages)} pages, {len(sitemap_urls)} sitemap URLs, "
        f"{manifest.get('internal_links')} internal links, {len(review_pages)} long-form reviews"
    )


if __name__ == "__main__":
    main()
