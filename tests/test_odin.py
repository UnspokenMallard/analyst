"""Odin's tests: scratch ODIN_HOME and JARVIS_HOME, no model call. Run: ~/.analyst/.venv/bin/python tests/test_odin.py"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="odin-test-"))
os.environ["ODIN_HOME"] = str(TMP / "odin")
os.environ["JARVIS_HOME"] = str(TMP / "jarvis")
os.environ["MEMORY_DB"] = str(TMP / "memory.db")  # scratch Mimir: the jobs read the other parts' records
os.environ["MIMIR_OUTBOX"] = str(TMP / "outbox")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odin import cli, store  # noqa: E402
from odin.jobs import hud_audit, portfolio_advisor  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        FAILED.append(name)


def test_paths_are_scratch():
    check("paths: state and Jarvis's findings come from the environment",
          str(store.STATE).startswith(str(TMP)) and str(store.FINDINGS).startswith(str(TMP)))


def test_reports():
    dated = store.write_report("demo", "hello\n", day="2026-10-18")
    check("reports: <date>.md and latest.md", dated.name == "2026-10-18.md"
          and store.latest("demo").read_text() == "hello\n")


def test_propose_new():
    store.FINDINGS.parent.mkdir(parents=True, exist_ok=True)
    store.FINDINGS.write_text(json.dumps({"findings": [{"id": "filed", "status": "dismissed"}]}))
    first = store.propose_new([{"id": "filed"}, {"id": "a"}, {"id": "b"}])
    again = store.propose_new([{"id": "a"}, {"id": "c"}])
    ids = [p["id"] for p in store.load_json(store.PROPOSALS, {})["findings"]]
    check("proposals: a filed id (any status) or a proposed one is never proposed again",
          first == ["a", "b"] and again == ["c"] and ids == ["a", "b", "c"], (first, again, ids))


def test_hud_audit_proposals():
    store.FINDINGS.write_text(json.dumps({"findings": [
        {"id": hud_audit.finding_id("er-web", {"file": "package.json", "title": hud_audit.DEPS_TITLE}), "status": "open"}]}))
    found = [{"severity": "high", "title": "SQL injection", "file": "a.js"}, {"severity": "bogus", "title": "x"}]
    added = hud_audit.merge_findings("er-api", "nightly", found)
    again = hud_audit.merge_findings("er-api", "nightly", found[:1])
    props = {p["id"]: p for p in store.load_json(store.PROPOSALS, {})["findings"]}
    fid = hud_audit.finding_id("er-api", found[0])
    check("hud-audit: a finding is proposed once, a bad severity dropped, a second sighting only moves lastSeen",
          added == 1 and again == 0 and props[fid]["status"] == "open" and props[fid]["source"] == "nightly", props)
    # Dependencies: nothing found and nothing filed says nothing; a filed open one gets a resolved proposal.
    check("hud-audit: no advisories for a repo with no dependency finding proposes nothing",
          hud_audit.apply_deps("cmdpeek", []) == 0
          and hud_audit.finding_id("cmdpeek", {"file": "package.json", "title": hud_audit.DEPS_TITLE}) not in
          {p["id"] for p in store.load_json(store.PROPOSALS, {})["findings"]})
    hud_audit.apply_deps("er-web", [])
    dep = next(p for p in store.load_json(store.PROPOSALS, {})["findings"] if p.get("project") == "er-web")
    check("hud-audit: a filed dependency finding with no advisories now is proposed resolved, sync",
          dep["status"] == "resolved" and dep["sync"] is True and dep.get("lastSeen"), dep)
    hud_audit.apply_deps("er-web", [{"severity": "critical", "title": "lodash", "suggestion": "upgrade"}])
    dep = next(p for p in store.load_json(store.PROPOSALS, {})["findings"] if p.get("project") == "er-web")
    check("hud-audit: advisories reopen the dependency proposal with their detail",
          dep["status"] == "open" and dep["severity"] == "critical" and "lodash" in dep["detail"], dep)


def test_portfolio_merge():
    a, b = TMP / "w.md", TMP / "p.md"
    a.write_text("# Report\n\n## Cross-project priorities\n\n1. **W.** d\n\n## eventregistry/er-web\n- x\n\n## Quiet / clean repos\n\n- q1\n")
    b.write_text("# Report\n\n## Cross-project priorities\n\n1. **P.** d\n\n## personal/cmdpeek\n- y\n\n## Quiet / clean repos\n\n- q2\n")
    out = portfolio_advisor.merge_reports({"work": a, "personal": b}, [])
    check("portfolio: priorities renumbered across scopes, sections and quiet lines kept",
          "1. **W.**" in out and "2. **P.**" in out and "## personal/cmdpeek" in out and "- q2" in out, out)


def test_audit_prompt_cites_decisions():
    store.FINDINGS.write_text(json.dumps({"findings": [
        {"id": "r", "source": "nightly", "project": "er-api", "title": "Rate limit missing", "status": "dismissed",
         "dismissedAt": "2026-10-20T10:00:00Z", "dismissReason": "internal only"},
        {"id": "m", "source": "weekly", "project": "er-web", "title": "XSS in preview", "status": "resolved",
         "resolvedBy": "merged abc", "resolvedAt": "2026-10-21T10:00:00Z"},
        {"id": "o", "source": "remedy", "title": "not an audit", "status": "dismissed", "dismissReason": "x"}]}))
    text = hud_audit.past_decisions()
    check("hud-audit: the prompt cites rejects with the reason and recent accepts, only audit findings (A16)",
          "rejected: [er-api] Rate limit missing - his reason: internal only" in text
          and "accepted: [er-web] XSS in preview" in text and "not an audit" not in text, text)


def test_inputs_inlined_not_read():
    f = TMP / "in.txt"
    f.write_text("DIFF-BODY {x}", encoding="utf-8")
    nightly = hud_audit.nightly_prompt("r", TMP, "a..b", f, TMP / "o.json", False)
    weekly = hud_audit.weekly_prompt("r", TMP, f, TMP / "o.json")
    check("hud-audit: the input is in the prompt once and its path is not",
          all(p.count("DIFF-BODY {x}") == 1 and str(f) not in p for p in (nightly, weekly)))


def test_jobs_start_no_mcp_servers():
    from odin import common
    seen = {}
    real = common.bifrost.run_agent
    common.bifrost.run_agent = lambda *a, **k: seen.update(k) or {"code": 0}
    try:
        common.run_claude_job("p", TMP / "l.log", "j", "Read", 1.0)
    finally:
        common.bifrost.run_agent = real
    # The flag lives in Bifrost only: analyst passes none, and the command Bifrost builds still carries it once.
    args = common.bifrost.agent.command("claude", "sonnet", "s1", "Read", None, 1.0)
    check("jobs: claude starts with --strict-mcp-config",
          not seen.get("flags") and args.count("--strict-mcp-config") == 1, f"{seen.get('flags')} {args}")


def test_jobs_read_mimir():
    import time
    from odin._mimir import records as mr
    from odin.jobs import alert_review, job_review, weekly_changes
    sys.path.insert(0, str(Path.home() / ".mind" / "mimir"))
    import mem
    mr.use_local(mem.connect(shared=True))
    now = time.time()
    def incident(i, kind, opened, resolved=None, by=None):
        data = {"id": i, "kind": kind, "summary": f"s{i}", "severity": "warn", "opened_at": opened, "last_seen_at": opened,
                "hits": 1, "members": json.dumps([f"{kind}:{i}"]), "member_count": 1, "resolved_at": resolved,
                "resolved_by": by, "resolution": None, "evidence": None}
        mr.put("heimdall", "heimdall.incident", str(i), {**data, **({} if resolved else {"open": True, "open_kind": kind})})
    incident(1, "stuck-event", now - 3600, now - 60, "human")
    incident(2, "loop-crash", now - 30 * 86400, now - 29 * 86400, "resolver")
    incident(3, "stale", now - 120)
    mr.put("jarvis", "jarvis.job", "bad", {"enabled": True, "last_result": "FAILED: x"})
    mr.put("jarvis", "jarvis.job", "off", {"enabled": False, "last_result": "FAILED: y"})
    opened, closed, still_open = weekly_changes.incidents(now - 7 * 86400)
    check("weekly-changes: window, closed-by counts and open list come from the incident records",
          [k for k, _ in opened] == ["stuck-event", "stale"] and closed == [("stuck-event", "human", 1)]
          and [i[0] for i in still_open] == [3], f"{opened} {closed} {still_open}")
    check("weekly-changes: only enabled jobs with a bad last result", weekly_changes.failing_jobs() == [("bad", "FAILED: x")])
    for i in range(3):
        mr.append("jarvis", "jarvis.alert_writes", {"key": "k:a", "severity": "warn"}, at=now - 100 * i)
    got = alert_review.writes_per_key(now - 86400)
    check("alert-review: writes grouped per key", got["k:a"]["writes"] == 3 and got["k:a"]["severity"] == "warn", str(got))
    check("alert-review: the incident resolved by hand counts as engagement",
          alert_review.engaged_keys(now - 86400).get("stuck-event:1") == ["resolved incident 1"])
    mr.append("fafnir", "fafnir.job_call", {"job": "j", "cost_usd": 1.5}, at=now - 10)
    mr.append("fafnir", "fafnir.job_call", {"job": "j", "cost_usd": None}, at=now - 20)
    mr.append("fafnir", "fafnir.job_call", {"job": "other", "cost_usd": 7}, at=now - 30)
    check("job-review: spend sums one job's recorded cost", job_review.spend("j", now - 86400) == 1.5)


def test_cli():
    check("cli: an unknown job is refused with exit 2", cli.main(["nope"]) == 2)
    from odin._mimir import records as mr
    mr.use_local(None)
    os.environ["MIMIR_URL"] = "none"
    try:
        check("cli: a job exits 2 when Mimir is unreachable", cli.main(["weekly-changes"]) == 2)
    finally:
        del os.environ["MIMIR_URL"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print(f"{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all passed'}")
    sys.exit(1 if FAILED else 0)
