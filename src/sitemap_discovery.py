"""Discover every crawlable URL for a domain via its XML sitemap(s).

This is the tool's "page keşfi" step: rather than someone maintaining a
manual list of pages, it walks the site's own sitemap (following nested
sitemap indexes) and falls back to the ``Sitemap:`` lines in robots.txt
if a sitemap isn't where we expect it.

Some sites block plain HTTP clients like ``requests`` outright (their
bot protection sees the network/TLS fingerprint, not just the
User-Agent header, and rejects it with a 403), even when the plain
fetch honestly announces itself with a browser-like User-Agent. When
that happens, and a ``browser_fetch`` callable is supplied (see
``RenderedFetcher.fetch_text`` in fetcher.py), this module retries the
same URL through the real headless browser before giving up.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import requests
from lxml import etree

logger = logging.getLogger(__name__)

NAMESPACES = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

BrowserFetch = Callable[[str], Optional[str]]


def _fetch_xml(
    url: str,
    timeout: int,
    user_agent: str,
    browser_fetch: Optional[BrowserFetch] = None,
) -> Optional["etree._Element"]:
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": user_agent})
        resp.raise_for_status()
        return etree.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001 - we want to keep scanning other sitemaps
        logger.warning("Plain fetch of sitemap %s failed (%s).", url, exc)

    if browser_fetch is None:
        return None

    logger.info("Retrying %s through the headless browser.", url)
    text = browser_fetch(url)
    if not text:
        return None
    try:
        return etree.fromstring(text.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Browser fallback fetched %s but it did not parse as XML: %s", url, exc)
        return None


def _sitemap_urls_from_robots(
    domain: str,
    timeout: int,
    user_agent: str,
    browser_fetch: Optional[BrowserFetch] = None,
) -> list[str]:
    """Fallback / supplement: read ``Sitemap:`` directives out of robots.txt."""
    robots_url = urljoin(domain, "/robots.txt")
    text: Optional[str] = None
    try:
        resp = requests.get(robots_url, timeout=timeout, headers={"User-Agent": user_agent})
        if resp.ok:
            text = resp.text
        else:
            logger.warning("Plain fetch of %s returned HTTP %d.", robots_url, resp.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Plain fetch of %s failed (%s).", robots_url, exc)

    if text is None and browser_fetch is not None:
        logger.info("Retrying %s through the headless browser.", robots_url)
        text = browser_fetch(robots_url)

    if not text:
        return []
    return [
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.lower().startswith("sitemap:")
    ]


def discover_urls(
    domain: str,
    seed_sitemaps: list[str],
    timeout: int = 20,
    user_agent: str = "AIOAuditBot/1.0",
    exclude_patterns: list[str] | None = None,
    browser_fetch: Optional[BrowserFetch] = None,
) -> list[str]:
    """Walk one or more sitemap entry points (including nested sitemap
    indexes) and return every ``<loc>`` page URL found, deduplicated and
    filtered to the target domain.

    ``browser_fetch``, when given, is tried automatically whenever the
    plain HTTP fetch of a sitemap or robots.txt is blocked.
    """
    exclude_patterns = exclude_patterns or []
    to_visit: list[str] = list(seed_sitemaps) or [urljoin(domain, "/sitemap.xml")]
    to_visit += _sitemap_urls_from_robots(domain, timeout, user_agent, browser_fetch)

    seen_sitemaps: set[str] = set()
    page_urls: set[str] = set()
    domain_host = urlparse(domain).netloc

    while to_visit:
        sm_url = to_visit.pop()
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)

        root = _fetch_xml(sm_url, timeout, user_agent, browser_fetch)
        if root is None:
            continue

        tag = etree.QName(root).localname

        if tag == "sitemapindex":
            for loc in root.findall("sm:sitemap/sm:loc", NAMESPACES):
                if loc.text:
                    to_visit.append(loc.text.strip())

        elif tag == "urlset":
            for loc in root.findall("sm:url/sm:loc", NAMESPACES):
                if not loc.text:
                    continue
                url = loc.text.strip()
                if urlparse(url).netloc != domain_host:
                    continue
                if any(url.lower().endswith(ext) for ext in exclude_patterns):
                    continue
                page_urls.add(url)

    logger.info(
        "Discovered %d page URL(s) across %d sitemap file(s).",
        len(page_urls),
        len(seen_sitemaps),
    )
    return sorted(page_urls)
