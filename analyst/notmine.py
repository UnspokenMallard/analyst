"""Repositories Anze marked "not mine" (added 2026-10-11).

He clones some repositories only to read them (newsapi-mcp, for one). Jobs that walk
every repository under ~/code -- the HUD audits, commit-audit, sweep-repos,
repo-versions, the portfolio digest -- skip the ones listed here, and their audit
findings stop counting. The HUD's project list marks and restores them; it owns
the file:

    state/not-mine.json  {"repos": [{"name", "path", "since", "note"}]}

A missing or unreadable file means nothing is excluded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FILE = Path(os.environ.get("JARVIS_NOT_MINE_FILE") or Path.home() / ".jarvis" / "state" / "not-mine.json")


def entries() -> list[dict]:
    try:
        rows = json.loads(FILE.read_text(encoding="utf-8")).get("repos", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("path")]


def paths() -> set[Path]:
    return {Path(r["path"]).expanduser().resolve() for r in entries()}


def names() -> set[str]:
    return {r["name"] for r in entries() if r.get("name")}


def is_mine(repo: Path) -> bool:
    return Path(repo).expanduser().resolve() not in paths()
