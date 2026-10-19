"""Shared plumbing for Analyst's model jobs, copied from Jarvis's scripts/jobcommon.py (2026-10-18).

  job_lock()        the one nightly flock every `claude -p` job and Jarvis's brain calls share
                    (same file as jobcommon and daemon/core.py's NightlyJobLock). On timeout the
                    caller MUST exit non-zero.
  wait_for_api()    DNS *and* a TCP connect to api.anthropic.com:443
  rule_path()       an absolute path in the `//abs/path` form Claude Code permission rules need (a
                    single leading `/` is relative to the settings file's project, not the filesystem).
  job_budget()      Budget's job-budget gate, asked before each repository of a multi-repo job.
  run_claude_job()  one tool-limited job session through Gateway's `run_agent`: dontAsk, an explicit
                    tool list, pre-approved rules, the per-run budget, the weekly ceiling, every
                    attempt's cost in Budget's job_calls. The model is Gateway's (surface `job:<name>`).
  Job               the log and the artifact/receipt freshness assertions every job ends with.

Verification is by artifact, never by exit code.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import store

HOME = store.HOME
JARVIS = store.JARVIS
LOG_DIR = store.LOGS
STATE_DIR = store.STATE
BUDGET_CLI = HOME / ".budget" / "bin" / "budget"
LOCK_PATH = HOME / ".claude-personal" / "state" / "nightly-job.lock"
PYTHON = sys.executable

sys.path.insert(0, str(HOME / ".budget"))
sys.path.insert(0, str(HOME / ".gateway"))
import gateway  # noqa: E402


def now_s() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_line(log_file: Path, text: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(text.rstrip("\n") + "\n")


def rule_path(path: Path | str) -> str:
    p = Path(path).as_posix()
    return "/" + p if p.startswith("/") and not p.startswith("//") else p


@contextlib.contextmanager
def job_lock(job_name: str, log_file: Path, max_wait_min: int = 45, interval_s: int = 30):
    """Yields True with the lock held, or False after max_wait_min (caller exits 1)."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + max_wait_min * 60
    attempt, waited, fh = 0, False, None
    while time.time() < deadline:
        attempt += 1
        fh = open(LOCK_PATH, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.seek(0)
            holder = fh.read().strip()
            fh.close()
            fh = None
            if not waited:
                log_line(log_file, f"another nightly job is running{f' (held by: {holder})' if holder else ''}"
                                   f" - waiting up to {max_wait_min} min")
                waited = True
            time.sleep(interval_s)
            continue
        fh.seek(0)
        fh.truncate()
        fh.write(f"{job_name} pid={os.getpid()} acquired={datetime.now().isoformat(timespec='seconds')}")
        fh.flush()
        if waited:
            log_line(log_file, f"lock acquired after {attempt} attempt(s) - previous job finished")
        try:
            yield True
        finally:
            fh.close()
        return
    log_line(log_file, f"=== FAILED: could not acquire the nightly job lock within {max_wait_min} min - "
                       "another job is stuck. This cycle did NOT run. ===")
    yield False


def wait_for_api(log_file: Path, max_wait_min: int = 20, interval_s: int = 30,
                 host: str = "api.anthropic.com") -> bool:
    deadline = time.time() + max_wait_min * 60
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        dns_ok = tcp_ok = False
        try:
            addr = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)[0][4]
            dns_ok = True
            with socket.create_connection((addr[0], 443), timeout=10):
                tcp_ok = True
        except OSError:
            pass
        if dns_ok and tcp_ok:
            if attempt > 1:
                log_line(log_file, f"network ready after {attempt} attempt(s)")
            return True
        log_line(log_file, f"waiting for network: attempt {attempt}, dns={dns_ok} tcp443={tcp_ok}")
        time.sleep(interval_s)
    log_line(log_file, f"=== FAILED: network never became reachable within {max_wait_min} min - "
                       "aborting before invoking claude ===")
    return False


def job_budget(scope: str, optional: bool = False) -> tuple[int, str]:
    """(0, text) to go ahead, (1, text) when the account's budget is reached, anything else when it
    could not be checked."""
    cmd = [str(BUDGET_CLI), "job-budget", f"--scope={scope}"] + (["--optional"] if optional else [])
    b = subprocess.run(cmd, capture_output=True, text=True)
    return b.returncode, (b.stdout + b.stderr).strip().replace("\n", " ")


def inline_input(text: str, label: str) -> str:
    """A job's input as a prompt block. The model gets it once here and has no Read rule for it, so
    it cannot re-read it (a 80k-token digest was read nine times in one week)."""
    return f"<input name=\"{label}\">\n{text}\n</input>"


# No MCP servers: their ~295 tool schemas are ~300k tokens before turn 1 (measured 2026-10-19), more
# than hud-audit's whole $1 cap. Analyst jobs only use built-in tools.
JOB_FLAGS = ["--strict-mcp-config"]


def run_claude_job(prompt: str, log_file: Path, job_name: str, tools: str, budget_usd: float,
                   allow: list[str] | None = None, max_attempts: int = 3, backoff_s: int = 120,
                   scope: str = "personal", cwd: Path | None = None, optional: bool = False,
                   surface: str | None = None) -> int:
    """Exit code of the last attempt; the caller still asserts its artifact. `cwd` defaults to
    ~/.jarvis, where the jobs always ran (the Claude config and its permissions resolve from it)."""
    out = gateway.run_agent(job_name, gateway.agent.stamp(prompt), tools, allow, budget_usd, scope=scope,
                            cwd=cwd or JARVIS, optional=optional, log_file=log_file, surface=surface,
                            max_attempts=max_attempts, backoff_s=backoff_s, flags=JOB_FLAGS)
    return int(out["code"]) if out["code"] is not None else 1


class Job:
    """The start line and the artifact/receipt assertions every job ends with."""

    def __init__(self, name: str, title: str):
        self.name = name
        self.log = LOG_DIR / f"{name}.log"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_line(self.log, f"\n=== {now_s()} : starting {title} ===")

    def say(self, text: str) -> None:
        log_line(self.log, text)

    def fail(self, text: str) -> int:
        log_line(self.log, f"=== FAILED: {text} ===")
        return 1

    def assert_artifact(self, path: Path, exit_code: int, what: str = "digest") -> int:
        if not path.exists():
            return self.fail(f"no {what} produced. exit code {exit_code}")
        age = (time.time() - path.stat().st_mtime) / 3600
        if age >= 6:
            return self.fail(f"{what} is stale ({age:.1f}h old) - run produced nothing. exit code {exit_code}")
        self.say(f"=== OK: {what} written {age:.1f}h ago, exit code {exit_code} ===")
        return 0
