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
