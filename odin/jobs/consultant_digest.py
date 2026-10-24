"""Weekly consultant digest (macOS port of run-consultant-digest.ps1).

Reads what other jobs already wrote this week and synthesizes one prioritized
"needs a human's attention" report. Refreshes the checkpoint first so the
daemon-health section is from this morning.
"""
from __future__ import annotations

import subprocess

from .. import common as jc, store

REPORT_NAME = "consultant"
DIGEST = store.report_dir(REPORT_NAME) / "draft.md"  # the model writes here; main() files it as <date>.md + latest.md
J = jc.JARVIS
JARVIS_PYTHON = J / ".venv" / "bin" / "python"  # checkpoint.py is Jarvis's and runs on its interpreter
MIRROR = jc.HOME / ".mind" / "state" / "memory-mirror"

PROMPT = f"""Weekly consultant digest. This is an UNATTENDED scheduled run - do NOT ask any
clarifying questions, and do NOT edit, delete, or write to anything except the
one output file named below. This job produces no new data collection of its
own - it reads what other jobs already wrote this week and synthesizes it into
one prioritized "what needs a human's attention" report across four domains:
repo/code health, project/task state, infrastructure health, and personal/life
priorities.

Sources (read only, skip silently and note the gap if a source is missing or
stale - do not fail the run over one missing input):

1. Repo/code health: {store.latest('portfolio')}
2. Infrastructure health (this machine is a Mac Studio since 2026-09-28; the
   Windows-only checks of the NUC - docker-runaway, wslconfig, scoop shims - are
   gone):
   - ~/.sentinel/state/checks/host-cpu-load.json
   - ~/.sentinel/state/checks/paths.json
   - {J}/checkpoints/latest.md (daemon's own health: soak gate verdict, job
     failures, overdue jobs, alert count)
   - ~/.sentinel/state/checks/backup.json (Mac backup freshness: last run, NUC copy,
     offsite copy, last restore drill; "problems" lists what is wrong).
     No offsite copy is Anze's decision (postponed indefinitely): never
     report a missing or unconfirmed offsite copy, as a problem or a blind spot)
   - ~/.sentinel/state/checks/expiry.json (credential expiry dates; "problems" lists
     anything within 14 days or past)
3a. Project/task state, local: {J}/state/repo-sweep.json (uncommitted files,
   commits not on any remote, branches idle over 30 days, per repo) and
   {J}/reports/asana/latest.md (lines starting "- **CRITICAL**" are the Asana
   tasks that CLAUDE.md judges critical; quote them, do not re-judge them)
3b. Project/task state, memory: {MIRROR}/INDEX.md lists the
   Living project notes (newest first) with their files under
   {MIRROR}/project-notes/ - read the ones dated in the last
   30 days; these are the status docs meant to be checked back on.
4. Personal/life priorities: read the BRAIN hub
   {MIRROR}/brain/hub.md and skim its companion pages in the
   same folder for anything time-sensitive or overdue, read-only, no deep
   re-analysis - the portfolio-advisor step already did the repo-level
   cross-reference against BRAIN, don't repeat that work here.

Write your findings to {DIGEST}
(OVERWRITING any previous version):
- A short header with the generation timestamp.
- One "Top priorities this week" section: 3-7 bullets, ranked, spanning
  whichever domains actually have something worth flagging. Every bullet
  must be traceable to one of the sources above - do not invent findings.
  If a domain has nothing new since last week, omit it rather than padding.
- One short section per domain with anything notable beyond the top
  priorities, or "nothing new" if genuinely quiet.
- A closing note on any source that was missing, stale (>10 days old), or
  errored, so a human knows the digest's blind spots for this run.

You MUST call the Write tool to create the digest file. Finishing by printing
findings as your final chat response instead of writing the file is a failed
run even if the exit code is 0. The only file you may create or modify is
{DIGEST} - this is a read-and-synthesize job, not a write-anywhere-else job.
"""


def main(argv: list[str] | None = None) -> int:
    job = jc.Job("consultant-digest", "consultant digest")
    r = subprocess.run([str(JARVIS_PYTHON), str(J / "checkpoint.py"), "--quiet"], capture_output=True)
    job.say(f"checkpoint refreshed before reading it: exit={r.returncode}")
    if not jc.wait_for_api(job.log):
        return 1
    with jc.job_lock("consultant-digest", job.log) as held:
        if not held:
            return 1
        code = jc.run_claude_job(
            PROMPT, job.log, "consultant-digest", budget_usd=1.25,
            tools="Read,Glob,Write",
            allow=[f"Read({jc.rule_path(J)}/**)", f"Read({jc.rule_path(store.REPORTS)}/**)", f"Edit({jc.rule_path(DIGEST)})"])
    if job.assert_artifact(DIGEST, code) != 0:
        return 1
    store.write_report(REPORT_NAME, DIGEST.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
