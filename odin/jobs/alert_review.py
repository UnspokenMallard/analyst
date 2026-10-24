"""Weekly alert signal-to-noise review: which alert keys keep writing while Anze never acts on them.

Anze, 2026-10-15: Jarvis should stop paging him about things nobody acts on. The
week before, 112 alert writes came from 16 keys and one key (burn:repeat:script)
was 64 of them. Nothing measured that.

For each key written to alerts.log in the window (alert_writes), it counts the
writes and looks for any sign Anze engaged:
  - an incident holding the key was resolved by him (resolved_by = 'human'),
  - he pressed Diagnose on such an incident (HUD events.jsonl),
  - the key is or was postponed (state/postponed.json).
A key with at least MIN_WRITES writes, none of these, and a write in the last
STILL_DAYS days is noise (a key that went quiet was fixed, by whoever). Each noisy key
becomes one HUD finding on project jarvis (id from the key, so a dismissed one
stays dismissed, proposed to Jarvis in Odin's state/proposals.json) proposing: fix the cause,
postpone it, raise its cooldown, or retire the check. The report is Odin's
state/reports/alert-review/latest.md.

Read-only for the daemon's state: it changes no config and silences nothing.
Usage: analyst alert-review [--days N] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import store

JARVIS = store.JARVIS
DB = JARVIS / "jarvis.db"
EVENTS = JARVIS / "state" / "hud" / "events.jsonl"
POSTPONED = JARVIS / "state" / "postponed.json"
REPORT_NAME = "alert-review"
ARTIFACT = store.STATE / "alert-review.json"
sys.path.insert(0, str(Path.home() / ".sentinel"))
from heimdall import store as heimdall_store  # noqa: E402  incidents live in Heimdall's db

MIN_WRITES = 5
STILL_DAYS = 3
DIAGNOSE_RE = re.compile(r"^incidents/(\d+)/diagnose$")


def writes_per_key(conn: sqlite3.Connection, since: float) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT key, severity, COUNT(*), MIN(ts), MAX(ts) FROM alert_writes "
        "WHERE ts >= ? GROUP BY key",
        (since,),
    ).fetchall()
    return {k: {"severity": sev, "writes": n, "first": a, "last": b} for k, sev, n, a, b in rows}


def diagnosed_incidents(since: float) -> set[int]:
    ids: set[int] = set()
    try:
        with open(EVENTS, encoding="utf-8") as fh:
            for line in fh:
                if '"diagnose"' not in line and "/diagnose" not in line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                m = DIAGNOSE_RE.match(ev.get("path", ""))
                at = ev.get("at", "")
                if m and at and datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp() >= since:
                    ids.add(int(m.group(1)))
    except OSError:
        pass
    return ids


def engaged_keys(conn: sqlite3.Connection, since: float) -> dict[str, list[str]]:
    """key -> how Anze engaged with it in the window."""
    out: dict[str, list[str]] = {}
    diagnosed = diagnosed_incidents(since)
    for iid, members, resolved_by, resolved_at in conn.execute(
        "SELECT id, members, resolved_by, resolved_at FROM incidents WHERE last_seen_at >= ?", (since,)
    ):
        try:
            keys = json.loads(members or "[]")
        except json.JSONDecodeError:
            keys = []
        for key in keys:
            if iid in diagnosed:
                out.setdefault(key, []).append(f"diagnosed incident {iid}")
            if resolved_by == "human" and (resolved_at or 0) >= since:
                out.setdefault(key, []).append(f"resolved incident {iid}")
    try:
        held = json.loads(POSTPONED.read_text(encoding="utf-8"))
        entries = held.get("entries", held) if isinstance(held, dict) else held
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("key"):
                out.setdefault(entry["key"], []).append("postponed")
    except (OSError, json.JSONDecodeError):
        pass
    return out


def finding_for(key: str, info: dict, days: int) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "id": "noise-" + hashlib.sha1(key.encode()).hexdigest()[:10],
        "project": "jarvis",
        "severity": "low",
        "kind": "noise",
        "title": f"Alert [{key}] wrote {info['writes']}x in {days} days and was never acted on.",
        "file": "config.toml",
        "line": 0,
        "detail": f"{info['writes']} {info['severity']} write(s) between "
                  f"{datetime.fromtimestamp(info['first']):%Y-%m-%d} and {datetime.fromtimestamp(info['last']):%Y-%m-%d}; "
                  "no Diagnose, no incident resolved by hand, never postponed. See ~/.analyst/state/reports/alert-review/latest.md.",
        "suggestion": "Pick one: fix the cause; postpone it (daemon/postpone.py); raise the check's cooldown; "
                      "or retire the check if its signal is worth nothing.",
        "source": "alert-review",
        "status": "open",
        "foundAt": now,
        "lastSeen": now,
    }


def write_findings(new: list[dict]) -> list[str]:
    """Propose them (Jarvis's proposals-watch files them); returns the ids not seen before."""
    return store.propose_new(new)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    since = time.time() - args.days * 86400

    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30) as conn:
        per_key = writes_per_key(conn, since)
    with sqlite3.connect(f"file:{heimdall_store.DB_PATH}?mode=ro", uri=True, timeout=30) as sconn:
        engaged = engaged_keys(sconn, since)

    total = sum(v["writes"] for v in per_key.values())
    recent = time.time() - STILL_DAYS * 86400
    noisy = {k: v for k, v in per_key.items()
             if v["writes"] >= MIN_WRITES and k not in engaged and v["last"] >= recent}
    ranked = sorted(per_key.items(), key=lambda kv: -kv[1]["writes"])

    lines = [f"# Alert review - {datetime.now():%Y-%m-%d %H:%M}", "",
             f"{total} alert write(s) from {len(per_key)} key(s) in the last {args.days} days. "
             f"Noise = {MIN_WRITES}+ writes, never acted on, still writing in the last {STILL_DAYS} days: "
             f"{len(noisy)} key(s).", "",
             "| writes | severity | key | acted on |", "|---:|---|---|---|"]
    for key, info in ranked:
        how = ", ".join(sorted(set(engaged.get(key, [])))) or ("**no (noise)**" if key in noisy else "no")
        lines.append(f"| {info['writes']} | {info['severity']} | `{key}` | {how} |")

    added: list[str] = []
    if not args.dry_run:
        added = write_findings([finding_for(k, v, args.days) for k, v in noisy.items()])
        store.write_report(REPORT_NAME, "\n".join(lines) + "\n")
        ARTIFACT.write_text(json.dumps({
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "writes": total, "keys": len(per_key), "noisy": sorted(noisy), "findings_added": added,
        }, indent=2), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nfindings added: {len(added)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
