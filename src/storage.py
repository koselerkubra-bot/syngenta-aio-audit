"""Read/write the JSON files that hold the current run's page-level
detail and the week-over-week summary time series.

Design choice: full page-level detail is kept only for the latest run
(overwritten each week) plus one dated snapshot per week under
data/history/. The lightweight summary time series accumulates
indefinitely, since it is small, and is what the dashboard's trend
lines are built from.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def save_latest_pages(path: str, pages: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")


def save_history_snapshot(history_dir: str, pages: list[dict]) -> str:
    Path(history_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = Path(history_dir) / f"{stamp}.json"
    out_path.write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out_path)


def append_timeseries(path: str, summary: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    entry = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), **summary}

    existing: list[dict] = []
    if Path(path).exists():
        try:
            existing = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []

    # Re-running on the same day (e.g. a manual workflow_dispatch) replaces
    # that day's row instead of appending a duplicate.
    existing = [e for e in existing if e.get("date") != entry["date"]]
    existing.append(entry)
    existing.sort(key=lambda e: e["date"])

    Path(path).write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


def load_timeseries(path: str) -> list[dict]:
    if not Path(path).exists():
        return []
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
