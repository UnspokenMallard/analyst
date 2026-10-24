"""Git state of every repository under ~/code, as one Markdown digest for the
portfolio advisor (macOS port of collect-portfolio-repos.ps1).

READ-ONLY by construction: every git call passes --no-optional-locks, so
`git status` never takes the index lock of a repo someone is working in.
Every repository found is listed, including ones where git failed - a repo that
silently drops out of the input drops out of the report.

Usage: analyst collect-portfolio-repos [--root DIR] [--out FILE] [--max-depth 6]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from .. import notmine, store  # notmine: repositories Anze marked not his

SKIP = {"node_modules", ".git", "dist", "build", "bin", "obj", ".venv", "venv", "__pycache__", ".next",
        "target", "vendor", ".angular", "coverage", ".cache",
        ".worktrees"}  # HUD task worktrees (~/.jarvis/hud) belong to their repository


def git(repo: Path, *args: str) -> tuple[int, list[str]]:
    r = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args],
                       capture_output=True, text=True, errors="replace")
    return r.returncode, [ln for ln in (r.stdout + r.stderr).splitlines()]


def find_repos(root: Path, max_depth: int) -> list[Path]:
    repos, queue = [], deque([(root, 0)])
    while queue:
        d, depth = queue.popleft()
        if (d / ".git").exists() and notmine.is_mine(d):
            repos.append(d)
        if depth >= max_depth:
            continue
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir() and not p.is_symlink())
        except OSError:
            continue
        for c in children:
            if c.name not in SKIP:
                queue.append((c, depth + 1))
    return sorted(repos)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home() / "code"))
    ap.add_argument("--out", default=str(store.STATE / "portfolio-repos.md"))
    ap.add_argument("--max-depth", type=int, default=6)
    a = ap.parse_args(argv)
    root, out = Path(a.root), Path(a.out)
    repos = find_repos(root, a.max_depth)
    now = time.time()
    lines = [f"# Portfolio repo digest - {datetime.now():%Y-%m-%d %H:%M}", "",
             f"Collected read-only by analyst collect-portfolio-repos (git --no-optional-locks). {len(repos)} "
             f"repositories under {root}, searched {a.max_depth} levels deep. Every one is listed below, "
             "including any where git failed."]
    for repo in repos:
        rel = os.path.relpath(repo, root)
        rel = root.name if rel == "." else rel
        lines += ["", f"## {rel}"]
        code, status = git(repo, "status", "--porcelain=v1", "-b")
        if code != 0:
            lines.append(f"- git failed here: {' / '.join(status[:2])}")
            continue
        branch = next((s for s in status if s.startswith("## ")), "## ?")
        lines.append(f"- branch: `{branch[3:]}`" + ("" if "..." in branch else " (no upstream tracking branch)"))
        c, last = git(repo, "log", "-1", "--format=%ct")
        if c == 0 and last and last[0].isdigit():
            when = int(last[0])
            lines.append(f"- last commit: {datetime.fromtimestamp(when):%Y-%m-%d} ({int((now - when) / 86400)} days ago)")
        else:
            lines.append("- last commit: none (no commits yet, or git log failed)")
        changes = [s for s in status if not s.startswith("## ") and s.strip()]
        if not changes:
            lines.append("- uncommitted: none")
        else:
            oldest = None
            for ch in changes:
                p = repo / ch[3:].split(" -> ")[-1].strip('"')
                try:
                    m = p.lstat().st_mtime
                    oldest = m if oldest is None or m < oldest else oldest
                except OSError:
                    pass
            age = f", oldest changed {int((now - oldest) / 86400)} days ago" if oldest else ""
            lines.append(f"- uncommitted: {len(changes)} file(s){age}")
            lines += [f"  - `{ch}`" for ch in changes[:15]]
            if len(changes) > 15:
                lines.append(f"  - ...and {len(changes) - 15} more")
        c, log = git(repo, "log", "-5", "--date=short", "--pretty=format:%ad %h %s")
        if c == 0 and log:
            lines.append("- recent commits:")
            lines += [f"  - {ln}" for ln in log]
        tasks = repo / "docs" / "TASKS.md"
        if tasks.exists():
            open_items = [ln.strip() for ln in tasks.read_text(encoding="utf-8", errors="replace").splitlines()
                          if ln.lstrip().startswith(("- [ ]", "* [ ]"))]
            lines.append(f"- docs/TASKS.md open items: {len(open_items)}")
            lines += [f"  - {ln}" for ln in open_items[:15]]
            if len(open_items) > 15:
                lines.append(f"  - ...and {len(open_items) - 15} more")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"collected {len(repos)} repositories into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
