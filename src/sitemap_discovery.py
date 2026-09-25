"""Discover every crawlable URL for a domain via its XML sitemap(s).

This is the tool's "page keşfi" step: rather than someone maintaining a
manual list of pages, it walks the site's own sitemap (following nested
sitemap indexes) and falls back to the ``Sitemap:`` lines in robots.txt
if a sitemap isn't where we expect it.
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from lxml import etree

logger = logging.getLogger(__name__)

NAMESPACES = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _fetch_xml(url: str, timeout: int, user_agent: str) -> Optional["etree._Element"]:
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": user_agent})
        resp.raise_for_status()
        return etree.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001 - we want to keep scanning other sitemaps
        logger.warning("Could not fetch or parse sitemap %s: %s", url, exc)
        return None


def _sitemap_urls_from_robots(domain: str, timeout: int, user_agent: str) -> list[str]:
    """Fallback / supplement: read ``Sitemap:`` directives out of robots.txt."""
    robots_url = urljoin(domain, "/robots.txt")
    found: list[str] = []
    try:
        resp = requests.get(robots_url, timeout=timeout, headers={"User-Agent": user_agent})
        if resp.ok:
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    found.append(line.split(":", 1)[1].strip())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read robots.txt for sitemap discovery: %s", exc)
    return found


def discover_urls(
    domain: str,
    seed_sitemaps: list[str],
    timeout: int = 20,
    user_agent: str = "AIOAuditBot/1.0",
    exclude_patterns: list[str] | None = None,
) -> list[str]:
    """Walk one or more sitemap entry points (including nested sitemap
    indexes) and return every ``<loc>`` page URL found, deduplicated and
    filtered to the target domain.
    """
    exclude_patterns = exclude_patterns or []
    to_visit: list[str] = list(seed_sitemaps) or [urljoin(domain, "/sitemap.xml")]
    to_visit += _sitemap_urls_from_robots(domain, timeout, user_agent)

    seen_sitemaps: set[str] = set()
    page_urls: set[str] = set()
    domain_host = urlparse(domain).netloc

    while to_visit:
        sm_url = to_visit.pop()
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)

        root = _fetch_xml(sm_url, timeout, user_agent)
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
