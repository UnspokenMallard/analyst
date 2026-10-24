"""Weekly: permission prompts Anze keeps answering "Yes" become proposed allow rules.

Anze, 2026-10-15: most HUD taps are answers to menus; a prompt he approves every time
should not need him. The HUD logs every answer it sends (hud/lib/screen.js, type
"answer" in state/hud/events.jsonl: question, chosen label, options, and the pending
tool call from the transcript).

Groups answers by tool and command prefix (Bash: first two words; file tools: the tool
name). A group with MIN_YES approvals in the window and no refusal becomes one HUD
finding on project claude-config proposing an allow rule, e.g. `Bash(npm test *)`.
Commands that change shared state (push, rm, deploy, ...) and file edits are never proposed.

Proposals only: it edits no settings.json. Anze adds the rule (or tells a session to).
Usage: analyst answer-rules [--days N] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone

from .. import store

JARVIS = store.JARVIS
EVENTS = JARVIS / "state" / "hud" / "events.jsonl"
REPORT_NAME = "answer-rules"
ARTIFACT = store.STATE / "answer-rules.json"
MIN_YES = 3
# Never proposed for auto-allow, whatever the history: these change shared or remote state,
# or (interpreters and wrappers) run whatever follows them. Matched on the basename too.
RISKY = re.compile(r"^(?:\S*/)?(sudo|rm|git (push|reset|rebase|merge|tag|branch|checkout|clean|filter-branch)|"
                   r"gh |docker (rm|compose down)|kill|pkill|launchctl|ssh|scp|rsync|curl|wget|"
                   r"npm (publish|install|i)\b|pip install|brew|deploy|mv|chmod|chown|dd|"
                   r"python[\d.]*|node|bash|sh|zsh|eval|exec|source|xargs|find|env|nohup|timeout|uv run)\b")
# Tools whose second word is a subcommand (npm test, git status); for the rest it is an argument.
SUBCOMMAND = {"npm", "npx", "pnpm", "yarn", "git", "docker", "gh", "cargo", "make", "uv", "pip", "go", "node", "tsc"}
# Edit and Write are a mode choice (accept edits), not a rule: listed, never proposed.
NEVER_RULE = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
CHAIN = "Bash(<chain of commands>)"
PERMISSION_Q = re.compile(r"proceed|allow|permission|make this edit|create|run", re.I)


def answers(since: float) -> list[dict]:
    out = []
    try:
        with open(EVENTS, encoding="utf-8") as fh:
            for line in fh:
                if '"answer"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                at = ev.get("at", "")
                if ev.get("type") != "answer" or not at:
                    continue
                if datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp() >= since:
                    out.append(ev)
    except OSError:
        pass
    return out


def group_of(ev: dict) -> tuple[str, str] | None:
    """(rule, sample) for a permission answer, or None for a plain question."""
    tool = ev.get("tool") or {}
    name = tool.get("name")
    if not name or not PERMISSION_Q.search(ev.get("question", "")):
        return None
    if name == "Bash":
        cmd = " ".join(str(tool.get("detail", "")).split())
        # cd only moves: the prompt came from what follows it. A chain of several commands is
        # listed as one group and never proposed, since any of them may have caused the prompt.
        parts = [p for p in re.split(r"\s*(?:&&|\|\||;|\|)\s*", cmd) if p and p.split()[0] != "cd"]
        if len(parts) > 1:
            return CHAIN, cmd[:120]
        # env assignments are skipped
        words = [w for w in (parts[0] if parts else "").split() if "=" not in w]
        if not words:
            return None
        sub = len(words) > 1 and words[0] in SUBCOMMAND and not words[1].startswith(("-", "/", "~", "."))
        prefix = " ".join(words[:2]) if sub else words[0]
        return f"Bash({prefix} *)", cmd[:120]
    return name, str(tool.get("detail", ""))[:120]


def is_yes(label: str) -> bool:
    return label.lower().startswith("yes")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    evs = answers(time.time() - args.days * 86400)

    groups: dict[str, dict] = defaultdict(lambda: {"yes": 0, "no": 0, "samples": set(), "projects": set()})
    for ev in evs:
        g = group_of(ev)
        if not g:
            continue
        rule, sample = g
        row = groups[rule]
        row["yes" if is_yes(ev.get("label", "")) else "no"] += 1
        row["samples"].add(sample)
        if ev.get("project"):
            row["projects"].add(ev["project"])

    proposals = []
    for rule, row in sorted(groups.items(), key=lambda kv: -kv[1]["yes"]):
        prefix = rule[5:-3] if rule.startswith("Bash(") else ""  # "Bash(git status *)" -> "git status"
        # a bare subcommand tool (`git -C dir status` groups as `git`) would allow all of it
        if (row["yes"] >= MIN_YES and not row["no"] and rule not in NEVER_RULE and rule != CHAIN
                and not (prefix and (RISKY.match(prefix) or prefix in SUBCOMMAND))):
            proposals.append((rule, row))

    lines = [f"# Answer rules - {datetime.now():%Y-%m-%d %H:%M}", "",
             f"{len(evs)} answer(s) logged by the HUD in the last {args.days} days; "
             f"{sum(r['yes'] + r['no'] for r in groups.values())} were permission prompts. "
             f"Proposed: {MIN_YES}+ yes, never no, not risky.", "",
             "| yes | no | rule | projects | proposed |", "|---:|---:|---|---|---|"]
    for rule, row in sorted(groups.items(), key=lambda kv: -(kv[1]["yes"] + kv[1]["no"])):
        lines.append(f"| {row['yes']} | {row['no']} | `{rule}` | {', '.join(sorted(row['projects']))} | "
                     f"{'**yes**' if any(r == rule for r, _ in proposals) else 'no'} |")

    added = []
    if not args.dry_run:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = []
        for rule, row in proposals:
            fid = "allow-" + hashlib.sha1(rule.encode()).hexdigest()[:10]
            rows.append({
                "id": fid, "project": "claude-config", "severity": "low", "kind": "permission",
                "title": f"You approved {rule} {row['yes']}x and never refused it: allow it?",
                "file": "~/.claude-personal/settings.json", "line": 0,
                "detail": f"Projects: {', '.join(sorted(row['projects'])) or '?'}. Samples: "
                          + "; ".join(sorted(row["samples"])[:3]),
                "suggestion": f"Add \"{rule}\" to permissions.allow in the config(s) those projects use "
                              "(claude-personal and/or claude-work), or dismiss this to keep being asked.",
                "source": "answer-rules", "status": "open", "foundAt": now, "lastSeen": now,
            })
        added = store.propose_new(rows)  # Jarvis's proposals-watch files them
        store.write_report(REPORT_NAME, "\n".join(lines) + "\n")
        ARTIFACT.write_text(json.dumps({"checked_at": now, "answers": len(evs),
                                        "proposed": [r for r, _ in proposals], "findings_added": added}, indent=2),
                            encoding="utf-8")
    print("\n".join(lines))
    print(f"\nfindings added: {len(added)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
