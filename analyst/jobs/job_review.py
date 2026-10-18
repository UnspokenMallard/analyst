"""Weekly job-value review: which finding-raising jobs cost money and produce findings Anze never accepts.

Anze, 2026-10-15: audits only propose, nothing measured whether proposals land. For each job
whose output is HUD findings ([job_findings] in config.toml), over the last 30 days it counts the findings it
raised and how they ended (same rule as the HUD's Job value panel, hud/lib/jobvalue.js):
resolved, dismissed, or ignored (still open after IGNORED_DAYS). A job with at least
MIN_DECIDED decided-or-ignored findings and acceptance below MAX_ACCEPT percent becomes one
HUD finding on project claude-config proposing to pause or retune it. The finding id comes from
the job name, so a dismissed one stays dismissed. The report is Analyst's state/reports/job-review/latest.md.

Read-only for the daemon's state: it edits no config and pauses nothing.
Usage: analyst job-review [--days N] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .. import store

JARVIS = store.JARVIS
DB = Path.home() / ".budget" / "state" / "budget.db"  # job_calls, in Budget since 2026-10-17
FINDINGS = store.FINDINGS  # read only: the outcomes of each job's filed findings
REPORT_NAME = "job-review"
ARTIFACT = store.STATE / "job-review.json"
CONFIG = JARVIS / "config.toml"
IGNORED_DAYS = 14
MIN_DECIDED = 5
MAX_ACCEPT = 10


def job_sources() -> dict[str, str]:
    """Job name -> finding source, from [job_findings] in config.toml (also read by hud/lib/jobvalue.js)."""
    with CONFIG.open("rb") as f:
        return tomllib.load(f).get("job_findings", {})


def parse_ts(s: str) -> float:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def outcomes(findings: list[dict], source: str, since: float, now: float) -> dict:
    mine = [f for f in findings if f.get("source") == source and parse_ts(f.get("foundAt", "")) >= since]
    resolved = sum(f.get("status") == "resolved" for f in mine)
    dismissed = sum(f.get("status") == "dismissed" for f in mine)
    ignored = sum(f.get("status") == "open" and parse_ts(f.get("foundAt", "")) < now - IGNORED_DAYS * 86400 for f in mine)
    decided = resolved + dismissed + ignored
    return {"raised": len(mine), "resolved": resolved, "dismissed": dismissed, "ignored": ignored,
            "decided": decided, "acceptance": round(100 * resolved / decided) if decided else None}


def paused_jobs(now: float) -> set[str]:
    """Jobs held by a pause that has not ended (daemon/jobpause.py). Held jobs are reported but not flagged."""
    try:
        doc = json.loads((JARVIS / "state" / "job-pauses.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    out = set()
    for job, e in (doc.items() if isinstance(doc, dict) else []):
        if not isinstance(e, dict):
            continue
        if e.get("until") is None:
            out.add(job)
            continue
        try:
            if datetime.fromisoformat(e["until"]).timestamp() > now:
                out.add(job)
        except (TypeError, ValueError):
            pass
    return out


def spend(conn: sqlite3.Connection, job: str, since: float) -> float:
    row = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM job_calls WHERE job = ? AND ts >= ?", (job, since)).fetchone()
    return round(row[0] or 0, 2)


def finding_for(job: str, o: dict, usd: float, days: int) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "id": "jobvalue-" + hashlib.sha1(job.encode()).hexdigest()[:10],
        "project": "claude-config",
        "severity": "low",
        "kind": "job-value",
        "title": f"Job [{job}] has {o['acceptance']}% of its findings accepted over {days} days (${usd}).",
        "file": "config.toml",
        "line": 0,
        "detail": f"{o['raised']} raised, {o['resolved']} resolved, {o['dismissed']} dismissed, {o['ignored']} ignored. "
                  "See ~/.analyst/state/reports/job-review/latest.md and the HUD Jarvis panel, Job value.",
        "suggestion": "Pick one: pause the job, make its prompt stricter, or lengthen its schedule. "
                      "The job is not changed automatically.",
        "source": "job-review",
        "status": "open",
        "foundAt": now,
        "lastSeen": now,
    }


def write_findings(new: list[dict]) -> list[str]:
    """Propose them (Jarvis's proposals-watch files them); returns the ids not seen before."""
    return store.propose_new(new)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    now = time.time()
    since = now - args.days * 86400

    try:
        findings = json.loads(FINDINGS.read_text(encoding="utf-8")).get("findings", [])
    except (OSError, json.JSONDecodeError):
        findings = []
    rows, flagged = [], []
    held = paused_jobs(now)
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30) as conn:
        for job, source in job_sources().items():
            o, usd = outcomes(findings, source, since, now), spend(conn, job, since)
            rows.append((job, usd, o))
            if job in held:
                continue
            if o["decided"] >= MIN_DECIDED and o["acceptance"] is not None and o["acceptance"] < MAX_ACCEPT:
                flagged.append(finding_for(job, o, usd, args.days))

    lines = [f"# Job review ({datetime.now():%Y-%m-%d})", "",
             f"Window {args.days} days. Flag: at least {MIN_DECIDED} decided-or-ignored findings and acceptance under {MAX_ACCEPT}%.", "",
             "| job | spend | raised | resolved | dismissed | ignored | acceptance |", "|---|---|---|---|---|---|---|"]
    for job, usd, o in rows:
        acc = "n/a" if o["acceptance"] is None else f"{o['acceptance']}%"
        if job in held:
            acc += " (paused, not flagged)"
        lines.append(f"| {job} | ${usd} | {o['raised']} | {o['resolved']} | {o['dismissed']} | {o['ignored']} | {acc} |")
    print("\n".join(lines))
    added: list[str] = []
    if not args.dry_run:
        added = write_findings(flagged)
        store.write_report(REPORT_NAME, "\n".join(lines) + "\n")
        ARTIFACT.write_text(json.dumps({"at": now, "jobs": len(rows), "flagged": [f["id"] for f in flagged], "findings_added": added}) + "\n", encoding="utf-8")
    print(f"\nflagged: {len(flagged)}  findings added: {len(added)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
