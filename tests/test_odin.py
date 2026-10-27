"""Odin's tests: scratch ODIN_HOME and JARVIS_HOME, no model call. Run: ~/.analyst/.venv/bin/python -m unittest discover -s tests"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="odin-test-"))
os.environ["ODIN_HOME"] = str(TMP / "odin")
os.environ["JARVIS_HOME"] = str(TMP / "jarvis")
os.environ["MEMORY_DB"] = str(TMP / "memory.db")  # scratch Mimir: the jobs read the other parts' records
os.environ["MIMIR_OUTBOX"] = str(TMP / "outbox")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odin import cli, store  # noqa: E402
from odin.jobs import hud_audit, portfolio_advisor  # noqa: E402


class TestOdin(unittest.TestCase):
    def setUp(self):
        for f in (store.PROPOSALS, store.FINDINGS, hud_audit.AUDITS):  # scratch files; tests run in any order
            f.parent.mkdir(parents=True, exist_ok=True)
            f.unlink(missing_ok=True)

    def check(self, name, ok, detail=""):
        self.assertTrue(ok, f"{name}  {detail}")

    def test_paths_are_scratch(self):
        self.check("paths: state and Jarvis's findings come from the environment",
              str(store.STATE).startswith(str(TMP)) and str(store.FINDINGS).startswith(str(TMP)))

    def test_reports(self):
        dated = store.write_report("demo", "hello\n", day="2026-10-18")
        self.check("reports: <date>.md and latest.md", dated.name == "2026-10-18.md"
              and store.latest("demo").read_text() == "hello\n")

    def test_propose_new(self):
        store.FINDINGS.parent.mkdir(parents=True, exist_ok=True)
        store.FINDINGS.write_text(json.dumps({"findings": [{"id": "filed", "status": "dismissed"}]}))
        first = store.propose_new([{"id": "filed"}, {"id": "a"}, {"id": "b"}])
        again = store.propose_new([{"id": "a"}, {"id": "c"}])
        ids = [p["id"] for p in store.load_json(store.PROPOSALS, {})["findings"]]
        self.check("proposals: a filed id (any status) or a proposed one is never proposed again",
              first == ["a", "b"] and again == ["c"] and ids == ["a", "b", "c"], (first, again, ids))

    def test_hud_audit_private_note(self):
        self.check("hud-audit: the private-repo rule is in the prompt for er-api and er-web only",
              all("PRIVATE" in hud_audit.private_note(n) for n in ("er-api", "er-web")) and hud_audit.private_note("jarvis") == "")

    def test_hud_audit_proposals(self):
        store.FINDINGS.write_text(json.dumps({"findings": [
            {"id": hud_audit.finding_id("er-web", {"file": "package.json", "title": hud_audit.DEPS_TITLE}), "status": "open"}]}))
        found = [{"severity": "high", "title": "SQL injection", "file": "a.js"}, {"severity": "bogus", "title": "x"}]
        added = hud_audit.merge_findings("er-api", "nightly", found)
        again = hud_audit.merge_findings("er-api", "nightly", found[:1])
        props = {p["id"]: p for p in store.load_json(store.PROPOSALS, {})["findings"]}
        fid = hud_audit.finding_id("er-api", found[0])
        self.check("hud-audit: a finding is proposed once, a bad severity dropped, a second sighting only moves lastSeen",
              added == 1 and again == 0 and props[fid]["status"] == "open" and props[fid]["source"] == "nightly", props)
        # Dependencies: nothing found and nothing filed says nothing; a filed open one gets a resolved proposal.
        self.check("hud-audit: no advisories for a repo with no dependency finding proposes nothing",
              hud_audit.apply_deps("cmdpeek", []) == 0
              and hud_audit.finding_id("cmdpeek", {"file": "package.json", "title": hud_audit.DEPS_TITLE}) not in
              {p["id"] for p in store.load_json(store.PROPOSALS, {})["findings"]})
        hud_audit.apply_deps("er-web", [])
        dep = next(p for p in store.load_json(store.PROPOSALS, {})["findings"] if p.get("project") == "er-web")
        self.check("hud-audit: a filed dependency finding with no advisories now is proposed resolved, sync",
              dep["status"] == "resolved" and dep["sync"] is True and dep.get("lastSeen"), dep)
        hud_audit.apply_deps("er-web", [{"severity": "critical", "title": "lodash", "suggestion": "upgrade"}])
        dep = next(p for p in store.load_json(store.PROPOSALS, {})["findings"] if p.get("project") == "er-web")
        self.check("hud-audit: advisories reopen the dependency proposal with their detail",
              dep["status"] == "open" and dep["severity"] == "critical" and "lodash" in dep["detail"], dep)

    def test_portfolio_merge(self):
        a, b = TMP / "w.md", TMP / "p.md"
        a.write_text("# Report\n\n## Cross-project priorities\n\n1. **W.** d\n\n## eventregistry/er-web\n- x\n\n## Quiet / clean repos\n\n- q1\n")
        b.write_text("# Report\n\n## Cross-project priorities\n\n1. **P.** d\n\n## personal/cmdpeek\n- y\n\n## Quiet / clean repos\n\n- q2\n")
        out = portfolio_advisor.merge_reports({"work": a, "personal": b}, [])
        self.check("portfolio: priorities renumbered across scopes, sections and quiet lines kept",
              "1. **W.**" in out and "2. **P.**" in out and "## personal/cmdpeek" in out and "- q2" in out, out)

    def test_audit_prompt_cites_decisions(self):
        store.FINDINGS.write_text(json.dumps({"findings": [
            {"id": "r", "source": "nightly", "project": "er-api", "title": "Rate limit missing", "status": "dismissed",
             "dismissedAt": "2026-10-20T10:00:00Z", "dismissReason": "internal only"},
            {"id": "m", "source": "weekly", "project": "er-web", "title": "XSS in preview", "status": "resolved",
             "resolvedBy": "merged abc", "resolvedAt": "2026-10-21T10:00:00Z"},
            {"id": "o", "source": "remedy", "title": "not an audit", "status": "dismissed", "dismissReason": "x"}]}))
        text = hud_audit.past_decisions()
        self.check("hud-audit: the prompt cites rejects with the reason and recent accepts, only audit findings (A16)",
              "rejected: [er-api] Rate limit missing - his reason: internal only" in text
              and "accepted: [er-web] XSS in preview" in text and "not an audit" not in text, text)

    def test_inputs_inlined_not_read(self):
        f = TMP / "in.txt"
        f.write_text("DIFF-BODY {x}", encoding="utf-8")
        nightly = hud_audit.nightly_prompt("r", TMP, "a..b", f, TMP / "o.json", False)
        weekly = hud_audit.weekly_prompt("r", TMP, f, TMP / "o.json")
        self.check("hud-audit: the input is in the prompt once and its path is not",
              all(p.count("DIFF-BODY {x}") == 1 and str(f) not in p for p in (nightly, weekly)))

    def test_audit_keeps_partial_findings(self):
        from odin import common
        out = TMP / "partial.json"
        real = common.run_claude_job
        common.run_claude_job = lambda *a, **k: out.write_text('{"findings": [{"title": "x"}]}') and 1
        try:
            job = common.Job("hud-audit-test", "test")
            found = hud_audit.run_model(job, "r", TMP, "nightly", "p", TMP / "in.txt", out)
        finally:
            common.run_claude_job = real
        self.check("hud-audit: a run cut off by its budget keeps the findings it wrote", found == [{"title": "x"}])

    def test_jobs_start_no_mcp_servers(self):
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
        self.check("jobs: claude starts with --strict-mcp-config",
              not seen.get("flags") and args.count("--strict-mcp-config") == 1, f"{seen.get('flags')} {args}")

    def test_jobs_read_mimir(self):
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
        self.check("weekly-changes: window, closed-by counts and open list come from the incident records",
              [k for k, _ in opened] == ["stuck-event", "stale"] and closed == [("stuck-event", "human", 1)]
              and [i[0] for i in still_open] == [3], f"{opened} {closed} {still_open}")
        self.check("weekly-changes: only enabled jobs with a bad last result", weekly_changes.failing_jobs() == [("bad", "FAILED: x")])
        for i in range(3):
            mr.append("jarvis", "jarvis.alert_writes", {"key": "k:a", "severity": "warn"}, at=now - 100 * i)
        got = alert_review.writes_per_key(now - 86400)
        self.check("alert-review: writes grouped per key", got["k:a"]["writes"] == 3 and got["k:a"]["severity"] == "warn", str(got))
        self.check("alert-review: the incident resolved by hand counts as engagement",
              alert_review.engaged_keys(now - 86400).get("stuck-event:1") == ["resolved incident 1"])
        mr.append("fafnir", "fafnir.job_call", {"job": "j", "cost_usd": 1.5}, at=now - 10)
        mr.append("fafnir", "fafnir.job_call", {"job": "j", "cost_usd": None}, at=now - 20)
        mr.append("fafnir", "fafnir.job_call", {"job": "other", "cost_usd": 7}, at=now - 30)
        self.check("job-review: spend sums one job's recorded cost", job_review.spend("j", now - 86400) == 1.5)
        self.check("job-review: every job's spend in one grouped query", job_review.all_spend(now - 86400) == {"j": 1.5, "other": 7})
        cfg, views = TMP / "jr-config.toml", TMP / "jr-views.jsonl"
        cfg.write_text('[[jobs]]\nkind = "report-push"\npayload = { reports = [ { path = "/r/weekly-introspect/latest.md" } ] }\n')
        views.write_text(json.dumps({"path": "/r/weekly-introspect/latest.md", "at": "2026-10-26T08:00:00Z"}) + "\nbad\n")
        real = job_review.CONFIG, job_review.VIEWS
        job_review.CONFIG, job_review.VIEWS = cfg, views
        try:
            self.check("job-review: a pushed report maps to the longest job name in its path",
                  job_review.pushed_reports(["weekly", "weekly-introspect"]) == {"weekly-introspect": "/r/weekly-introspect/latest.md"})
            self.check("job-review: report reads are counted inside the window only",
                  job_review.report_reads(job_review.parse_ts("2026-10-25T00:00:00Z")) == {"/r/weekly-introspect/latest.md": 1}
                  and job_review.report_reads(job_review.parse_ts("2026-10-27T00:00:00Z")) == {})
        finally:
            job_review.CONFIG, job_review.VIEWS = real

    def test_job_review_proposes_branch(self):
        import subprocess
        from odin.jobs import job_review
        repo = TMP / "jr-repo"
        subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
        (repo / "config.toml").write_text('[[jobs]]\nname = "a"\nenabled = true\n\n[[jobs]]\nname = "b"\nenabled = true\n')
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(git + ["add", "config.toml"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
        real = job_review.JARVIS
        job_review.JARVIS = repo
        os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        try:
            branch = job_review.propose_branch("b")
            again = job_review.propose_branch("b")
            missing = job_review.propose_branch("nope")
        finally:
            job_review.JARVIS = real
        shown = subprocess.run(git + ["show", f"{branch}:config.toml"], capture_output=True, text=True).stdout
        self.check("job-review: a flagged job gets a branch that disables only it, reused on a rerun",
              branch == again == "proposal/job-review-b" and shown.endswith('name = "b"\nenabled = false\n')
              and 'name = "a"\nenabled = true' in shown and missing is None, shown)
        self.check("job-review: master and the live checkout are untouched",
              "enabled = false" not in (repo / "config.toml").read_text()
              and subprocess.run(git + ["worktree", "list"], capture_output=True, text=True).stdout.count("\n") == 1)
        p = job_review.as_proposal(job_review.finding_for("b", {"acceptance": 0, "raised": 1, "resolved": 0, "dismissed": 1, "ignored": 0}, 3, 30), "b", branch)
        self.check("job-review: the proposal is on the jarvis project with its branch", p["kind"] == "proposal" and p["project"] == "jarvis" and p["branch"] == branch)

    def test_cli(self):
        self.check("cli: an unknown job is refused with exit 2", cli.main(["nope"]) == 2)
        from odin._mimir import records as mr
        mr.use_local(None)
        os.environ["MIMIR_URL"] = "none"
        try:
            self.check("cli: a job exits 2 when Mimir is unreachable", cli.main(["weekly-changes"]) == 2)
        finally:
            del os.environ["MIMIR_URL"]

    def test_audit_failure_stops_paying(self):
        import contextlib
        import subprocess
        from odin import common
        repo = TMP / "failrepo"
        repo.mkdir()
        g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()  # noqa: E731
        g("init", "-q")
        for i in range(3):
            (repo / "f").write_text(str(i))
            g("add", "f")
            g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", f"c{i}")
        saved = (hud_audit.projects, common.wait_for_api, common.job_budget, common.job_lock, hud_audit.run_model)
        hud_audit.projects = lambda: [("failrepo", repo)]
        common.wait_for_api = lambda log: True
        common.job_budget = lambda scope, optional=False: (0, "")
        common.job_lock = lambda name, log: contextlib.nullcontext(True)
        hud_audit.run_model = lambda *a: None  # every run ends without a usable findings file
        try:
            state = json.loads(hud_audit.AUDITS.read_text()) if hud_audit.AUDITS.exists() else {}
            state["failrepo"] = {"lastSha": g("rev-parse", "HEAD~2")}
            hud_audit.AUDITS.parent.mkdir(parents=True, exist_ok=True)
            hud_audit.AUDITS.write_text(json.dumps(state))
            first = hud_audit.audit("nightly")
            after_one = json.loads(hud_audit.AUDITS.read_text())["failrepo"]
            second = hud_audit.audit("nightly")
            after_two = json.loads(hud_audit.AUDITS.read_text())["failrepo"]
        finally:
            hud_audit.projects, common.wait_for_api, common.job_budget, common.job_lock, hud_audit.run_model = saved
        self.check("hud-audit: a failed run exits 86 so Jarvis does not retry a paid run", first == second == 86, f"{first} {second}")
        self.check("hud-audit: a range that failed twice is skipped",
              after_one["failStreak"] == 1 and after_two["lastSha"] == g("rev-parse", "HEAD") and after_two["failStreak"] == 0,
              f"{after_one} {after_two}")

    def test_weekly_activity_fails_on_nonzero_exit_with_fresh_file(self):
        import contextlib
        from unittest import mock
        from odin import common
        from odin.jobs import weekly_activity as wa
        wa.DIGEST.parent.mkdir(parents=True, exist_ok=True)
        wa.DIGEST.write_text("digest")
        def run(code):
            def fake(prompt, *a, **k):
                (store.report_dir(wa.REPORT_NAME) / f"{wa.datetime.now():%Y-%m-%d}.md").write_text("Last week:\n- x\n")
                return code
            with mock.patch.object(wa.subprocess, "run"), mock.patch.object(common, "wait_for_api", return_value=True), \
                 mock.patch.object(common, "job_lock", lambda *a: contextlib.nullcontext(True)), \
                 mock.patch.object(common, "run_claude_job", fake):
                return wa.main([])
        self.check("weekly-activity: exit 1 with a fresh file is a failure", run(1) == 1)
        self.check("weekly-activity: exit 0 with a fresh file passes", run(0) == 0)


if __name__ == "__main__":
    unittest.main()
