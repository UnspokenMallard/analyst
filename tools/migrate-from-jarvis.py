"""One-off (2026-10-18): copy the moved jobs' state and report history from ~/.jarvis into ~/.analyst/state.

Copies only; the Jarvis files stay where they are until Anze confirms removing them. A target that
already exists is left alone, so a second run changes nothing. Run before the restart that cuts over.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

J = Path.home() / ".jarvis"
A = Path.home() / ".analyst" / "state"

FILES = {  # Jarvis path -> Analyst path
    J / "state" / "hud" / "audits.json": A / "audits.json",  # without it every repo is "first sight" and a night is skipped
    J / "state" / "alert-review.json": A / "alert-review.json",
    J / "state" / "answer-rules.json": A / "answer-rules.json",
    J / "state" / "job-review.json": A / "job-review.json",
    J / "state" / "weekly-changes.json": A / "weekly-changes.json",
    J / "state" / "week-activity.md": A / "week-activity.md",
    J / "state" / "portfolio-repos.md": A / "portfolio-repos.md",
}
DIRS = {  # report history
    J / "reports" / "alert-review": A / "reports" / "alert-review",
    J / "reports" / "answer-rules": A / "reports" / "answer-rules",
    J / "reports" / "job-review": A / "reports" / "job-review",
    J / "reports" / "weekly": A / "reports" / "weekly-changes",
}
LATEST = {  # single files that become <mtime date>.md + latest.md
    J / "portfolio-report.md": A / "reports" / "portfolio",
    J / "consultant-digest.md": A / "reports" / "consultant",
}


def copy(src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"missing, skipped: {src}")
    elif dst.exists():
        print(f"exists, left alone: {dst}")
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"copied {src} -> {dst}")


def main() -> int:
    for src, dst in FILES.items():
        copy(src, dst)
    for src, dst in DIRS.items():
        for f in sorted(src.glob("*")) if src.is_dir() else []:
            copy(f, dst / f.name)
    for src, d in LATEST.items():
        if src.exists():
            day = datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d")
            copy(src, d / f"{day}.md")
            copy(src, d / "latest.md")
        else:
            print(f"missing, skipped: {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
