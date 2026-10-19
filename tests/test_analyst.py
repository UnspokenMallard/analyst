"""Analyst's tests: scratch ANALYST_HOME and JARVIS_HOME, no model call. Run: ~/.analyst/.venv/bin/python tests/test_analyst.py"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="analyst-test-"))
os.environ["ANALYST_HOME"] = str(TMP / "analyst")
os.environ["JARVIS_HOME"] = str(TMP / "jarvis")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analyst import cli, store  # noqa: E402
from analyst.jobs import hud_audit, portfolio_advisor  # noqa: E402

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


def test_inputs_inlined_not_read():
    f = TMP / "in.txt"
    f.write_text("DIFF-BODY {x}", encoding="utf-8")
    nightly = hud_audit.nightly_prompt("r", TMP, "a..b", f, TMP / "o.json", False)
    weekly = hud_audit.weekly_prompt("r", TMP, f, TMP / "o.json")
    check("hud-audit: the input is in the prompt once and its path is not",
          all(p.count("DIFF-BODY {x}") == 1 and str(f) not in p for p in (nightly, weekly)))


def test_jobs_start_no_mcp_servers():
    from analyst import common
    seen = {}
    real = common.gateway.run_agent
    common.gateway.run_agent = lambda *a, **k: seen.update(k) or {"code": 0}
    try:
        common.run_claude_job("p", TMP / "l.log", "j", "Read", 1.0)
    finally:
        common.gateway.run_agent = real
    check("jobs: claude starts with --strict-mcp-config", seen.get("flags") == ["--strict-mcp-config"], str(seen.get("flags")))


def test_cli():
    check("cli: an unknown job is refused with exit 2", cli.main(["nope"]) == 2)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print(f"{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all passed'}")
    sys.exit(1 if FAILED else 0)
