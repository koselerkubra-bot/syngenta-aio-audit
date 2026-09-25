"""Offline smoke tests: no network, no real browser. These exercise the
parsing/aggregation/rendering logic against synthetic HTML so template
or logic bugs are caught before the tool ever touches a live site.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analyzer import analyze_page
from src.aggregator import build_summary
from src.robots_check import _parse_robots
from src.dashboard import render_dashboard, render_hub
from src.sites_config import add_site, load_sites, slugify_domain

REPO_ROOT = Path(__file__).resolve().parents[1]

# --- Simulates the real Boundary LQD / Axial finding: headings with no
# --- text underneath in the raw HTML, filled in only by JavaScript.
RAW_EMPTY_TEMPLATE = """
<html><head><title>Boundary LQD - Herbicide | Syngenta CA</title>
<meta name="description" content="Boundary LQD,Herbicide"></head>
<body>
<img src="<>">
<h3>Active ingredients</h3>
-
<h2>Uses</h2>
<h3>For use on:</h3>
<h2>Application information</h2>
</body></html>
"""

RENDERED_FULL_TEMPLATE = """
<html><head><title>Boundary LQD - Herbicide | Syngenta CA</title>
<meta name="description" content="Boundary LQD,Herbicide">
<script type="application/ld+json">
{"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": "x"}]}
</script>
</head>
<body>
<h1>Boundary LQD Herbicide</h1>
<img src="boundary.jpg" alt="Boundary LQD sprayed on soybean field, Ontario Canada">
<h3>Active ingredients</h3>
<p>Metribuzin and S-metolachlor, a combination herbicide for residual weed control in soybeans.</p>
<h2>What crops is Boundary LQD used on?</h2>
<h3>For use on: soybeans grown in Eastern Canada, in soils with organic matter between one and ten percent.</h3>
<h2>How should Boundary LQD be applied?</h2>
<p>Apply pre-plant incorporated or pre-emergent, at label rate, with adequate agitation to keep the tank mixture uniform throughout application.</p>
</body></html>
"""

NORMAL_PAGE_HTML = """
<html><head><title>Syngenta Canada: Crop Solutions for Growers</title>
<meta name="description" content="Syngenta Canada offers crop protection, seeds, and agronomy support for growers across every major Canadian crop and region."></head>
<body>
<h1>Syngenta Canada: Crop Protection, Seeds and Agronomy</h1>
<p>Syngenta Canada supports growers across cereals, corn, horticulture and potatoes with crop protection products, seed genetics, and agronomy advice.</p>
<h2>What products does Syngenta Canada offer?</h2>
<img src="team.jpg" alt="Syngenta Canada agronomy team in a wheat field, Ontario">
</body></html>
"""


def test_js_content_gap_is_flagged_for_empty_template():
    analysis = analyze_page(
        url="https://www.syngenta.ca/productsdetail/boundary-lqd",
        raw_html=RAW_EMPTY_TEMPLATE,
        rendered_html=RENDERED_FULL_TEMPLATE,
        js_gap_word_threshold_ratio=3.0,
        js_gap_min_word_diff=20,
    )
    assert analysis.js_content_gap_flag is True, "Expected the JS content gap to be flagged"
    assert analysis.has_faqpage_schema is True
    assert analysis.page_type == "product"
    print("OK: js_content_gap_flag True, has_faqpage_schema True, page_type=product")


def test_normal_page_is_not_flagged():
    analysis = analyze_page(
        url="https://www.syngenta.ca/",
        raw_html=NORMAL_PAGE_HTML,
        rendered_html=NORMAL_PAGE_HTML,
        js_gap_word_threshold_ratio=3.0,
        js_gap_min_word_diff=20,
    )
    assert analysis.js_content_gap_flag is False
    assert analysis.h1_count == 1
    assert analysis.page_type == "homepage"
    assert analysis.h2_question_ratio == 1.0, "The single H2 is phrased as a question"
    print("OK: normal page not flagged, h1_count=1, page_type=homepage, h2_question_ratio=1.0")


def test_build_summary_aggregates_two_pages():
    p1 = analyze_page(
        "https://www.syngenta.ca/productsdetail/boundary-lqd",
        RAW_EMPTY_TEMPLATE, RENDERED_FULL_TEMPLATE, 3.0, 20,
    ).to_dict()
    p2 = analyze_page(
        "https://www.syngenta.ca/", NORMAL_PAGE_HTML, NORMAL_PAGE_HTML, 3.0, 20,
    ).to_dict()

    summary = build_summary([p1, p2], meta_title_max_len=60, meta_desc_min_len=120, meta_desc_max_len=155)
    assert summary["total_pages"] == 2
    assert summary["js_content_gap"]["count"] == 1
    assert summary["faqpage_schema_present"]["count"] == 1
    print("OK: build_summary ->", json.dumps(summary, indent=2))


def test_robots_parser_detects_blocked_bot():
    sample = """
    User-agent: GPTBot
    Disallow: /

    User-agent: *
    Disallow:
    """
    groups = _parse_robots(sample)
    assert groups["GPTBot"] == ["/"]
    assert groups["*"] == [""]
    print("OK: robots parser groups ->", groups)


def test_dashboard_template_renders_without_error():
    p1 = analyze_page(
        "https://www.syngenta.ca/productsdetail/boundary-lqd",
        RAW_EMPTY_TEMPLATE, RENDERED_FULL_TEMPLATE, 3.0, 20,
    ).to_dict()
    p2 = analyze_page(
        "https://www.syngenta.ca/", NORMAL_PAGE_HTML, NORMAL_PAGE_HTML, 3.0, 20,
    ).to_dict()
    pages = [p1, p2]

    summary = build_summary(pages, meta_title_max_len=60, meta_desc_min_len=120, meta_desc_max_len=155)
    summary["ai_bot_access"] = {
        "robots_txt_url": "https://www.syngenta.ca/robots.txt",
        "reachable": True,
        "bots": {"GPTBot": "blocked", "PerplexityBot": "allowed", "Google-Extended": "not_mentioned"},
    }

    timeseries = [
        {"date": "2026-09-15", **summary},
        {"date": "2026-09-22", **summary},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        out_path = str(Path(tmp) / "index.html")
        render_dashboard(
            template_dir=str(REPO_ROOT / "templates"),
            output_path=out_path,
            domain="https://www.syngenta.ca",
            generated_at="2026-09-25 06:00 UTC",
            summary=summary,
            pages=pages,
            timeseries=timeseries,
        )
        html = Path(out_path).read_text(encoding="utf-8")
        assert "AIO Status" in html
        assert "boundary-lqd" in html
        assert len(html) > 2000
    print("OK: dashboard template rendered,", len(html), "characters")


def test_slugify_domain():
    assert slugify_domain("https://www.syngenta.ca/some/path") == "syngenta-ca"
    assert slugify_domain("https://www.syngenta.com.mx") == "syngenta-com-mx"
    print("OK: slugify_domain ->", slugify_domain("https://www.syngenta.ca"), slugify_domain("https://www.syngenta.com.mx"))


def test_add_site_is_idempotent_and_infers_sitemap():
    with tempfile.TemporaryDirectory() as tmp:
        sites_path = str(Path(tmp) / "sites.yaml")

        entry1 = add_site("https://www.syngenta.com.mx/productsdetail/foo", name="Syngenta Mexico", sites_path=sites_path)
        assert entry1["slug"] == "syngenta-com-mx"
        assert entry1["domain"] == "https://www.syngenta.com.mx"
        assert entry1["sitemap_urls"] == ["https://www.syngenta.com.mx/sitemap.xml"]

        # Adding the same domain again (different path on it) must not duplicate the entry.
        entry2 = add_site("https://www.syngenta.com.mx/some-other-page", sites_path=sites_path)
        assert entry2["slug"] == entry1["slug"]

        sites = load_sites(sites_path)
        assert len(sites) == 1
    print("OK: add_site is idempotent and infers a sitemap URL ->", entry1)


def test_hub_template_renders_without_error():
    summary_a = {
        "total_pages": 42,
        "js_content_gap": {"pct": 12.5},
        "faqpage_schema_present": {"pct": 60.0},
    }
    summary_b = {
        "total_pages": 5,
        "js_content_gap": {"pct": 0.0},
        "faqpage_schema_present": {"pct": 100.0},
    }
    sites = [
        {"name": "Syngenta Canada", "slug": "syngenta-ca", "domain": "https://www.syngenta.ca", "generated_at": "2026-09-25", "summary": summary_a},
        {"name": "Syngenta Mexico", "slug": "syngenta-com-mx", "domain": "https://www.syngenta.com.mx", "generated_at": "2026-09-25", "summary": summary_b},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        out_path = str(Path(tmp) / "index.html")
        render_hub(
            template_dir=str(REPO_ROOT / "templates"),
            output_path=out_path,
            generated_at="2026-09-25 06:00 UTC",
            sites=sites,
        )
        html = Path(out_path).read_text(encoding="utf-8")
        assert "Syngenta Canada" in html
        assert "Syngenta Mexico" in html
        assert "syngenta-com-mx/" in html
    print("OK: hub template rendered,", len(html), "characters")


def test_hub_template_renders_with_no_sites_yet():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = str(Path(tmp) / "index.html")
        render_hub(
            template_dir=str(REPO_ROOT / "templates"),
            output_path=out_path,
            generated_at="2026-09-25 06:00 UTC",
            sites=[],
        )
        html = Path(out_path).read_text(encoding="utf-8")
        assert "No sites tracked yet" in html
    print("OK: hub template handles the empty-state case")


if __name__ == "__main__":
    test_js_content_gap_is_flagged_for_empty_template()
    test_normal_page_is_not_flagged()
    test_build_summary_aggregates_two_pages()
    test_robots_parser_detects_blocked_bot()
    test_dashboard_template_renders_without_error()
    test_slugify_domain()
    test_add_site_is_idempotent_and_infers_sitemap()
    test_hub_template_renders_without_error()
    test_hub_template_renders_with_no_sites_yet()
    print("\nAll smoke tests passed.")
