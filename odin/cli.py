"""`analyst <job> [args]`: run one job. Jarvis triggers each through bin/analyst-job.sh and asserts its
artifact; Odin keeps no schedule of its own."""
from __future__ import annotations

import importlib
import sys

# Jarvis's job name -> module under odin.jobs (the two collectors run on their own for debugging).
JOBS = {
    "portfolio-advisor": "portfolio_advisor",
    "consultant-digest": "consultant_digest",
    "weekly-activity": "weekly_activity",
    "weekly-changes": "weekly_changes",
    "hud-audit": "hud_audit",
    "alert-review": "alert_review",
    "answer-rules": "answer_rules",
    "job-review": "job_review",
    "collect-portfolio-repos": "collect_portfolio_repos",
    "collect-week-activity": "collect_week_activity",
}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in JOBS:
        print("usage: analyst <job> [args]\njobs: " + ", ".join(JOBS), file=sys.stderr)
        return 2
    return importlib.import_module(f"odin.jobs.{JOBS[argv[0]]}").main(argv[1:]) or 0
