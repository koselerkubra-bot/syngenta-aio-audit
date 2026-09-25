"""Check whether known AI crawlers are blocked in the site's robots.txt.

This is a small, dependency-free robots.txt reader rather than
``urllib.robotparser``, because we need per-bot group visibility
(which named user-agent blocks exist) rather than a single allow/deny
answer for one agent.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


def _parse_robots(text: str) -> dict[str, list[str]]:
    """Return ``{user_agent_name: [disallow paths]}`` for every group in
    the file. A "group" starts at a ``User-agent:`` line (or a run of
    consecutive ones) and ends at the next ``User-agent:`` line.
    """
    groups: dict[str, list[str]] = {}
    current_agents: list[str] = []
    agents_pending = True

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            if not agents_pending:
                current_agents = []
            current_agents.append(value)
            groups.setdefault(value, [])
            agents_pending = True
        elif field == "disallow":
            agents_pending = False
            for agent in current_agents:
                groups.setdefault(agent, []).append(value)
        else:
            agents_pending = False

    return groups


def check_ai_bot_access(domain: str, bots: list[str], timeout: int, user_agent: str) -> dict:
    """For each bot in ``bots``, report whether robots.txt disallows it
    entirely (``Disallow: /`` in its own group, or in the wildcard ``*``
    group if the bot has no group of its own).
    """
    robots_url = urljoin(domain, "/robots.txt")
    result: dict = {"robots_txt_url": robots_url, "reachable": False, "bots": {}}

    try:
        resp = requests.get(robots_url, timeout=timeout, headers={"User-Agent": user_agent})
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch robots.txt at %s: %s", robots_url, exc)
        for bot in bots:
            result["bots"][bot] = "unknown"
        return result

    result["reachable"] = True
    groups = _parse_robots(resp.text)
    wildcard_disallows = groups.get("*", [])

    for bot in bots:
        matched_agent = next((a for a in groups if a.lower() == bot.lower()), None)
        if matched_agent is not None:
            disallows = groups[matched_agent]
            status = "blocked" if "/" in disallows else "allowed"
        elif wildcard_disallows:
            status = "blocked" if "/" in wildcard_disallows else "allowed"
        else:
            status = "not_mentioned"
        result["bots"][bot] = status

    return result
