"""One week of Anze's own activity, collected into a digest for weekly-activity
(macOS port of collect-week-activity.ps1). Read-only: git log, `gh search`,
transcripts. Every section says where it looked, and a source that cannot be
read says COULD NOT COLLECT - a silently missing section would read to the
model as "nothing happened that week".

Usage: analyst collect-week-activity [--days 7] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from .. import store

HOME = Path.home()
OWNERS = ("Event-Registry", "EventRegistry")
SKIP_PREFIX = ("<system-reminder", "<local-command", "<command-name", "<command-message")
MACHINE_RE = re.compile(r"UNATTENDED scheduled run|there is no shell to ask|Do NOT ask any clarifying questions")
MACHINE_START = ("Portfolio advisor:", "Nightly reflection over", "Daily usage digest", "Weekly introspection",
                 "Consultant digest", "Weekly memory-hygiene audit", "Weekly consultant digest",
                 "Write Anze's weekly activity report")


def git(repo: Path, *args: str) -> tuple[int, list[str]]:
    r = subprocess.run(["git", "-C", str(repo), "--no-optional-locks", *args], capture_output=True, text=True,
                       errors="replace")
    return r.returncode, [ln for ln in r.stdout.splitlines() if ln.strip()]


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def project_name(dirname: str) -> str:
    name = re.sub(r"^-Users-anzes-?", "", dirname)
    name = re.sub(r"^C--Users-anzes-?", "", name)
    return name.replace("-", "/") or "home"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default=str(store.STATE / "week-activity.md"))
    ap.add_argument("--repo-root", default=str(HOME / "code" / "eventregistry"))
    a = ap.parse_args(argv)
    since = datetime.now() - timedelta(days=a.days)
    since_date = since.strftime("%Y-%m-%d")
    out: list[str] = [f"# Activity digest: {since_date} to {datetime.now():%Y-%m-%d}", "",
                      f"Collected {datetime.now():%Y-%m-%d %H:%M} by analyst collect-week-activity. "
                      f"Window: the last {a.days} days.", "",
                      "## Commits (Event Registry repos, current branch of each)", ""]
    root = Path(a.repo_root)
    repos = sorted(p for p in root.iterdir() if (p / ".git").exists()) if root.is_dir() else []
    if not repos:
        out.append(f"COULD NOT COLLECT: no git repositories under {root}")
    for repo in repos:
        _, br = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        c1, log = git(repo, "log", f"--since={since_date}", "--no-merges", "--pretty=format:%ad|%an|%s", "--date=short")
        _, merges = git(repo, "log", f"--since={since_date}", "--merges", "--pretty=format:%ad|%an|%s", "--date=short")
        if c1 != 0 and not log:
            out.append(f"- **{repo.name}**: COULD NOT COLLECT (git log failed)")
            continue
        if not log and not merges:
            continue
        out.append(f"### {repo.name} (branch {br[0] if br else '?'}): {len(log)} commit(s), {len(merges)} merge(s)")
        for ln in log:
            p = ln.split("|", 2)
            if len(p) == 3:
                out.append(f"- {p[0]} [{p[1]}] {p[2]}")
        for ln in merges:
            p = ln.split("|", 2)
            if len(p) == 3:
                out.append(f"- {p[0]} [{p[1]}] MERGE: {p[2]}")
        out.append("")

    out += [f"## Pull requests ({', '.join(OWNERS)})", ""]
    for flag, label in (("--author=@me", "opened by Anze"), ("--reviewed-by=@me", "reviewed by Anze")):
        r = subprocess.run(["gh", "search", "prs", flag, f"--updated=>={since_date}", "--limit", "50",
                            "--json", "repository,number,title,state,updatedAt"], capture_output=True, text=True)
        if r.returncode != 0:
            out.append(f"- {label}: COULD NOT COLLECT ({(r.stderr or r.stdout).strip()[:200]})")
            continue
        try:
            prs = json.loads(r.stdout or "[]")
        except ValueError:
            out.append(f"- {label}: COULD NOT COLLECT (unreadable gh output)")
            continue
        mine = [p for p in prs if p["repository"]["nameWithOwner"].split("/")[0] in OWNERS]
        if not mine:
            out.append(f"- {label}: none in this window")
            continue
        out.append(f"- {label}:")
        out += [f"  - {p['repository']['nameWithOwner']}#{p['number']} [{p['state']}] {p['title']}" for p in mine]
    out += ["", "## Claude Code sessions (all projects, not only Event Registry)", ""]

    dirs = [HOME / ".claude" / "projects", HOME / ".claude-personal" / "projects", HOME / ".claude-work" / "projects"]
    missing = [str(d) for d in dirs if not d.exists()]
    if missing:
        out.append(f"COULD NOT COLLECT: transcript dir(s) missing: {', '.join(missing)}")
    machine = set()
    # The scheduled jobs log their session ids: Jarvis's in ~/.jarvis/logs, Odin's in its state/logs.
    for lf in [*(store.JARVIS / "logs").glob("*.log"), *store.LOGS.glob("*.log")]:
        machine.update(m.lower() for m in re.findall(r"session ([0-9a-fA-F-]{36})",
                                                      lf.read_text(encoding="utf-8", errors="replace")))
    cutoff = since.timestamp()
    all_s = sorted((p for d in dirs if d.exists() for p in d.rglob("*.jsonl") if p.stat().st_mtime > cutoff),
                   key=lambda p: p.stat().st_mtime)
    sessions = [s for s in all_s if s.stem.lower() not in machine]
    machine_count = len(all_s) - len(sessions)
    lines = []
    for s in sessions:
        ask = full = ""
        with open(s, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= 120:
                    break
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("type") != "user":
                    continue
                text = text_of((o.get("message") or {}).get("content"))
                if not text.strip() or text.lstrip().startswith(SKIP_PREFIX) \
                        or text.lstrip().startswith(("Caveat:", "[Request interrupted")):
                    continue
                full, ask = text, " ".join(text.split())
                break
        if MACHINE_RE.search(full) or full.startswith(MACHINE_START):
            machine_count += 1
            continue
        ask = (ask[:220] + "...") if len(ask) > 220 else (ask or "(no prose prompt found in the first 120 lines)")
        lines.append(f"- {datetime.fromtimestamp(s.stat().st_mtime):%Y-%m-%d} [{project_name(s.parent.name)}] {ask}")
    if not sessions or not lines:
        out.append(f"None in this window that were Anze's own ({machine_count} scheduled run(s) excluded).")
    else:
        out += [f"{len(lines)} session(s), oldest first. Project, day, and what the session was asked to do. "
                f"({machine_count} of the daemon's own scheduled runs were excluded - they are not Anze's work.)", ""]
        out += lines

    out += ["", "## Work done by the Jarvis queue (Claude implementer)", ""]
    deleg = HOME / ".jarvis" / "delegation"
    if not deleg.exists():
        out.append(f"COULD NOT COLLECT: {deleg} is missing")
    else:
        tasks = sorted((p for sub in ("done", "failures") for p in (deleg / sub).glob("*.json")
                        if p.stat().st_mtime > cutoff), key=lambda p: p.stat().st_mtime)
        if not tasks:
            out.append("None in this window.")
        for t in tasks:
            try:
                what = json.loads(t.read_text(encoding="utf-8-sig")).get("task") or t.stem
            except ValueError:
                what = t.stem
            out.append(f"- {datetime.fromtimestamp(t.stat().st_mtime):%Y-%m-%d} "
                       f"[{'done' if t.parent.name == 'done' else 'FAILED'}] {what}")
    op = Path(a.out)
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {op} ({op.stat().st_size:,} chars, {len(repos)} repo(s), {len(lines)} session(s) of Anze's own, "
          f"{machine_count} machine run(s) excluded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
