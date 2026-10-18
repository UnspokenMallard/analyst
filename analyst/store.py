"""Analyst's paths, reports and proposals.

Paths come from ANALYST_HOME (default ~/.analyst) and JARVIS_HOME (default ~/.jarvis), so the tests and
Jarvis's selftest point both at scratch before anything here is imported.

Reports: state/reports/<name>/<date>.md plus latest.md (Mind's layout). Jarvis's report pushes, Forge and the
consultant digest read latest.md.
Proposals: state/proposals.json, {"findings": [...]} in the shape the HUD reads. Analyst never files them;
Jarvis's proposals-watch does (~/.jarvis/scripts/proposals-watch.py).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from datetime import date
from pathlib import Path

HOME = Path.home()
CODE = Path(__file__).resolve().parents[1]  # the checkout holding the analyst package (cwd for `python -m`)
ANALYST = Path(os.environ.get("ANALYST_HOME") or HOME / ".analyst")
JARVIS = Path(os.environ.get("JARVIS_HOME") or HOME / ".jarvis")
STATE = ANALYST / "state"
LOGS = STATE / "logs"
REPORTS = STATE / "reports"
PROPOSALS = STATE / "proposals.json"
# Jarvis's HUD findings, read only here (dedup, job-review's outcomes); proposals-watch writes them.
FINDINGS = JARVIS / "state" / "hud" / "findings.json"


def report_dir(name: str) -> Path:
    d = REPORTS / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def latest(name: str) -> Path:
    return REPORTS / name / "latest.md"


def write_report(name: str, text: str, day: str | None = None) -> Path:
    """Write <date>.md and latest.md for one report; returns the dated file."""
    d = report_dir(name)
    dated = d / f"{day or date.today().isoformat()}.md"
    dated.write_text(text, encoding="utf-8")
    latest(name).write_text(text, encoding="utf-8")
    return dated


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextlib.contextmanager
def proposals():
    """The proposals list, locked for one read-modify-write: jobs may overlap (Sunday's audit and reviews)."""
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / "proposals.lock", "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        db = load_json(PROPOSALS, {"findings": []})
        db.setdefault("findings", [])
        yield db["findings"]
        save_json(PROPOSALS, db)


def propose_new(rows: list[dict]) -> list[str]:
    """Add the rows whose id is neither proposed already nor a HUD finding in any status; returns their ids."""
    have = {f.get("id") for f in load_json(FINDINGS, {"findings": []}).get("findings", [])}
    with proposals() as props:
        have |= {p.get("id") for p in props}
        added = [r for r in rows if r.get("id") and r["id"] not in have]
        props.extend(added)
    return [r["id"] for r in added]
