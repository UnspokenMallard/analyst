"""Monday weekly activity report: Odin writes it, Jarvis posts it (split 2026-10-18).

collect_week_activity gathers the week read-only; one tool-limited `claude -p` turns it into the
"Last week:" bullets in state/reports/week-activity/<date>.md (+ latest.md). Jarvis's
weekly-activity-post (~/.jarvis/scripts/post-weekly-activity.py) puts that text into the Notes vault under
Work/Daily Notes and adds it to the index. Odin never posts.
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime

from .. import common as jc, store
from . import collect_week_activity

REPORT_NAME = "week-activity"
DIGEST = jc.STATE_DIR / "week-activity.md"

PROMPT = """Write Anze's weekly activity report. This is an UNATTENDED scheduled run on
Monday morning. Do NOT ask any clarifying questions - there is nobody to answer
them. If a choice arises, take the most conservative option that still finishes
the report.

The week's raw activity has already been collected for you and is in the <input> block at
the end of this prompt. It is already in your context: do NOT Read it again. It holds, for the last 7 days: commits per Event Registry repo
(with author), pull requests he opened or reviewed, the Claude Code sessions he
drove, and any Jarvis queue work the Claude implementer did. Do NOT go looking for repositories,
transcripts or git history yourself - the digest is the input, and you have no
shell.

Write the report with the Write tool to {out}, OVERWRITING any previous version.
Another program posts that file's text unchanged into the Notes vault as the note {today},
so the file holds the page body and nothing else: a line reading "Last week:"
followed by a flat list of short bullets, each one a theme in plain language -
"Login security: failed logins get the same message at a fixed deadline" - not
commit subjects, not repo names, not counts. {previous}

What the report is and is not:
- It is what ANZE did. The digest names the author of every commit; other
  people's commits are context, not his work, and the daemon's own scheduled
  runs are already excluded.
- Group the week into 6 to 12 themes, most significant first. A theme usually
  spans several commits, and often a repo and its pull request together.
- Write outcomes, not activity: "a password change ends all sessions", not
  "refactored session handling". Someone reading it in a month should learn
  what changed for users, in one line each.
- End with a bullet (two at most) for the Claude Code work he drove -
  he asked for that to be counted. Say what it produced and now does: a monitor,
  a script, a system fixed. The digest lists what each session was ASKED for, so
  judge from that; several sessions in one project over several days is one
  piece of work, not several. If the week's sessions were only questions and
  answers, say that in one short line instead of inventing an outcome.
- No preamble, no summary of the summary, no "this week was productive".
- If the digest says COULD NOT COLLECT for a source, add one closing line
  saying which source was missing, so a thin report is never mistaken for a
  quiet week.

You MUST call the Write tool to create the file. A chat answer instead of the
file is a failed run even if the exit code is 0. If you cannot finish, say why in
one line beginning with FAILED so the log is greppable.

{digest_text}
"""


def main(argv: list[str] | None = None) -> int:
    job = jc.Job("weekly-activity", "weekly activity report")
    with open(job.log, "a", encoding="utf-8") as fh:
        subprocess.run([jc.PYTHON, "-m", collect_week_activity.__name__, "--days", "7", "--out", str(DIGEST)],
                       stdout=fh, stderr=subprocess.STDOUT, cwd=store.CODE)
    if not DIGEST.exists():
        return job.fail("the collector wrote no digest - nothing to report on")
    age_min = (time.time() - DIGEST.stat().st_mtime) / 60
    if age_min > 30:
        return job.fail(f"the digest is {age_min:.0f} min old, so the collector did not run this time")
    job.say(f"digest: {DIGEST.stat().st_size} chars at {DIGEST}")
    today = datetime.now().strftime("%Y-%m-%d")
    out = store.report_dir(REPORT_NAME) / f"{today}.md"
    last = store.latest(REPORT_NAME)
    previous = (f"Last week's report, {last}, shows the format; match it." if last.exists() else "")
    prompt = PROMPT.format(digest_text=jc.inline_input(DIGEST.read_text(encoding="utf-8"), "week-activity digest"), out=out, today=today, previous=previous)
    if not jc.wait_for_api(job.log):
        return 1
    with jc.job_lock("weekly-activity", job.log) as held:
        if not held:
            return 1
        code = jc.run_claude_job(
            prompt, job.log, "weekly-activity", budget_usd=1.00, tools="Read,Write,Edit", scope="work",
            allow=[f"Read({jc.rule_path(last)})", f"Read({jc.rule_path(out)})",
                   f"Write({jc.rule_path(out)})", f"Edit({jc.rule_path(out)})"])
    if job.assert_artifact(out, code, what=f"week-activity/{out.name}") != 0:
        return 1
    text = out.read_text(encoding="utf-8")
    if "Last week:" not in text:
        return job.fail(f"{out.name} has no 'Last week:' line - not the page body the poster expects")
    store.write_report(REPORT_NAME, text, day=today)
    return 0
