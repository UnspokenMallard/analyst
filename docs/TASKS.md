# Analyst tasks, 2026-10-27

Ordered by priority. From confirmed findings in `docs/AUDIT-2026-10-27.md`.

- [ ] [med] [underperforming] Keep the nightly audit under its cap — odin/jobs/hud_audit.py (cut at 150000 bytes, SKIP_REPOS at :40) — size the prompt against the $1 cap before the call and trim the diff to fit; keep the partial report — acceptance: a diff priced above $1 is trimmed, the repo is audited, and no log line says `error_max_budget_usd` for 7 nights
- [ ] [med] [underperforming] Say why a job exited 1 — odin/cli.py, odin/common.py — print the final `=== FAILED: reason ===` line to stdout/stderr — acceptance: the next `analyst-job.sh exit=1` entry in `~/.jarvis/state/errors.jsonl` has a non-empty `output tail`
- [ ] [med] [underperforming] Cover every LLM job in job-review — odin/jobs/job_review.py — read `fafnir.job_call` telemetry for all jobs and flag a job with 2 or more failed runs in 7 days or cost with no output — acceptance: replaying 2026-10-19..26 flags hud-audit-nightly; `state/job-review.json` shows `jobs` above 3
- [ ] [low] [erroring] Refuse the audit inside a HUD task session — odin/jobs/hud_audit.py — when `HUD_TASK_ID` is set, stop before the model call with one clear line — acceptance: a manual run from a task session spends $0 and prints the reason
- [ ] [low] [underperforming] Fail weekly-activity on a nonzero exit even when the file exists — odin/jobs/weekly_activity.py — check the exit code before the file-age check — acceptance: a test with exit 1 and a fresh file returns FAILED
- [ ] [low] [improvement] Make the tests discoverable — tests/test_odin.py — turn the script checks into `unittest.TestCase` methods, keep the scratch ODIN_HOME setup — acceptance: `python -m unittest discover -s tests` reports more than 0 tests and passes
- [ ] [low] [improvement] Remove the duplicated job plumbing (A42) — odin/common.py vs ~/.jarvis/scripts/jobcommon.py — pick one owner and import it from the other — acceptance: one copy left, `tests/test_odin.py` and the Jarvis selftest pass
