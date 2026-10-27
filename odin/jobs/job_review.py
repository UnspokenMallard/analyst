"""Weekly job-value review: which finding-raising jobs cost money and produce findings Anze never accepts.

Anze, 2026-10-15: audits only propose, nothing measured whether proposals land. For each job
whose output is HUD findings ([job_findings] in config.toml), over the last 30 days it counts the findings it
raised and how they ended (same rule as the HUD's Job value panel, hud/lib/jobvalue.js):
resolved, dismissed, or ignored (still open after IGNORED_DAYS). A job with at least
MIN_DECIDED decided-or-ignored findings and acceptance below MAX_ACCEPT percent becomes one
HUD finding on project claude-config proposing to pause or retune it. The finding id comes from
the job name, so a dismissed one stays dismissed. The report is Odin's state/reports/job-review/latest.md.

Every other LLM job with recorded spend (audit A32, 2026-10-24) is listed with its output signal: the
findings above, or how often Anze opened the report it pushes (the HUD's report-views.jsonl, audit A34).
A job whose pushed report nobody opened in the window, while it spent at least MIN_UNREAD_USD, is flagged
the same way. Reads are only counted from READS_SINCE, when the HUD started recording them.

A flagged job is proposed, not changed (audit A33, 2026-10-25): job-review commits `enabled = false` for it
to a local branch proposal/job-review-<job> in ~/.jarvis, cut from master in a throwaway worktree, and files
the finding as a HUD proposal on that branch. It never pushes, merges or edits the live config; Accept in the
HUD opens a chat on the branch. A branch that already exists is reused, so a rerun commits nothing new.

Every job with a Fafnir job_call row, not only the ones above, is also checked for failures over the last
FAIL_DAYS days (audit F5): 2 or more days with a failed run (`ok` = 0), or failed runs that cost at least
MIN_WASTED_USD with no successful run in the window, becomes a HUD finding on claude-config (no config branch:
a failing job needs a fix, not a pause).

Read-only for the daemon's state: it edits no config and pauses nothing.
Usage: analyst job-review [--days N] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .. import store
from .._mimir import records as mr

JARVIS = store.JARVIS
FINDINGS = store.FINDINGS  # read only: the outcomes of each job's filed findings
REPORT_NAME = "job-review"
ARTIFACT = store.STATE / "job-review.json"
CONFIG = JARVIS / "config.toml"
IGNORED_DAYS = 14
MIN_DECIDED = 5
MAX_ACCEPT = 10
VIEWS = JARVIS / "state" / "hud" / "report-views.jsonl"
READS_SINCE = datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp()
MIN_UNREAD_USD = 2.0
FAIL_DAYS = 7
MIN_FAIL_DAYS = 2
MIN_WASTED_USD = 1.0


def job_sources() -> dict[str, str]:
    """Job name -> finding source, from [job_findings] in config.toml (also read by hud/lib/jobvalue.js)."""
    with CONFIG.open("rb") as f:
        return tomllib.load(f).get("job_findings", {})


def pushed_reports(jobs: list[str]) -> dict[str, str]:
    """Job name -> the report file a report-push job sends for it."""
    with CONFIG.open("rb") as f:
        cfg = tomllib.load(f)
    paths = [r["path"] for j in cfg.get("jobs", []) if j.get("kind") == "report-push"
             for r in (j.get("payload") or {}).get("reports", []) if r.get("path")]
    out = {}
    # shortcut: a report belongs to the longest job name in its path; name a job in the payload if one ever misfiles.
    for p in paths:
        owner = max((j for j in jobs if j in p), key=len, default=None)
        if owner:
            out[owner] = p
    return out


def report_reads(since: float) -> dict[str, int]:
    """Report path -> times Anze opened it from its notification in the window."""
    reads: dict[str, int] = {}
    try:
        lines = VIEWS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return reads
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if parse_ts(d.get("at", "")) >= since:
            reads[d.get("path", "")] = reads.get(d.get("path", ""), 0) + 1
    return reads


def all_spend(since: float) -> dict[str, float]:
    """Job -> Fafnir's recorded cost over the window, for every job that has one."""
    groups = mr.agg("sum", stream="fafnir.job_call", field="cost_usd", by="job", since=since, source="fafnir") or {}
    return {job: round(usd or 0, 2) for job, usd in groups.items()}


def job_calls(since: float) -> list[dict]:
    """Fafnir's job_call rows since `since`, each with `at`. shortcut: 5000 rows (days of calls), page it if that changes."""
    return [{**r["data"], "at": r["at"]} for r in mr.query(stream="fafnir.job_call", since=since, limit=5000, source="fafnir")]


def failing_jobs(rows: list[dict], held: set[str]) -> dict[str, dict]:
    """Job -> {days, failed, ok, wasted_usd} for each unpaused job with failed runs on MIN_FAIL_DAYS+ days,
    or failed runs worth MIN_WASTED_USD+ and no successful run. A run's retries count as one day's failure."""
    per: dict[str, dict] = {}
    for r in rows:
        j = per.setdefault(r.get("job", ""), {"day_set": set(), "failed": 0, "ok": 0, "wasted_usd": 0.0})
        if r.get("ok"):
            j["ok"] += 1
        else:
            j["failed"] += 1
            j["day_set"].add(datetime.fromtimestamp(r.get("at", 0), timezone.utc).date())
            j["wasted_usd"] += r.get("cost_usd") or 0
    out = {}
    for job, j in per.items():
        j["days"], j["wasted_usd"] = len(j.pop("day_set")), round(j["wasted_usd"], 2)
        if job and job not in held and (j["days"] >= MIN_FAIL_DAYS or (j["wasted_usd"] >= MIN_WASTED_USD and not j["ok"])):
            out[job] = j
    return out


def failing_finding(job: str, j: dict) -> dict:
    f = finding_for(job, {"acceptance": 0, "raised": 0, "resolved": 0, "dismissed": 0, "ignored": 0}, j["wasted_usd"], FAIL_DAYS)
    f.update(id="jobfail-" + hashlib.sha1(job.encode()).hexdigest()[:10], kind="job-failing", file="",
             title=f"Job [{job}] failed on {j['days']} day(s) in the last {FAIL_DAYS} (${j['wasted_usd']} spent on failed runs).",
             detail=f"{j['failed']} failed and {j['ok']} successful runs in Fafnir's job_call records. "
                    "See ~/.analyst/state/reports/job-review/latest.md.",
             suggestion="Read the job's log for why it fails; fix the cause or lengthen its cap. The job is not changed automatically.")
    return f


def unread_finding(job: str, report: str, usd: float, days: int) -> dict:
    f = finding_for(job, {"acceptance": 0, "raised": 0, "resolved": 0, "dismissed": 0, "ignored": 0}, usd, days)
    f.update(id="jobvalue-unread-" + hashlib.sha1(job.encode()).hexdigest()[:10],
             title=f"Job [{job}] spent ${usd} over {days} days on a report nobody opened.",
             detail=f"Its report {report} was pushed to the phone and never opened from the notification in the window. "
                    "See ~/.analyst/state/reports/job-review/latest.md.",
             suggestion="Pick one: stop pushing the report, pause the job, or lengthen its schedule. "
                        "The job is not changed automatically.")
    return f


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


def spend(job: str, since: float) -> float:
    """Fafnir's recorded cost of the job's runs (its `fafnir.job_call` stream in Mimir)."""
    total = mr.agg("sum", stream="fafnir.job_call", field="cost_usd", where="job:" + json.dumps(job), since=since, source="fafnir")
    return round(total or 0, 2)


def finding_for(job: str, o: dict, usd: float, days: int) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "id": "jobvalue-" + hashlib.sha1(job.encode()).hexdigest()[:10],
        "project": "claude-config",
        "severity": "low",
        "kind": "job-value",
        "job": job,
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


def disable_edit(text: str, job: str) -> str | None:
    """config.toml with the job's `enabled = true` set to false; None when the job has no such line."""
    blocks = re.split(r"(?m)^(?=\[\[jobs\]\])", text)
    for i, block in enumerate(blocks):
        if re.search(rf'(?m)^name = "{re.escape(job)}"$', block):
            new = re.sub(r"(?m)^enabled = true$", "enabled = false", block, count=1)
            if new == block:
                return None
            blocks[i] = new
            return "".join(blocks)
    return None


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd or JARVIS), *args], capture_output=True, text=True, timeout=60)


def propose_branch(job: str) -> str | None:
    """The local branch that disables `job` in config.toml, made once from master; None when it cannot be made."""
    branch = f"proposal/job-review-{job}"
    if _git("rev-parse", "--verify", "-q", f"refs/heads/{branch}").returncode == 0:
        return branch
    shown = _git("show", "master:config.toml")
    new = disable_edit(shown.stdout, job) if shown.returncode == 0 else None
    if new is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt"
        if _git("worktree", "add", "-q", "-b", branch, str(wt), "master").returncode != 0:
            return None
        try:
            (wt / "config.toml").write_text(new, encoding="utf-8")
            ok = _git("commit", "-q", "-m", f"Disable the {job} job, which job-review flagged", "--", "config.toml", cwd=wt).returncode == 0
        finally:
            _git("worktree", "remove", "--force", str(wt))
    if not ok:
        _git("branch", "-D", branch)  # only the branch this call just made
        return None
    return branch


def as_proposal(f: dict, job: str, branch: str) -> dict:
    return {**f, "kind": "proposal", "project": "jarvis", "branch": branch, "why": f["title"], "confidence": 0.6,
            "detail": f"Sets enabled = false for [{job}] in config.toml. {f['detail']}",
            "notChecked": ["whether another job or report depends on this one"]}


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
    for job, source in job_sources().items():
        o, usd = outcomes(findings, source, since, now), spend(job, since)
        rows.append((job, usd, o))
        if job in held:
            continue
        if o["decided"] >= MIN_DECIDED and o["acceptance"] is not None and o["acceptance"] < MAX_ACCEPT:
            flagged.append(finding_for(job, o, usd, args.days))

    spent = all_spend(since)
    reports = pushed_reports(list(spent))
    reads = report_reads(since)
    covered = since >= READS_SINCE
    others = []
    for job in sorted(set(spent) - set(job_sources()), key=lambda j: -spent[j]):
        rep = reports.get(job)
        signal = f"report opened {reads.get(rep, 0)}x" if rep else "no output signal"
        if rep and not covered:
            signal += " (reads counted from 2026-10-25)"
        others.append((job, spent[job], signal))
        if rep and covered and job not in held and not reads.get(rep) and spent[job] >= MIN_UNREAD_USD:
            flagged.append(unread_finding(job, rep, spent[job], args.days))

    calls = job_calls(now - FAIL_DAYS * 86400)
    failing = failing_jobs(calls, held)
    flagged += [failing_finding(job, j) for job, j in sorted(failing.items())]
    all_jobs = set(job_sources()) | set(spent) | {r.get("job") for r in calls}

    lines = [f"# Job review ({datetime.now():%Y-%m-%d})", "",
             f"Window {args.days} days. Flag: at least {MIN_DECIDED} decided-or-ignored findings and acceptance under {MAX_ACCEPT}%.", "",
             "| job | spend | raised | resolved | dismissed | ignored | acceptance |", "|---|---|---|---|---|---|---|"]
    for job, usd, o in rows:
        acc = "n/a" if o["acceptance"] is None else f"{o['acceptance']}%"
        if job in held:
            acc += " (paused, not flagged)"
        lines.append(f"| {job} | ${usd} | {o['raised']} | {o['resolved']} | {o['dismissed']} | {o['ignored']} | {acc} |")
    lines += ["", "Every other LLM job with recorded spend:", "", "| job | spend | output |", "|---|---|---|"]
    lines += [f"| {job} | ${usd} | {signal} |" for job, usd, signal in others]
    lines += ["", f"Failing jobs (failed runs on {MIN_FAIL_DAYS}+ of the last {FAIL_DAYS} days, or ${MIN_WASTED_USD} wasted with no success):", ""]
    lines += [f"- {job}: failed on {j['days']} day(s), {j['failed']} failed / {j['ok']} ok runs, ${j['wasted_usd']} on failed runs"
              for job, j in sorted(failing.items())] or ["- none"]
    print("\n".join(lines))
    added: list[str] = []
    if not args.dry_run:
        for i, f in enumerate(flagged):
            if f["kind"] != "job-failing" and (branch := propose_branch(f["job"])):
                flagged[i] = as_proposal(f, f["job"], branch)
        added = write_findings(flagged)
        store.write_report(REPORT_NAME, "\n".join(lines) + "\n")
        ARTIFACT.write_text(json.dumps({"at": now, "jobs": len(all_jobs), "flagged": [f["id"] for f in flagged], "findings_added": added}) + "\n", encoding="utf-8")
    print(f"\nflagged: {len(flagged)}  findings added: {len(added)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
