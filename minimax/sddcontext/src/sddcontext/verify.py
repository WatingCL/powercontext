"""Test runner used for the "verify" step.

Runs pytest inside the business project, records the command, exit code,
code version (git commit) and full output into ``evidence/logs/`` so the
before/after behaviour required by the task statement is auditable.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .config import Config


@dataclass
class VerifyResult:
    label: str
    command: str
    exit_code: int
    passed: int = 0
    failed: int = 0
    errors: int = 0
    log_file: str = ""
    commit: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _git_commit(project_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_dir, capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def run_tests(cfg: Config, label: str, extra_args: Optional[List[str]] = None) -> VerifyResult:
    args = ["-m", "pytest", "tests/", "-v"]
    if extra_args:
        args.extend(extra_args)
    command = "python " + " ".join(args)
    proc = subprocess.run(
        ["python", *args[1:]],
        cwd=str(cfg.project_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    output = proc.stdout + proc.stderr

    passed = failed = errors = 0
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.endswith("PASSED") or " PASSED" in stripped:
            passed += 1
        elif stripped.endswith("FAILED") or " FAILED" in stripped:
            failed += 1
        elif stripped.endswith("ERROR") or " ERROR" in stripped:
            errors += 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cfg.evidence_dir.mkdir(parents=True, exist_ok=True)
    log_dir = cfg.evidence_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{label}-{stamp}.log"
    log_file.write_text(
        f"command: {command}\n"
        f"exit_code: {proc.returncode}\n"
        f"commit: {_git_commit(cfg.project_dir)}\n"
        f"time: {datetime.now(timezone.utc).isoformat()}\n"
        + "-" * 70 + "\n"
        + output,
        encoding="utf-8",
    )
    return VerifyResult(
        label=label,
        command=command,
        exit_code=proc.returncode,
        passed=passed,
        failed=failed,
        errors=errors,
        log_file=str(log_file),
        commit=_git_commit(cfg.project_dir),
    )
