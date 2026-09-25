"""Registry of tracked sites (config/sites.yaml).

Each entry is one site the tool scans and publishes its own dashboard
for. Adding a site here (by hand, or via `scanner.py --add-url`) is all
it takes for the weekly scheduled run to start covering it too.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

DEFAULT_SITES_PATH = "config/sites.yaml"


def slugify_domain(domain: str) -> str:
    host = urlparse(domain).netloc or domain
    host = host.lower()
    if host.startswith("www."):
        host = host[len("www."):]
    return re.sub(r"[^a-z0-9]+", "-", host).strip("-")


def load_sites(path: str = DEFAULT_SITES_PATH) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data.get("sites", [])


def save_sites(sites: list[dict], path: str = DEFAULT_SITES_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.safe_dump({"sites": sites}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def find_site(sites: list[dict], slug_or_domain: str) -> dict | None:
    target_slug = slugify_domain(slug_or_domain) if "://" in slug_or_domain else slug_or_domain
    for site in sites:
        if site.get("slug") == target_slug or site.get("slug") == slug_or_domain:
            return site
        if slugify_domain(site.get("domain", "")) == target_slug:
            return site
    return None


def add_site(
    url: str,
    name: str | None = None,
    sites_path: str = DEFAULT_SITES_PATH,
) -> dict:
    """Add a new site to the registry from any URL on that site (not
    necessarily its homepage). Idempotent: adding the same domain twice
    just returns the existing entry.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"'{url}' does not look like a full URL (missing http(s)://).")

    domain = f"{parsed.scheme}://{parsed.netloc}"
    slug = slugify_domain(domain)

    sites = load_sites(sites_path)
    existing = find_site(sites, slug)
    if existing is not None:
        return existing

    entry = {
        "name": name or parsed.netloc,
        "slug": slug,
        "domain": domain,
        "sitemap_urls": [f"{domain}/sitemap.xml"],
    }
    sites.append(entry)
    save_sites(sites, sites_path)
    return entry
