"""Nightly portfolio advisor (macOS port of run-portfolio-advisor.ps1).

collect_portfolio_repos gathers the git facts of every repo under ~/code
read-only. The digest is split by scope and one tool-limited `claude -p` runs per
scope - work repos (under eventregistry/) under ~/.claude-work, the rest under
~/.claude-personal - each writing a report fragment; this script stores each fragment as
the Living note "Portfolio Advisor Nightly Report - <scope>" in the memory store (`mem`,
since 2026-10-13; it was a Notion page the model wrote) and merges them into state/reports/portfolio/latest.md (Odin, 2026-10-18; it was
~/.jarvis/portfolio-report.md). The report's layout is parsed by ~/.forge/brokkr/findings.py - do not
change the headings without changing that parser.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import date
from pathlib import Path

from .. import common as jc, store
from . import collect_portfolio_repos

CODE = jc.HOME / "code"
WORK_PREFIX = "eventregistry/"
DIGEST = jc.STATE_DIR / "portfolio-repos.md"
REPORT_NAME = "portfolio"
SCOPES = ("work", "personal")
BRAIN_DIR = jc.HOME / ".mind" / "state" / "memory-mirror" / "brain"
MEM = jc.HOME / ".local" / "bin" / "mem"
LABELS = {"work": "work (Event Registry)", "personal": "personal"}

def build_prompt(scope: str, digest: Path, report: Path) -> str:
    label = LABELS[scope]
    return f"""Portfolio advisor: analyze the {label} git repositories under {CODE} and produce a status report. This run covers the {scope} scope only; another run covers the other scope, and a program merges the two reports.

1. Read {digest}. The script that launched you collected it read-only a few minutes ago: every git repository under {CODE} (6 levels deep - work repos under eventregistry/, personal ones under personal/) with its branch and upstream tracking status, its uncommitted changes and how long the oldest has sat, the last 5 commits, the days since the last commit, and the open items in docs/TASKS.md. It is your only view of the repos - you have no shell and no access to them, by design.

2. Treat the digest as the facts. Flag uncommitted changes that have sat for a while, repos with no upstream tracking branch, branches ahead of or behind their upstream, dormant repos, and open TASKS.md items. A repo marked "git failed here" still gets a line saying so.

3. BRAIN lives in the local memory store; read its markdown copy: {BRAIN_DIR}/hub.md and whichever companion page(s) are relevant to tonight's findings for context on priorities and goals - work.md, devops.md, event-registry.md, graph-massivizer.md in the same folder. Use them only as read context to inform prioritization - never write to them.

4. You MUST call the Write tool to create {report}, OVERWRITING any previous version. Do NOT finish the task by printing the report as your final chat response instead of writing the file - a chat answer with no Write tool call is a failed run even if the exit code is 0. EVERY repo found in step 1 must be accounted for somewhere in the report - never silently drop one. Structure:
   - A header with the generation timestamp
   - A "## Cross-project priorities" section at the top: 3-6 NUMBERED items on what deserves attention first across the whole portfolio, grounded in BRAIN context where relevant. Each item starts with a bold one-sentence title, then the detail: `1. **Title sentence.** Detail.`
   - One "## <repo>" section per repo that has anything notable. The heading is the repo's path relative to {CODE} exactly as the digest writes it (for example `## personal/cmdpeek` or `## eventregistry/er-web`). Inside it, these four bullets in this order: `- **Last activity:** ...` (date, branch and upstream state), `- **Recently:** ...` (what was done, from the commits), `- **Next steps:** ...` (from TASKS.md, or "none recorded"), and `- **Issues:**` ALONE on its line followed by one indented bullet per issue - two spaces, a dash, then the issue (uncommitted changes sitting for a while, no upstream tracking branch, branches ahead of or behind their upstream, blockers). When a repo has no issues, write `- **Issues:** none` on one line instead.
   - A program reads the numbered Cross-project items and the indented Issues bullets every night, and it understands only this layout. Do not put issues on one line after "Issues:", do not use bullets instead of numbers for the priorities, and do not rename the headings.
   - A final "## Quiet / clean repos" section listing every remaining repo that has nothing notable (no uncommitted changes, in sync with its upstream, nothing in TASKS.md/handoff) as a single compact line each: repo name, last commit date, one-line note if useful (e.g. "clean, dormant"). Do not omit any repo from the report entirely - if it's quiet, it goes in this section instead of getting nothing.

5. The only FILE you may create or modify on disk is {report}, and the only files you can read are that report, the digest from step 1, the BRAIN pages from step 3, and any file a tool result is saved to for you - this run was started with permissions that refuse anything else. Do not look for a way around a refusal; mention it in your final text instead. Do not touch any BRAIN content.
"""


def store_in_memory(scope: str, fragment: Path, job) -> None:
    """Upsert the fragment as the Living note "Portfolio Advisor Nightly Report - <scope>".
    Summary: the bold titles of the cross-project priorities. A failure is logged, not fatal:
    the report file is the source of truth for the night."""
    title = f"Portfolio Advisor Nightly Report - {scope}"
    text = fragment.read_text(encoding="utf-8")
    _, priorities, _, _ = split_report(text)
    titles = [m.group(1).strip() for ln in priorities if (m := re.match(r"^\d+\.\s+\*\*(.+?)\*\*", ln))]
    summary = f"{date.today().isoformat()} {scope} scope: " + ("; ".join(titles[:4]) or "no cross-project priorities")
    q = subprocess.run([str(MEM), "sql", "SELECT id FROM notes WHERE title = '" + title.replace("'", "''")
                        + "' AND superseded_by IS NULL ORDER BY updated_at DESC LIMIT 1"], capture_output=True, text=True)
    try:
        found = json.loads(q.stdout or "[]")
    except ValueError:
        found = []
    if found:
        args = [str(MEM), "update", found[0]["id"], "--content-file", str(fragment), "--summary", summary,
                "--date", date.today().isoformat()]
    else:
        # --force: the per-scope reports share one summary template; the exact title is the dedupe
        args = [str(MEM), "add", "note", "--force", "--title", title, "--type", "project", "--scope", "general" if scope == "work" else "personal",
                "--summary", summary, "--content-file", str(fragment)]
    r = subprocess.run(args, capture_output=True, text=True)
    job.say(f"memory note {'updated' if found else 'created'}: {title}" if r.returncode == 0
            else f"WARN: memory note not stored ({(r.stdout + r.stderr).strip()[:200]})")


def scoped_digests(text: str) -> dict[str, str]:
    """The digest split by `## <repo>` section into the work and personal parts."""
    first = text.find("\n## ")
    preamble, body = (text, "") if first < 0 else (text[:first], text[first + 1:])
    parts: dict[str, list[str]] = {s: [] for s in SCOPES}
    for block in re.split(r"(?m)^(?=## )", body):
        if not block.strip():
            continue
        heading = block.splitlines()[0][3:].strip()
        parts["work" if heading.startswith(WORK_PREFIX) else "personal"].append(block)
    return {s: preamble.rstrip() + "\n\n" + "".join(parts[s]) for s in SCOPES}


def split_report(text: str) -> tuple[str, list[str], list[str], list[str]]:
    """(header, priority items, repo sections, quiet lines) of one report fragment."""
    header: list[str] = []
    priorities: list[str] = []
    sections: list[str] = []
    quiet: list[str] = []
    for block in re.split(r"(?m)^(?=## )", text):
        head = block.splitlines()[0].lower() if block.strip() else ""
        if not head.startswith("## "):
            header.append(block)
        elif head.startswith("## cross-project"):
            priorities += [ln for ln in block.splitlines()[1:] if ln.strip()]
        elif head.startswith("## quiet"):
            quiet += [ln for ln in block.splitlines()[1:] if ln.strip()]
        else:
            sections.append(block.rstrip() + "\n")
    return "".join(header).strip(), priorities, sections, quiet


def merge_reports(fragments: dict[str, Path], failed: list[str]) -> str:
    """One portfolio-report.md in the layout ~/.forge/brokkr/findings.py parses. Priorities are
    renumbered across scopes, work first."""
    header, priorities, sections, quiet = "", [], [], []
    for scope in SCOPES:
        path = fragments.get(scope)
        if path is None:
            continue
        h, p, s, q = split_report(path.read_text(encoding="utf-8"))
        header = header or h
        priorities += p
        sections += s
        quiet += q
    numbered, n = [], 0
    for ln in priorities:
        if re.match(r"^\d+\.\s", ln):
            n += 1
            ln = re.sub(r"^\d+\.", f"{n}.", ln, count=1)
        numbered.append(ln)
    out = [header or "# Portfolio report", ""]
    if failed:
        out += [f"> Missing this run: {', '.join(failed)} scope (its advisor run failed).", ""]
    out += ["## Cross-project priorities", "", *numbered, "", *sections, "", "## Quiet / clean repos", "", *quiet, ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    job = jc.Job("portfolio-advisor", "portfolio advisor")
    r = subprocess.run([jc.PYTHON, "-m", collect_portfolio_repos.__name__, "--out", str(DIGEST)],
                       capture_output=True, text=True, cwd=store.CODE)
    job.say((r.stdout + r.stderr).strip())
    if not DIGEST.exists() or DIGEST.stat().st_mtime < time.time() - 600:
        return job.fail("the repo digest was not written this run - not starting the model on stale input")
    if not jc.wait_for_api(job.log):
        return 1
    digests = scoped_digests(DIGEST.read_text(encoding="utf-8"))
    fragments: dict[str, Path] = {}
    failed: list[str] = []
    with jc.job_lock("portfolio-advisor", job.log) as held:
        if not held:
            return 1
        for scope in SCOPES:
            digest = jc.STATE_DIR / f"portfolio-repos.{scope}.md"
            fragment = jc.STATE_DIR / f"portfolio-report.{scope}.md"
            digest.write_text(digests[scope], encoding="utf-8")
            fragment.unlink(missing_ok=True)
            if "\n## " not in digests[scope]:
                job.say(f"no {scope} repositories found - skipping that scope")
                continue
            job.say(f"--- {scope} scope ---")
            code = jc.run_claude_job(
                build_prompt(scope, digest, fragment), job.log, f"portfolio-advisor-{scope}", surface="job:portfolio-advisor",
                budget_usd=2.25, tools="Read,Write,Edit", scope=scope, optional=True,
                allow=[f"Read({jc.rule_path(digest)})", f"Read({jc.rule_path(fragment)})",
                       f"Edit({jc.rule_path(fragment)})", f"Write({jc.rule_path(fragment)})",
                       f"Read({jc.rule_path(BRAIN_DIR)}/**)"])
            if job.assert_artifact(fragment, code, what=f"portfolio-report.{scope}.md") == 0:
                fragments[scope] = fragment
                store_in_memory(scope, fragment, job)
            else:
                failed.append(scope)
    if not fragments:
        return 1
    report = store.write_report(REPORT_NAME, merge_reports(fragments, failed))
    job.say(f"=== OK: merged {', '.join(fragments)} into {report}"
            + (f"; MISSING {', '.join(failed)}" if failed else "") + " ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
