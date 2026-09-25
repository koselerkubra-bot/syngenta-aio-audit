"""Roll many per-page analyses up into a single, site-wide, point-in-time
summary. Pure arithmetic over what analyzer.py already found, no new
judgments and no recommendations.
"""

from __future__ import annotations

from collections import Counter
from statistics import mean


def build_summary(
    pages: list[dict],
    meta_title_max_len: int,
    meta_desc_min_len: int,
    meta_desc_max_len: int,
) -> dict:
    total = len(pages)
    if total == 0:
        return {"total_pages": 0}

    def pct(count: int) -> float:
        return round(100 * count / total, 1)

    js_gap = sum(1 for p in pages if p.get("js_content_gap_flag"))
    no_h1 = sum(1 for p in pages if p.get("h1_count", 0) == 0)
    multi_h1 = sum(1 for p in pages if p.get("h1_count", 0) > 1)

    title_missing = sum(1 for p in pages if not p.get("meta_title"))
    title_too_long = sum(1 for p in pages if p.get("meta_title_len", 0) > meta_title_max_len)

    desc_missing = sum(1 for p in pages if not p.get("meta_description"))
    desc_out_of_range = sum(
        1
        for p in pages
        if p.get("meta_description")
        and not (meta_desc_min_len <= p.get("meta_description_len", 0) <= meta_desc_max_len)
    )

    has_faq_schema = sum(1 for p in pages if p.get("has_faqpage_schema"))
    any_schema = sum(1 for p in pages if p.get("schema_types_found"))

    h2_ratios = [p.get("h2_question_ratio", 0) for p in pages if p.get("h2_texts")]
    avg_h2_question_pct = round(100 * mean(h2_ratios), 1) if h2_ratios else None

    freshness_present = sum(1 for p in pages if p.get("freshness_signal_present"))

    alt_totals: Counter = Counter()
    for p in pages:
        for k, v in (p.get("alt_text") or {}).items():
            alt_totals[k] += v

    by_type = Counter(p.get("page_type", "other") for p in pages)

    return {
        "total_pages": total,
        "pages_by_type": dict(by_type),
        "js_content_gap": {"count": js_gap, "pct": pct(js_gap)},
        "missing_h1": {"count": no_h1, "pct": pct(no_h1)},
        "multiple_h1": {"count": multi_h1, "pct": pct(multi_h1)},
        "meta_title_missing": {"count": title_missing, "pct": pct(title_missing)},
        "meta_title_too_long": {"count": title_too_long, "pct": pct(title_too_long)},
        "meta_description_missing": {"count": desc_missing, "pct": pct(desc_missing)},
        "meta_description_out_of_range": {"count": desc_out_of_range, "pct": pct(desc_out_of_range)},
        "faqpage_schema_present": {"count": has_faq_schema, "pct": pct(has_faq_schema)},
        "any_schema_present": {"count": any_schema, "pct": pct(any_schema)},
        "avg_h2_question_phrasing_pct": avg_h2_question_pct,
        "freshness_signal_present": {"count": freshness_present, "pct": pct(freshness_present)},
        "image_alt_totals": dict(alt_totals),
    }
