# Next prompt: Analyst

**Built and cut over 2026-10-18 (DONE).** The report and review jobs run in `~/.analyst`, triggered by Jarvis;
`DESIGN.md` "As built" has the layout, the job table, the readers repointed and what differs from the design.

## When to fire this

The first three rows run by themselves: Jarvis's hourly `checkups` job (`analyst-first-night` after 2026-10-19 09:30,
`analyst-sunday` after 2026-10-25 08:15) writes `~/.jarvis/reports/checkups/<id>.md` and alerts on FAIL. Earliest-useful dates, not deadlines; being late costs nothing (a broken job shows up as a failed Jarvis job and its
alert, and the old Jarvis files are untouched).

| When | Step | Waits on |
|---|---|---|
| 2026-10-19 morning (after 08:00) | first-night check (prompt B plus the list under it) | hud-audit-nightly 03:30, portfolio-advisor 04:15 |
| 2026-10-19 (after 09:15) | Monday check: weekly-changes 07:20, weekly-activity 07:45, weekly-activity-post 08:45 wrote the Notion page | the first Monday |
| 2026-10-25 (after 08:00) | Sunday check: hud-audit-weekly 05:00, consultant-digest 06:00 and its push 07:30, the three reviews 07:00-07:10 | the first Sunday |
| when Anze says so | move the memory jobs to Mind (`weekly-introspect`, `nightly-reflection`, `lesson-candidates`), each in its own commit | Anze; Jarvis reminder of 2026-10-30 compares Mind's capture drafts with the reflection |
| when Anze says so | move `issue-triage` to Forge, `dep-rehearsal` and `commit-audit` to Sentinel, `token-report` and `usage-digest` to Budget (DESIGN "Not Analyst") | Anze |
| when Anze confirms | delete the old Jarvis copies listed in DESIGN "As built" | Anze |

First-night check, read-only:
- `tail -30 ~/.analyst/state/logs/hud-audit-nightly.log ~/.analyst/state/logs/portfolio-advisor.log`: `=== OK` lines, no
  Traceback, no `is not a Claude surface`.
- `ls -la ~/.analyst/state/reports/portfolio/`: a `2026-10-19.md` and `latest.md` from this morning; Forge's originate
  ran on it (`~/.jarvis/logs/jarvis.log`, `originate`), not "report is Nh old".
- `mem sql "SELECT datetime(at,'unixepoch','localtime'), json_extract(data,'$.job'), json_extract(data,'$.ok'), json_extract(data,'$.model') FROM telemetry WHERE stream='fafnir.job_call' AND at > strftime('%s','2026-10-19')"` (Fafnir's job calls live in Mimir since 2026-10-24):
  `hud-audit-nightly`, `portfolio-advisor-*` with their usual models and `ok = 1`.
- `~/.jarvis/state/proposals-file.json` (hourly) and `proposals-watch.json` (07:15): any audit finding proposed tonight (`~/.analyst/state/proposals.json`)
  is in `~/.jarvis/state/hud/findings.json` exactly once.
- `~/.analyst/state/audits.json` `lastSha` moved for the repos audited.

## Audit 2026-10-21: your items

From the Jarvis audit (HUD task audit-jarvis-and-all-its-com-e5a9). The evidence, effort, risk and
done-criteria of each item are in `~/.jarvis/AUDIT-2026-10-21.md`; the phases and Anze's decisions
are in `~/.jarvis/NEXT-PROMPT.md`. Build an item only after Anze approves its phase. Prompt A below
covers these rows too. The rule stays: this component measures or knows; Jarvis alerts and acts.

- **A30 (Phase 3)** hud-audit-nightly fails a third of its runs on the budget cap; narrow its scope
  or raise the cap so a run finishes, and keep a partial report when it does not.
- **A32 (Phase 3)** job-review covers 3 jobs and has never flagged one. Cover every LLM job with
  output per dollar (reports read, findings accepted, incidents resolved).
- **A33 (Phase 3)** job-review proposes config edits as branches (still "propose, you merge").
- **A34 (Phase 3)** No read signal for reports: use the HUD's viewed marks so unread reports can be
  proposed for retirement.
- **A37 (Phase 3)** weekly-activity on Haiku fails half its runs and was recorded OK despite exit 1.
- **A38 (Phase 3)** The unmoved jobs: issue-triage to Forge, dep-rehearsal and commit-audit to
  Sentinel, token-report and usage-digest to Budget.
- **A42 (Phase 4)** `odin/common.py` (176 lines) duplicates `~/.jarvis/scripts/jobcommon.py`.

| When (earliest useful, not a deadline) | Step | Waits on |
|---|---|---|
| with Phase 3 | A30, A32, A34, then A33, then the A38 moves one at a time | Phase 3 approval |
| 2026-10-26 after 08:45 | A37: did weekly-activity-post write its note this week | the weekly run |

## A: advance the work

> Read `~/.analyst/DESIGN.md` ("As built") and this file, then do the first row of the table above whose date has come
> and that is not done; strike it through here and add the result to the top of `~/.jarvis/JOURNAL.md`. Rules: Analyst
> never alerts, pings, posts or files; Jarvis triggers it and acts (proposals-watch files, weekly-activity-post posts).
> Jarvis's job names stay. A moved job's readers are repointed in the same commit. Copy state, never delete a Jarvis
> file or table without Anze's confirmation. Tests: `~/.analyst/.venv/bin/python ~/.analyst/tests/test_odin.py`,
> Jarvis's selftest, the HUD tests and every component's tests, before and after. Restart only with
> `~/.jarvis/restart.sh`. Stop and tell me if anything differs from what the design expects.

## B: status only

> Read `~/.analyst/DESIGN.md` and this file and report whether Analyst's jobs ran as expected (the first-night list
> above). Change nothing.

## C: something is broken

> An Analyst job or proposals-watch broke. First, do not delete `~/.analyst/state`, `findings.json` or any Jarvis
> file. Run `~/.jarvis/.venv/bin/python ~/.jarvis/status.py`, read the job's log under `~/.analyst/state/logs/` and
> `~/.jarvis/logs/jarvis.log`, and report before fixing. To fall back, the ten old scripts are in Jarvis's git
> history (the commit that moved them); restoring them and their config lines is a revert of that commit.
