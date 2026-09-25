"""Render the static dashboard (docs/index.html) from the latest run's
data plus the accumulated week-over-week time series.

This reports CURRENT STATE only: pass/fail facts and trend lines. It
does not generate recommendations or an action plan; that judgment is
left to the person reading the dashboard.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


def _sparkline_points(values: list[float], width: int = 240, height: int = 56, pad: int = 6) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)
    step = (width - 2 * pad) / max(n - 1, 1)
    points = []
    for i, v in enumerate(values):
        x = pad + i * step
        y = height - pad - ((v - lo) / span) * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def render_dashboard(
    template_dir: str,
    output_path: str,
    domain: str,
    generated_at: str,
    summary: dict,
    pages: list[dict],
    timeseries: list[dict],
    site_name: str | None = None,
    back_link: str | None = None,
) -> None:
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html.j2")

    trend_series = {
        "js_content_gap_pct": [row.get("js_content_gap", {}).get("pct", 0) for row in timeseries],
        "faqpage_schema_pct": [row.get("faqpage_schema_present", {}).get("pct", 0) for row in timeseries],
        "meta_description_ok_pct": [
            round(100 - row.get("meta_description_out_of_range", {}).get("pct", 0), 1)
            for row in timeseries
        ],
    }
    sparklines = {name: _sparkline_points(values) for name, values in trend_series.items()}
    trend_dates = [row.get("date") for row in timeseries]
    trend_latest = {name: (values[-1] if values else None) for name, values in trend_series.items()}
    trend_previous = {
        name: (values[-2] if len(values) > 1 else None) for name, values in trend_series.items()
    }

    # Pages with something flagged surface first in the table.
    def sort_key(p: dict) -> tuple:
        return (
            not p.get("js_content_gap_flag"),
            p.get("h1_count", 0) != 0,
            bool(p.get("meta_description")),
            p.get("url", ""),
        )

    sorted_pages = sorted(pages, key=sort_key)

    html = template.render(
        domain=domain,
        site_name=site_name or domain,
        back_link=back_link,
        generated_at=generated_at,
        summary=summary,
        pages=sorted_pages,
        trend_dates=trend_dates,
        sparklines=sparklines,
        trend_latest=trend_latest,
        trend_previous=trend_previous,
        has_history=len(timeseries) > 1,
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")


def render_hub(template_dir: str, output_path: str, generated_at: str, sites: list[dict]) -> None:
    """Render the top-level docs/index.html that lists every tracked site.

    Each entry in ``sites`` is expected to have: name, slug, domain,
    generated_at, and summary (the same summary dict a per-site
    dashboard uses), so the hub can show one headline stat per site.
    """
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("hub.html.j2")
    html = template.render(generated_at=generated_at, sites=sites)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
