"""Runtime configuration, read from environment variables.

All values have working defaults so the module runs out of the box; override
any of them through environment variables or a `.env` file loaded by the
runner script.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(key: str, default: str) -> str:
    value = os.environ.get(key, "").strip()
    return value or default


@dataclass
class Config:
    # Business project to index (contains src/, specs/, tests/, tasks/)
    project_dir: Path = field(default_factory=lambda: Path(_env("SDD_PROJECT_DIR", "project")))

    # Storage backend: "seekdb" (embedded, Linux) | "mysql" (seekdb server /
    # OceanBase over MySQL protocol) | "sqlite" (local smoke tests only)
    store_backend: str = field(default_factory=lambda: _env("SDD_STORE_BACKEND", "seekdb"))

    # Embedded seekdb data path
    seekdb_path: str = field(default_factory=lambda: _env("SDD_SEEKDB_PATH", ".sdd/seekdb"))
    # MySQL-style URL for seekdb server or OceanBase, e.g.
    # mysql://root@127.0.0.1:2881/sdd?... (used when store_backend == "mysql")
    store_mysql_url: str = field(default_factory=lambda: _env("SDD_STORE_MYSQL_URL", ""))

    # Where module-local state (scope cache) lives
    work_dir: Path = field(default_factory=lambda: Path(_env("SDD_WORK_DIR", ".sdd")))

    # PowerContext server
    powercontext_url: str = field(
        default_factory=lambda: _env("POWERCONTEXT_URL", "http://127.0.0.1:8000")
    )

    # MiniMax
    minimax_base_url: str = field(
        default_factory=lambda: _env("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
    )
    minimax_api_key: str = field(default_factory=lambda: _env("MINIMAX_API_KEY", ""))
    minimax_model: str = field(default_factory=lambda: _env("MINIMAX_MODEL", "MiniMax-M2"))

    # Evidence artefacts (logs, records, diffs)
    evidence_dir: Path = field(default_factory=lambda: Path(_env("SDD_EVIDENCE_DIR", "evidence")))

    def ensure_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    @property
    def specs_dir(self) -> Path:
        return self.project_dir / "specs"

    @property
    def src_dir(self) -> Path:
        return self.project_dir / "src"

    @property
    def tests_dir(self) -> Path:
        return self.project_dir / "tests"

    @property
    def tasks_dir(self) -> Path:
        return self.project_dir / "tasks"
