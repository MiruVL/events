"""Crawl live-house schedule pages using Crawl4AI and return clean markdown, HTML, or JSON."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
    JsonCssExtractionStrategy,
)

# Directory to cache raw crawl results for debugging/re-processing
CRAWL_CACHE_DIR = Path("crawl_cache")

DEFAULT_CONTENT_TYPE = "fit_markdown"

_CONTENT_EXTRACTORS = {
    "fit_markdown": lambda r: r.markdown.fit_markdown or r.markdown.raw_markdown,
    "raw_markdown": lambda r: r.markdown.raw_markdown,
    "markdown_with_citations": lambda r: r.markdown.markdown_with_citations,
    "html": lambda r: r.cleaned_html or r.html,
}


def _safe_cache_suffix(suffix: str) -> str:
    """Make a cache key suffix safe for use in filenames."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in suffix)[:30]


async def crawl_page(
    url: str,
    *,
    use_cache: bool = True,
    cache_key_suffix: str | None = None,
    css_selector: str | None = None,
    json_css_schema: dict[str, Any] | None = None,
    content_type: str = DEFAULT_CONTENT_TYPE,
) -> str:
    """
    Crawl a single URL and return its content as markdown, HTML, or JSON.

    When ``json_css_schema`` is provided the page is crawled using Crawl4AI's
    ``JsonCssExtractionStrategy`` and the extracted JSON string is returned.
    Otherwise the ``content_type`` determines which format is returned.

    Args:
        url: The page URL to crawl.
        use_cache: If True, check local file cache before crawling.
        cache_key_suffix: Optional suffix for cache file (e.g. "2026-02").
        css_selector: Optional CSS selector to scope page content.
        json_css_schema: Optional schema dict for JsonCssExtractionStrategy.
            When set, the return value is a JSON string (overrides content_type).
        content_type: Output format — one of "fit_markdown", "raw_markdown",
            "markdown_with_citations", or "html".

    Returns:
        Page content in the requested format.
    """
    CRAWL_CACHE_DIR.mkdir(exist_ok=True)
    base_name = _url_to_filename(url)
    if cache_key_suffix:
        base_name = f"{base_name}_{_safe_cache_suffix(cache_key_suffix)}"

    if json_css_schema:
        ext = ".json"
    elif content_type == "html":
        ext = ".html"
    else:
        ext = ".md"

    # Include non-default content_type in filename to avoid stale cache
    if not json_css_schema and content_type != DEFAULT_CONTENT_TYPE:
        type_tag = _safe_cache_suffix(content_type)
        cache_file = CRAWL_CACHE_DIR / f"{base_name}_{type_tag}{ext}"
    else:
        cache_file = CRAWL_CACHE_DIR / f"{base_name}{ext}"

    if use_cache and cache_file.exists():
        print(f"  Using cached crawl: {cache_file}")
        return cache_file.read_text(encoding="utf-8")

    print(f"  Crawling: {url}")
    if css_selector:
        print(f"  CSS selector: {css_selector}")
    if json_css_schema:
        print(f"  Using JsonCssExtractionStrategy")
    elif content_type != DEFAULT_CONTENT_TYPE:
        print(f"  Content type: {content_type}")

    browser_config = BrowserConfig(
        headless=True,
        text_mode=False,
    )

    run_config_kw: dict[str, Any] = {
        "cache_mode": CacheMode.BYPASS,
    }
    if json_css_schema:
        run_config_kw["extraction_strategy"] = JsonCssExtractionStrategy(
            schema=json_css_schema
        )
    if css_selector:
        run_config_kw["css_selector"] = css_selector

    run_config = CrawlerRunConfig(**run_config_kw)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

    if not result.success:
        raise RuntimeError(f"Crawl failed for {url}: {result.error_message}")

    if json_css_schema:
        content = result.extracted_content or "[]"
    else:
        extractor = _CONTENT_EXTRACTORS.get(content_type)
        if extractor is None:
            raise ValueError(f"Unknown content_type: {content_type}")
        content = extractor(result)

    cache_file.write_text(content, encoding="utf-8")
    print(f"  Saved crawl cache: {cache_file}")

    return content


async def crawl_schedule(
    venue_name: str,
    schedule_url: str,
    *,
    use_cache: bool = True,
    cache_key_suffix: str | None = None,
    css_selector: str | None = None,
    json_css_schema: dict[str, Any] | None = None,
    content_type: str = DEFAULT_CONTENT_TYPE,
) -> str:
    """Crawl a venue's schedule page and return content in the requested format."""
    print(f"\n[{venue_name}] Crawling schedule...")
    return await crawl_page(
        schedule_url,
        use_cache=use_cache,
        cache_key_suffix=cache_key_suffix,
        css_selector=css_selector,
        json_css_schema=json_css_schema,
        content_type=content_type,
    )


async def crawl_detail_pages(
    venue_name: str,
    detail_urls: list[str],
    *,
    use_cache: bool = True,
    css_selector: str | None = None,
    json_css_schema: dict[str, Any] | None = None,
    content_type: str = DEFAULT_CONTENT_TYPE,
) -> list[str]:
    """Crawl multiple event detail pages and return their content."""
    print(f"\n[{venue_name}] Crawling {len(detail_urls)} detail pages...")
    results = []
    for url in detail_urls:
        content = await crawl_page(
            url,
            use_cache=use_cache,
            css_selector=css_selector,
            json_css_schema=json_css_schema,
            content_type=content_type,
        )
        results.append(content)
    return results


def _url_to_filename(url: str) -> str:
    """Convert a URL to a safe filename."""
    return (
        url.replace("https://", "")
        .replace("http://", "")
        .replace("/", "_")
        .replace("?", "_")
        .replace("&", "_")[:120]
    )


async def main() -> None:
    """CLI: crawl a URL and print the markdown."""
    if len(sys.argv) < 2:
        print("Usage: uv run -m app.scraper <url>")
        print('Example: uv run -m app.scraper "https://example.com/schedule"')
        sys.exit(1)

    url = sys.argv[1]
    no_cache = "--no-cache" in sys.argv

    content = await crawl_page(url, use_cache=not no_cache)
    print("\n" + "=" * 60)
    print("CRAWL RESULT")
    print("=" * 60)
    print(content[:3000])
    if len(content) > 3000:
        print(f"\n... ({len(content)} chars total, truncated)")


if __name__ == "__main__":
    asyncio.run(main())
