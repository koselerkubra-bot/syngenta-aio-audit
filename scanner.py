"""Entry point: scan one or every tracked site, persist results, and
regenerate each site's dashboard plus the top-level hub page.

Designed to run unattended on a schedule (see
.github/workflows/weekly-scan.yml) with no dependency on any AI model
or external assistant at run time. Every check is deterministic Python
reading real, freshly fetched HTML.

Usage:
    python scanner.py --all
    python scanner.py --site syngenta-ca
    python scanner.py --add-url https://www.syngenta.com.mx --name "Syngenta Mexico"

    # quick local test, only the first N discovered pages:
    python scanner.py --site syngenta-ca --limit 10
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Optional

import yaml

from src.aggregator import build_summary
from src.analyzer import analyze_page
from src.dashboard import render_dashboard, render_hub
from src.fetcher import RenderedFetcher, fetch_raw, polite_delay
from src.robots_check import check_ai_bot_access
from src.sitemap_discovery import discover_urls
from src.sites_config import add_site, load_sites
from src.storage import append_timeseries, load_timeseries, save_history_snapshot, save_latest_pages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("aio_scanner")

CONFIG_PATH = "config.yaml"
SITES_PATH = "config/sites.yaml"


def load_shared_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _resolve_paths(cfg: dict, slug: str) -> dict:
    return {
        "latest_pages_file": cfg["latest_pages_file"].format(slug=slug),
        "history_dir": cfg["history_dir"].format(slug=slug),
        "timeseries_file": cfg["timeseries_file"].format(slug=slug),
        "dashboard_output": cfg["dashboard_output"].format(slug=slug),
    }


def scan_site(site: dict, cfg: dict, limit: Optional[int] = None, delay_seconds: float = 1.0) -> None:
    """Run the full pipeline for one site: discover, fetch, analyze,
    persist, and render that site's own dashboard.
    """
    slug = site["slug"]
    domain = site["domain"]
    paths = _resolve_paths(cfg, slug)

    logger.info("[%s] Discovering pages via sitemap for %s", slug, domain)
    urls = discover_urls(
        domain=domain,
        seed_sitemaps=site.get("sitemap_urls", []),
        timeout=cfg["request_timeout"],
        user_agent=cfg["user_agent"],
        exclude_patterns=cfg.get("exclude_patterns", []),
    )
    if cfg.get("max_pages"):
        urls = urls[: cfg["max_pages"]]
    if limit:
        urls = urls[:limit]
    logger.info("[%s] Scanning %d page(s).", slug, len(urls))

    pages: list[dict] = []
    with RenderedFetcher(cfg["user_agent"], cfg["render_timeout_ms"]) as renderer:
        for i, url in enumerate(urls, start=1):
            logger.info("[%s] [%d/%d] %s", slug, i, len(urls), url)
            raw_html = fetch_raw(url, cfg["request_timeout"], cfg["user_agent"])
            rendered_html = renderer.fetch(url)
            analysis = analyze_page(
                url,
                raw_html,
                rendered_html,
                js_gap_word_threshold_ratio=cfg["js_gap_word_threshold_ratio"],
                js_gap_min_word_diff=cfg["js_gap_min_word_diff"],
            )
            pages.append(analysis.to_dict())
            polite_delay(delay_seconds)

    summary = build_summary(
        pages,
        meta_title_max_len=cfg["meta_title_max_len"],
        meta_desc_min_len=cfg["meta_desc_min_len"],
        meta_desc_max_len=cfg["meta_desc_max_len"],
    )
    summary["ai_bot_access"] = check_ai_bot_access(
        domain=domain,
        bots=cfg.get("ai_bots_to_check", []),
        timeout=cfg["request_timeout"],
        user_agent=cfg["user_agent"],
    )

    save_latest_pages(paths["latest_pages_file"], pages)
    save_history_snapshot(paths["history_dir"], pages)
    append_timeseries(paths["timeseries_file"], summary)
    timeseries = load_timeseries(paths["timeseries_file"])

    render_dashboard(
        template_dir="templates",
        output_path=paths["dashboard_output"],
        domain=domain,
        site_name=site.get("name", domain),
        back_link="../",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        summary=summary,
        pages=pages,
        timeseries=timeseries,
    )
    logger.info("[%s] Dashboard written to %s", slug, paths["dashboard_output"])


def rebuild_hub(cfg: dict, sites: list[dict]) -> None:
    """Regenerate the top-level docs/index.html from whatever each
    tracked site's own history already has, regardless of which site(s)
    were actually scanned in this run.
    """
    hub_entries = []
    for site in sites:
        slug = site["slug"]
        paths = _resolve_paths(cfg, slug)
        timeseries = load_timeseries(paths["timeseries_file"])
        if not timeseries:
            continue  # never scanned yet, leave it out of the hub for now
        last = timeseries[-1]
        hub_entries.append(
            {
                "name": site.get("name", slug),
                "slug": slug,
                "domain": site["domain"],
                "generated_at": last.get("date", "unknown"),
                "summary": last,
            }
        )

    render_hub(
        template_dir="templates",
        output_path=cfg["hub_output"],
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        sites=hub_entries,
    )
    logger.info("Hub page written to %s (%d site(s) listed)", cfg["hub_output"], len(hub_entries))


def main() -> None:
    parser = argparse.ArgumentParser(description="Technical AIO/AEO scan, one or every tracked site.")
    parser.add_argument("--config", default=CONFIG_PATH)
    parser.add_argument("--sites-file", default=SITES_PATH)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Scan every site in config/sites.yaml.")
    group.add_argument("--site", help="Scan only this one site, by its slug (see config/sites.yaml).")
    group.add_argument(
        "--add-url",
        help="Add a new site from any URL on it (its domain root and /sitemap.xml are inferred), then scan it.",
    )
    parser.add_argument("--name", help="Display name for --add-url. Defaults to the domain.")
    parser.add_argument("--limit", type=int, default=None, help="Only scan the first N discovered URLs per site.")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between page fetches.")
    args = parser.parse_args()

    cfg = load_shared_config(args.config)

    if args.add_url:
        site = add_site(args.add_url, name=args.name, sites_path=args.sites_file)
        logger.info("Tracking new site: %s (%s)", site["name"], site["slug"])
        scan_site(site, cfg, limit=args.limit, delay_seconds=args.delay)
        rebuild_hub(cfg, load_sites(args.sites_file))
        return

    sites = load_sites(args.sites_file)
    if not sites:
        logger.warning("No sites configured in %s yet.", args.sites_file)
        return

    if args.site:
        site = next((s for s in sites if s["slug"] == args.site), None)
        if site is None:
            raise SystemExit(f"No site with slug '{args.site}' in {args.sites_file}.")
        scan_site(site, cfg, limit=args.limit, delay_seconds=args.delay)
    else:  # --all
        for site in sites:
            scan_site(site, cfg, limit=args.limit, delay_seconds=args.delay)

    rebuild_hub(cfg, sites)


if __name__ == "__main__":
    main()
