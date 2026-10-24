"""Weekly "what changed" file: what opened, what closed, what is failing, and the
trend numbers the other reports already compute. Read-only, file only.

Sources, all local: Heimdall's `incidents` table, the `jobs` table in jarvis.db, and the
artifacts ~/.herald/state/asana-digest.json, ~/.budget/state/spend-by-model-effort.json and
~/.budget/state/usage/status.json. Nothing is recomputed here that another job already writes.

Output: state/reports/weekly-changes/<date>.md and latest.md (Odin, 2026-10-18; it was
~/.jarvis/reports/weekly/), plus the artifact state/weekly-changes.json that the job asserts on.
Usage: analyst weekly-changes [--days N]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from .. import store

sys.path.insert(0, str(Path.home() / ".sentinel"))
from heimdall import store as heimdall_store  # noqa: E402  incidents live in Heimdall's db
DB = store.JARVIS / "jarvis.db"
REPORT_NAME = "weekly-changes"
ARTIFACT = store.STATE / "weekly-changes.json"


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def incidents(conn: sqlite3.Connection, since: float) -> tuple[list, list, list]:
    opened = conn.execute(
        "SELECT kind, summary FROM incidents WHERE opened_at >= ? ORDER BY opened_at", (since,)
    ).fetchall()
    closed = conn.execute(
        "SELECT kind, resolved_by, COUNT(*) FROM incidents WHERE resolved_at >= ? "
        "GROUP BY kind, resolved_by ORDER BY kind", (since,)
    ).fetchall()
    still_open = conn.execute(
        "SELECT id, kind, summary, datetime(opened_at, 'unixepoch', 'localtime') FROM incidents "
        "WHERE resolved_at IS NULL ORDER BY opened_at"
    ).fetchall()
    return opened, closed, still_open


def failing_jobs(conn: sqlite3.Connection) -> list:
    return conn.execute(
        "SELECT name, substr(last_result, 1, 120) FROM jobs "
        "WHERE enabled = 1 AND (last_result LIKE 'FAILED%' OR last_result LIKE 'DEFERRED%') ORDER BY name"
    ).fetchall()


def render(now: datetime, days: int, opened, closed, still_open, failing, extras: list[str]) -> str:
    lines = [
        f"# What changed - week to {now.astimezone():%Y-%m-%d}",
        "",
        f"Window: last {days} days. Generated {now.astimezone():%Y-%m-%d %H:%M}.",
        "",
        f"## Incidents opened ({len(opened)})",
        "",
    ]
    lines += [f"- {kind}: {summary[:140]}" for kind, summary in opened] or ["- none"]
    lines += ["", "## Incidents closed", ""]
    lines += [f"- {kind} by {by or 'open'}: {n}" for kind, by, n in closed] or ["- none"]
    lines += ["", f"## Still open ({len(still_open)})", ""]
    lines += [f"- #{i} {kind} since {when}: {summary[:120]}" for i, kind, summary, when in still_open] or ["- none"]
    lines += ["", f"## Jobs not succeeding ({len(failing)})", ""]
    lines += [f"- {name}: {result}" for name, result in failing] or ["- none"]
    lines += ["", "## Trends", ""]
    lines += [f"- {e}" for e in extras] or ["- no trend artifacts yet"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args(argv)
    now = datetime.now().astimezone()
    since = time.time() - args.days * 86400

    with sqlite3.connect(f"file:{heimdall_store.DB_PATH}?mode=ro", uri=True) as sconn:
        opened, closed, still_open = incidents(sconn, since)
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:  # Jarvis's db: read only
        failing = failing_jobs(conn)

    asana = _json(Path.home() / ".herald" / "state" / "asana-digest.json")  # Hermod's job (moved 2026-10-17)
    spend = _json(Path.home() / ".budget" / "state" / "spend-by-model-effort.json")
    quota = (_json(Path.home() / ".budget" / "state" / "usage" / "status.json").get("claude") or {})
    extras = []
    if asana:
        extras.append(f"Asana: {asana.get('critical', '?')} critical of {asana.get('open', '?')} open; "
                      f"{asana.get('critical_3d', '?')} critical for 3+ days")
    if spend:
        extras.append(f"Spend ({spend.get('days', '?')}d): {spend.get('billable_total', 0):,} billable tokens")
    if quota:
        extras.append(f"Claude 5h estimate: {quota.get('five_hour_billable_tokens', '?'):,} billable tokens")

    text = render(now, args.days, opened, closed, still_open, failing, extras)
    store.write_report(REPORT_NAME, text, day=f"{now:%Y-%m-%d}")
    ARTIFACT.write_text(json.dumps({
        "checked_at": now.isoformat(timespec="seconds"),
        "opened": len(opened),
        "closed": sum(n for _, _, n in closed),
        "still_open": len(still_open),
        "failing_jobs": len(failing),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"weekly-changes: {len(opened)} opened, {sum(n for _, _, n in closed)} closed, "
          f"{len(still_open)} open, {len(failing)} failing job(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
