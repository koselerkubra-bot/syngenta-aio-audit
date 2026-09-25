"""Fetch a page two ways so the tool can measure the gap between them:

* ``fetch_raw`` -- a plain HTTP GET, no JavaScript execution. This is
  close to what most AI crawlers (GPTBot, PerplexityBot, and similar)
  actually see.
* ``RenderedFetcher`` -- a headless Chromium fetch via Playwright, which
  runs the page's JavaScript first. This is close to what a person, or
  Googlebot, sees.

The difference between the two is exactly the "JS content gap" finding
from the manual audit (the Boundary LQD / Axial product template case).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests
from playwright.sync_api import Browser, sync_playwright

logger = logging.getLogger(__name__)


def fetch_raw(url: str, timeout: int, user_agent: str) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": user_agent})
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # noqa: BLE001 - a single failed page shouldn't stop the run
        logger.warning("Raw fetch failed for %s: %s", url, exc)
        return None


class RenderedFetcher:
    """Reuses a single headless-browser instance across many pages, so the
    (relatively expensive) browser start-up cost is paid once per run,
    not once per page. Use as a context manager::

        with RenderedFetcher(user_agent, timeout_ms) as renderer:
            html = renderer.fetch(url)
    """

    def __init__(self, user_agent: str, timeout_ms: int):
        self._user_agent = user_agent
        self._timeout_ms = timeout_ms
        self._pw = None
        self._browser: Optional[Browser] = None

    def __enter__(self) -> "RenderedFetcher":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        return self

    def __exit__(self, *exc_info) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()

    def fetch(self, url: str) -> Optional[str]:
        if self._browser is None:
            raise RuntimeError("Use RenderedFetcher as a context manager: 'with RenderedFetcher(...) as r:'")
        context = self._browser.new_context(user_agent=self._user_agent)
        page = context.new_page()
        try:
            page.goto(url, timeout=self._timeout_ms, wait_until="networkidle")
            return page.content()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Rendered fetch failed for %s: %s", url, exc)
            return None
        finally:
            context.close()


def polite_delay(seconds: float) -> None:
    """A small pause between page fetches. Keeps the weekly scan a good
    citizen on the target site rather than a burst of concurrent load.
    """
    if seconds > 0:
        time.sleep(seconds)
