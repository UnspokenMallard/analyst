# Next prompt: Analyst

**Built and cut over 2026-10-18 (DONE).** The report and review jobs run in `~/.analyst`, triggered by Jarvis;
`DESIGN.md` "As built" has the layout, the job table, the readers repointed and what differs from the design.

## When to fire this

Earliest-useful dates, not deadlines; being late costs nothing (a broken job shows up as a failed Jarvis job and its
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
- `sqlite3 ~/.budget/state/budget.db "SELECT datetime(ts,'unixepoch','localtime'), job, ok, model FROM job_calls WHERE ts > strftime('%s','2026-10-19')"`:
  `hud-audit-nightly`, `portfolio-advisor-*` with their usual models and `ok = 1`.
- `~/.jarvis/state/proposals-file.json` (hourly) and `proposals-watch.json` (07:15): any audit finding proposed tonight (`~/.analyst/state/proposals.json`)
  is in `~/.jarvis/state/hud/findings.json` exactly once.
- `~/.analyst/state/audits.json` `lastSha` moved for the repos audited.

## A: advance the work

> Read `~/.analyst/DESIGN.md` ("As built") and this file, then do the first row of the table above whose date has come
> and that is not done; strike it through here and add the result to the top of `~/.jarvis/JOURNAL.md`. Rules: Analyst
> never alerts, pings, posts or files; Jarvis triggers it and acts (proposals-watch files, weekly-activity-post posts).
> Jarvis's job names stay. A moved job's readers are repointed in the same commit. Copy state, never delete a Jarvis
> file or table without Anze's confirmation. Tests: `~/.analyst/.venv/bin/python ~/.analyst/tests/test_analyst.py`,
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
