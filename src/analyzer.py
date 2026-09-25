"""Per-page technical AIO/AEO analysis.

This module records the CURRENT STATE of a page against the on-page
checklist used by the syngenta-seo-aeo-optimizer skill (meta title,
meta description, H1, H2 phrasing, FAQ schema, image alt text,
freshness signal, and the raw-vs-rendered content gap). It makes no
recommendations: every field here is an observed fact about the page
as fetched, not a suggested fix.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

QUESTION_STARTERS = (
    "how", "what", "why", "when", "where", "which", "who", "can", "does",
    "do", "is", "are", "will", "should",
    # light French coverage, since several Syngenta Canada pages are French
    "comment", "pourquoi", "quel", "quelle", "quels", "quelles", "quand", "o\u00f9",
)


def classify_page_type(url: str) -> str:
    """Best-effort page-type guess from the URL path, used only to group
    results in the dashboard (e.g. "how are product pages doing"). This
    is a heuristic, not a guarantee.
    """
    path = urlparse(url).path.lower().rstrip("/")
    if path == "":
        return "homepage"
    if "/productsdetail/" in path or "/products/" in path:
        return "product"
    if "/news" in path or "/blog" in path or "in-the-news" in path:
        return "article"
    if "/agronomy" in path or "/pests" in path:
        return "service"
    return "other"


def _text_word_count(soup: BeautifulSoup) -> int:
    text = soup.get_text(separator=" ", strip=True)
    return len(text.split())


def _is_question(text: str) -> bool:
    t = text.strip().lower()
    if not t:
        return False
    if t.endswith("?"):
        return True
    return t.startswith(QUESTION_STARTERS)


def _extract_schema_types(soup: BeautifulSoup) -> list[str]:
    """Collect every @type found in this page's JSON-LD blocks, including
    types nested inside an @graph array.
    """
    found: list[str] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            nodes = graph if isinstance(graph, list) else [item]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                t = node.get("@type")
                if isinstance(t, list):
                    found.extend(str(x) for x in t)
                elif isinstance(t, str):
                    found.append(t)
    return sorted(set(found))


def _alt_text_quality(soup: BeautifulSoup) -> dict:
    imgs = soup.find_all("img")
    total = len(imgs)
    empty_alt = 0
    filename_like_alt = 0
    missing_src = 0
    for img in imgs:
        alt = (img.get("alt") or "").strip()
        src = (img.get("src") or "").strip()
        if not alt:
            empty_alt += 1
        elif re.search(r"\.(png|jpe?g|webp|gif|svg)$", alt, re.IGNORECASE) or " " not in alt:
            filename_like_alt += 1
        if not src or src in ("<>", "#") or src.startswith("javascript:"):
            missing_src += 1
    return {
        "total_images": total,
        "empty_alt": empty_alt,
        "filename_like_alt": filename_like_alt,
        "missing_or_broken_src": missing_src,
    }


def _freshness_signal_present(soup: BeautifulSoup) -> bool:
    text = soup.get_text(separator=" ", strip=True).lower()
    return bool(re.search(r"(last updated|updated on|mis \u00e0 jour|derni\u00e8re mise \u00e0 jour)", text))


@dataclass
class PageAnalysis:
    url: str
    page_type: str
    fetched_raw_ok: bool
    fetched_rendered_ok: bool

    meta_title: Optional[str] = None
    meta_title_len: int = 0
    meta_description: Optional[str] = None
    meta_description_len: int = 0

    h1_count: int = 0
    h1_text: Optional[str] = None

    h2_texts: list = field(default_factory=list)
    h2_question_ratio: float = 0.0

    schema_types_found: list = field(default_factory=list)
    has_faqpage_schema: bool = False

    alt_text: dict = field(default_factory=dict)
    freshness_signal_present: bool = False

    raw_word_count: int = 0
    rendered_word_count: int = 0
    js_content_gap_ratio: float = 0.0
    js_content_gap_flag: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def analyze_page(
    url: str,
    raw_html: Optional[str],
    rendered_html: Optional[str],
    js_gap_word_threshold_ratio: float,
    js_gap_min_word_diff: int,
) -> PageAnalysis:
    analysis = PageAnalysis(
        url=url,
        page_type=classify_page_type(url),
        fetched_raw_ok=raw_html is not None,
        fetched_rendered_ok=rendered_html is not None,
    )

    raw_soup = BeautifulSoup(raw_html, "lxml") if raw_html else None
    rendered_soup = BeautifulSoup(rendered_html, "lxml") if rendered_html else None

    # The rendered DOM is a superset of what a browser shows, so it drives
    # every structural/content check. Raw HTML is only used to measure the
    # JS-dependency gap itself.
    primary = rendered_soup or raw_soup
    if primary is None:
        return analysis

    title_tag = primary.find("title")
    analysis.meta_title = title_tag.get_text(strip=True) if title_tag else None
    analysis.meta_title_len = len(analysis.meta_title) if analysis.meta_title else 0

    desc_tag = primary.find("meta", attrs={"name": "description"})
    raw_desc = desc_tag.get("content", "").strip() if desc_tag else ""
    analysis.meta_description = raw_desc or None
    analysis.meta_description_len = len(raw_desc)

    h1s = primary.find_all("h1")
    analysis.h1_count = len(h1s)
    analysis.h1_text = h1s[0].get_text(strip=True) if h1s else None

    h2_texts = [h.get_text(strip=True) for h in primary.find_all("h2")]
    h2_texts = [h for h in h2_texts if h]
    analysis.h2_texts = h2_texts
    if h2_texts:
        analysis.h2_question_ratio = round(
            sum(1 for h in h2_texts if _is_question(h)) / len(h2_texts), 3
        )

    schema_types = _extract_schema_types(primary)
    analysis.schema_types_found = schema_types
    analysis.has_faqpage_schema = "FAQPage" in schema_types

    analysis.alt_text = _alt_text_quality(primary)
    analysis.freshness_signal_present = _freshness_signal_present(primary)

    if raw_soup is not None:
        analysis.raw_word_count = _text_word_count(raw_soup)
    if rendered_soup is not None:
        analysis.rendered_word_count = _text_word_count(rendered_soup)

    if analysis.raw_word_count > 0:
        analysis.js_content_gap_ratio = round(
            analysis.rendered_word_count / analysis.raw_word_count, 2
        )
    elif analysis.rendered_word_count > 0:
        analysis.js_content_gap_ratio = float("inf")

    word_diff = analysis.rendered_word_count - analysis.raw_word_count
    analysis.js_content_gap_flag = bool(
        word_diff >= js_gap_min_word_diff
        and analysis.js_content_gap_ratio >= js_gap_word_threshold_ratio
    )

    return analysis
