# Analyst

The jobs that read the state of Anze's work and machines and turn it into reports and proposals:
the portfolio advisor, the consultant digest, the week's activity and changes, the code audits of
the HUD's projects, and the reviews of Jarvis's own alerts, rules and jobs. Designed 2026-10-17.

## Decisions (Anze, 2026-10-17)

| Question | Decision |
|---|---|
| Home | `~/.analyst`, own git repo, code and `state/` together, own venv |
| Scope | Report jobs move here; the memory jobs (weekly introspect, nightly reflection, lesson candidates) move to Mind instead |
| Handoff | Like Mind: reports in `state/reports/<name>/`, HUD finding proposals in `state/proposals.json`; a Jarvis job files the proposals and Jarvis's report pushes read the reports. Analyst never pushes, pings or files |
| Schedule | Jarvis triggers every job (`bin/analyst-job.sh <job>`), as for Budget, Sentinel, Herald and Forge |
| Process | CLI and library, no service (nothing asks it live) |
| Model calls | Through Gateway (`run_agent`), so Gateway is built first |

## Boundary

Analyst **reads and proposes**. It reads repositories, Jarvis's, Mind's and the components' state,
and writes reports and proposals. Jarvis decides what reaches Anze: the report pushes (morning,
weekly), the HUD findings it files from `proposals.json`, and anything a proposal would change.
A proposal is never applied by Analyst.

## What moves where

To Analyst (`analyst/jobs/`):

| Job (Jarvis name kept) | Script today | Model | Output today -> here |
|---|---|---|---|
| `portfolio-advisor` | `run-portfolio-advisor.py` + `collect-portfolio-repos.py` | yes | `~/.jarvis/portfolio-report.md` -> `state/reports/portfolio/` |
| `consultant-digest` | `run-consultant-digest.py` | yes | `~/.jarvis/consultant-digest.md` -> `state/reports/consultant/` |
| `weekly-activity` | `run-weekly-activity.py` + `collect-week-activity.py` | yes | `state/week-activity.md` -> `state/reports/week-activity/` |
| `weekly-changes` | `weekly-changes.py` | no | `reports/weekly/` -> `state/reports/weekly-changes/` |
| `hud-audit-nightly`, `hud-audit-weekly` | `run-hud-audit.py` | yes | `findings.json` directly -> proposals |
| `alert-review` | `alert-review.py` | no | findings -> proposals |
| `answer-rules` | `answer-rules.py` | no | findings -> proposals |
| `job-review` | `job-review.py` | no | findings -> proposals |

To Mind (its sleep cycle, or Jarvis-triggered like the rest): `weekly-introspect`
(`run-weekly-introspect.py`), `nightly-reflection` (`run-nightly-reflection.py`), `lesson-candidates`
(`lesson-candidates.py`). They read memory and propose memory, and Mind's capture drafts already
overlap the nightly reflection (Jarvis reminder of 2026-10-30: compare them, keep the stronger).

Not Analyst, found on inspection:
- `issue-triage` fixes code, pushes and publishes to npm: unattended work, so **Forge**.
- `dep-rehearsal` (runs dependency upgrades' tests) and `commit-audit` (`audit-commits.py`) are
  checks with no model: **Sentinel**.
- `token-report` and `usage-digest`: spend, so **Budget** (usage-digest posts to Notion, so its
  posting half stays Jarvis's).

## Proposals and their filing

`state/proposals.json` holds HUD findings in the shape the HUD reads (`id`, `project`, `severity`,
`source`, `title`, `detail`, `suggestion`, `status: open`). Ids stay stable per condition, so a
dismissed finding is never proposed again (each script already derives its ids that way).
Jarvis's `mind-watch` generalises to `proposals-watch`: it reads Mind's and Analyst's proposals
(and any later component's) and files the new open ones, never re-filing an id that exists in
`findings.json` in any status. `[job_findings]` maps each job to its finding source as today.

## First steps for the build session

1. Gateway must be DONE (`~/.gateway/NEXT-PROMPT.md`).
2. Map every reader of each output above: report pushes in `config.toml`, the morning digest, the
   HUD (Today panel, findings), the consultant and portfolio prompts' own inputs, Mind's attention.
3. Move one job at a time, its outputs with it, repointing its readers in the same commit; the
   memory jobs to Mind in their own commits.
4. The finding scripts last, together with `proposals-watch`, checked by a run that files nothing
   twice. Selftest and every component's tests before and after.

## As built (2026-10-18)

Built and cut over in one session. Anze's answers shaped it: the Analyst jobs only (the memory jobs and the five
found to belong elsewhere wait, see `NEXT-PROMPT.md`), an own copy of the job plumbing, old files left in place,
and the two mismatches below.

Layout: `analyst/` library (`store.py`: paths from `ANALYST_HOME` and `JARVIS_HOME`, reports, proposals;
`common.py`: the generic half of Jarvis's `scripts/jobcommon.py`, calling `gateway.run_agent` directly, same
nightly lock file; `notmine.py`: copy of Jarvis's reader of `state/not-mine.json`), `analyst/jobs/` (one module
per job), `analyst/cli.py` behind `bin/analyst`, `bin/analyst-job.sh` (Jarvis's entry point),
`tests/test_analyst.py`, `tools/migrate-from-jarvis.py` (one-off), own venv (`uv venv`, 3.13, no packages).
No service and no `config.toml`: every job reads what it read before.

| Jarvis job | Trigger (`analyst-job.sh ...`) | Artifact Jarvis asserts | Report |
|---|---|---|---|
| `portfolio-advisor` | `portfolio-advisor` | `state/logs/portfolio-advisor.log` | `state/reports/portfolio/` |
| `consultant-digest` | `consultant-digest` | `state/reports/consultant/latest.md` | same |
| `weekly-activity` | `weekly-activity` | `state/reports/week-activity/latest.md` | same |
| `weekly-changes` | `weekly-changes` | `state/weekly-changes.json` | `state/reports/weekly-changes/` |
| `hud-audit-nightly`, `-weekly` | `hud-audit nightly\|weekly` | `state/audits.json` | proposals |
| `alert-review`, `answer-rules`, `job-review` | the job name | `state/<job>.json` | `state/reports/<job>/` + proposals |

- Reports are `state/reports/<name>/<date>.md` plus `latest.md` (Mind's layout); job logs `state/logs/<job>.log`.
- Readers repointed: Forge `store.REPORT` (the originator's input, `ANALYST_HOME`-aware), the consultant prompt,
  `report-push-weekly`, Sentinel's config-drift `configs` keys, Sentinel's `log-signatures` (reads both log
  dirs), the week collector's job-session filter (both log dirs), the `update-brain` skill, the checkups text,
  `check-hud-findings.py`'s docstring. `[job_findings]` names `proposals-watch`.
- Jarvis: `scripts/mind-watch.py` became `scripts/proposals-watch.py` (job `proposals-watch`, daily 07:15, plus
  `proposals-file` hourly with `--file-only`): files new open
  proposals from Mind (`/api/proposals`) and Analyst (`state/proposals.json`), never an id already in
  `findings.json` in any status. Selftest covers it (662/0).
- State copied by `tools/migrate-from-jarvis.py` (copies only, mtimes kept): `audits.json` (without it every repo is
  "first sight" and a night is lost), the review artifacts, the report history, `portfolio-report.md` and
  `consultant-digest.md`. No `jarvis.db` table moved, so no backup was needed. The ten scripts left Jarvis's git
  (as Sentinel's and Herald's did); the old output files stay until Anze confirms removing them:
  `~/.jarvis/portfolio-report.md`, `consultant-digest.md`, `state/hud/audits.json`, `state/{alert-review,
  answer-rules,job-review,weekly-changes}.json`, `state/week-activity.md`, `state/portfolio-repos*.md`,
  `state/portfolio-report.*.md`, `reports/{alert-review,answer-rules,job-review,weekly}/`, `state/hud/audit-work/`.

Differs from the design above:

- **hud-audit is not add-only** (Anze's call: proposals carry updates). It also moved `lastSeen`, reopened a finding
  seen again after its fix merged, and kept one npm-audit finding per repo in line with each run. Its proposals
  carry `lastSeen`, and the npm-audit one `sync: true` and `status` open/resolved. proposals-watch applies a
  sighting once, when its `lastSeen` is newer than the finding's: the new `lastSeen`; a merge-resolved finding
  reopens; a `sync` finding takes severity, detail and suggestion and moves open/resolved. A dismissed finding is
  never reopened. The one-time fold of per-package npm findings (2026-10-11) was dropped: none were left.
- **weekly-activity is split** (Anze's call: Analyst writes, Jarvis posts). `state/week-activity.md` was its input,
  the output a Notion page. Analyst writes the page body (`Last week:` + bullets, $1 cap); Jarvis's new job
  `weekly-activity-post` (`scripts/post-weekly-activity.py`, Mon 08:45, $0.75 cap, surface `job:weekly-activity`)
  posts it unchanged, updates the index and writes the receipt the old job wrote. It fails when there is no report
  for today. The first run has no earlier report to match the format against; the prompt states the format.
- **Filing runs hourly** (`proposals-file`, `--file-only`), so an audit's findings reach the HUD within the hour as they
  did when the audit wrote `findings.json` itself. That run never fails; the daily `proposals-watch` keeps
  mind-watch's checks and alerts (an hourly failure would be 24 alerts and a `burn:repeat`). A Mind that is down
  still lets Analyst's proposals through.
- The consultant digest still refreshes Jarvis's checkpoint first (`checkpoint.py`, on Jarvis's interpreter), and the
  portfolio advisor still keeps its Living memory notes up to date through `mem`. Neither alerts, pings or files.
- The review reports gained dated copies next to `latest.md`.
- `scripts/jobcommon.py` stays in Jarvis for its own model jobs (introspect, reflection, issue-triage, checkups).
