"""Unit tests for sddcontext (no external services required).

These cover the pure-logic parts: spec parsing, symbol extraction, term
extraction, re-ranking and the MiniMax response parser. Storage runs on the
SQLite smoke backend so the tests work on any OS.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from sddcontext.importer import (  # noqa: E402
    parse_spec_file,
    parse_task_file,
    parse_code_symbols,
    parse_test_cases,
)
from sddcontext.retriever import extract_terms, _rerank  # noqa: E402
from sddcontext.agent import parse_file_blocks  # noqa: E402
from sddcontext.config import Config  # noqa: E402
from sddcontext.store import SqliteStore, open_store, SPEC_TABLE  # noqa: E402
from sddcontext.importer import import_project  # noqa: E402

PROJECT = Path(__file__).parents[1].parent / "project"


@pytest.fixture()
def cfg(tmp_path):
    return Config(project_dir=PROJECT, work_dir=tmp_path / "sdd", store_backend="sqlite")


def test_parse_spec_file_items():
    items = parse_spec_file(PROJECT / "specs" / "SPEC-002-filtering.md", PROJECT)
    keys = [i.item_key for i in items]
    assert keys == ["SPEC-002-A", "SPEC-002-B", "SPEC-002-C", "SPEC-002-D"]
    by_key = {i.item_key: i for i in items}
    assert "status" in by_key["SPEC-002-B"].content
    assert by_key["SPEC-002-C"].spec_id == "SPEC-002"
    assert by_key["SPEC-002-A"].file == "specs/SPEC-002-filtering.md"


def test_parse_code_symbols():
    symbols = parse_code_symbols(PROJECT / "src", PROJECT)
    qualnames = {s.qualname for s in symbols}
    assert "TaskService.list_tasks" in qualnames
    assert "TaskService" in qualnames
    assert "TaskStore.save" in qualnames
    list_symbol = next(s for s in symbols if s.qualname == "TaskService.list_tasks")
    assert list_symbol.file == "src/todoapp/service.py"
    assert list_symbol.line > 0


def test_parse_test_cases_roles():
    cases = parse_test_cases(PROJECT / "tests", PROJECT)
    target = {c.test_name for c in cases if c.role == "target"}
    regression = {c.test_name for c in cases if c.role == "regression"}
    assert "test_filter_by_status_todo" in target
    assert "test_persistence_roundtrip_keeps_format" in regression


def test_parse_task_file():
    task = parse_task_file(PROJECT / "tasks" / "001-add-status-filter.md")
    assert task.task_id == "001"
    assert "状态筛选" in task.title
    assert "list_tasks" in task.goal
    assert task.preserve
    assert "test_filtering.py" in task.verification


def test_extract_terms_mixed_language():
    terms = extract_terms("为 list_tasks 增加 status 状态筛选，保持创建顺序")
    assert "list_tasks" in terms
    assert "status" in terms
    assert any("状态" in t for t in terms)
    assert any("筛选" in t for t in terms)


def test_rerank_prefers_term_hits():
    rows = [
        {"title": "列出全部任务", "content": "returns all"},
        {"title": "按状态筛选", "content": "list_tasks status filter"},
    ]
    ranked = _rerank(rows, ["status", "filter"], 2)
    assert ranked[0]["title"] == "按状态筛选"


def test_parse_file_blocks():
    response = (
        "Some explanation\n\n"
        "### FILE: project/src/todoapp/service.py\n"
        "```python\ndef ok():\n    pass\n```\n"
        "### FILE: minimax/project/src/todoapp/models.py\n"
        "```python\nx = 1\n```"
    )
    blocks = parse_file_blocks(response)
    assert [b["path"] for b in blocks] == [
        "project/src/todoapp/service.py",
        "minimax/project/src/todoapp/models.py",
    ]
    assert blocks[0]["content"] == "def ok():\n    pass\n"


def test_import_project_roundtrip(cfg):
    store = open_store(cfg)
    counts = import_project(cfg, store)
    assert counts["spec_items"] >= 8
    assert counts["code_symbols"] >= 10
    assert counts["test_cases"] >= 10
    assert store.count(SPEC_TABLE) == counts["spec_items"]

    # re-import after a spec change replaces rows (update propagation)
    spec_file = cfg.project_dir / "specs" / "SPEC-002-filtering.md"
    original = spec_file.read_text(encoding="utf-8")
    try:
        spec_file.write_text(
            original.replace("仅返回状态为 `todo` 的任务", "仅返回状态为 `todo` 的任务（修订版）"),
            encoding="utf-8",
        )
        import_project(cfg, store)
        rows = [r for r in store.fetch_all(SPEC_TABLE) if r["item_key"] == "SPEC-002-B"]
        assert "修订版" in rows[0]["content"]
    finally:
        spec_file.write_text(original, encoding="utf-8")
    store.close()


def test_store_search_returns_matching_rows(cfg):
    store = open_store(cfg)
    import_project(cfg, store)
    hits = store.search(SPEC_TABLE, ["筛选", "status"], limit=3)
    assert hits, "search should return candidate rows"
    assert any("status" in (r["title"] + r["content"]) or "筛选" in r["title"] for r in hits)
    store.close()


class TestLiteralCursor:
    """pylibseekdb has no DB-API parameter binding; verify SQL literal inlining."""

    def test_literal_escaping(self):
        from sddcontext.store import _LiteralCursor

        class _FakeCur:
            def __init__(self):
                self.sql = None

            def execute(self, sql):
                self.sql = sql
                return 0

            def fetchall(self):
                return []

            def close(self):
                pass

        fake = _FakeCur()
        cur = _LiteralCursor(fake)
        cur.execute("SELECT * FROM t WHERE a = %s AND b = %s", ("O'Brien", 42))
        assert fake.sql == "SELECT * FROM t WHERE a = 'O''Brien' AND b = 42"
        cur.execute("DELETE FROM t")
        assert fake.sql == "DELETE FROM t"
        cur.executemany("INSERT INTO t VALUES (%s)", [("x",), ("y'y",)])
        assert fake.sql == "INSERT INTO t VALUES ('y''y')"


CANNED_RESPONSE = '''### FILE: project/src/todoapp/service.py
```python
"""Application services for todoapp.

Implements SPEC-002 (see specs/SPEC-002-filtering.md) for query behaviour
and coordinates the store.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from .models import Task, STATUS_TODO, VALID_STATUSES
from .storage import TaskStore


class TaskService:
    """Facade over a TaskStore (SPEC-002-A for list semantics)."""

    def __init__(self, store: TaskStore):
        self._store = store

    def add_task(self, title: str, notes: str = "", priority: int = 2) -> Task:
        if not title or not title.strip():
            raise ValueError("title must not be empty")
        if priority not in (1, 2, 3):
            raise ValueError("priority must be 1, 2 or 3")
        tasks = self._store.load()
        task = Task(
            id=uuid.uuid4().hex[:8],
            title=title.strip(),
            status=STATUS_TODO,
            notes=notes,
            priority=priority,
        )
        tasks.append(task)
        self._store.save(tasks)
        return task

    def list_tasks(self, status: Optional[str] = None) -> List[Task]:
        """Return tasks in creation order, optionally filtered by status."""
        tasks = self._store.load()
        if status is None:
            return tasks
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        return [task for task in tasks if task.status == status]

    def get_task(self, task_id: str) -> Task:
        for task in self._store.load():
            if task.id == task_id:
                return task
        raise KeyError(f"task not found: {task_id}")

    def complete_task(self, task_id: str) -> Task:
        tasks = self._store.load()
        for task in tasks:
            if task.id == task_id:
                task.status = "done"
                self._store.save(tasks)
                return task
        raise KeyError(f"task not found: {task_id}")

    def delete_task(self, task_id: str) -> None:
        tasks = self._store.load()
        remaining = [t for t in tasks if t.id != task_id]
        if len(remaining) == len(tasks):
            raise KeyError(f"task not found: {task_id}")
        self._store.save(remaining)
```
'''


class TestImplementPipeline:
    """The MiniMax -> parse -> apply -> test chain, exercised offline.

    A canned response (what a correct model reply looks like) is fed through
    the real parser and writer, then the business project's tests run on a
    copy - proving the pipeline itself works even before an API call is made.
    """

    def test_apply_changes_rejects_paths_outside_project(self, tmp_path, cfg):
        from sddcontext.agent import MiniMaxError, apply_changes

        project = tmp_path / "project"
        (project / "src").mkdir(parents=True)
        bad_cfg = Config(project_dir=project, work_dir=tmp_path / "sdd",
                         evidence_dir=tmp_path / "evidence", store_backend="sqlite")
        with pytest.raises(MiniMaxError):
            apply_changes(bad_cfg, [{"path": "../../etc/passwd", "content": "x"}],
                          repo_root=tmp_path)

    def test_canned_response_makes_target_tests_pass(self, tmp_path, monkeypatch):
        import shutil
        import subprocess

        from sddcontext import agent as agent_module

        repo = tmp_path / "repo"
        project_copy = repo / "project"
        shutil.copytree(PROJECT, project_copy)
        run_cfg = Config(
            project_dir=project_copy,
            work_dir=tmp_path / "sdd",
            evidence_dir=tmp_path / "evidence",
            store_backend="sqlite",
            minimax_api_key="offline-test-key",
        )

        before = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q"],
            cwd=project_copy, capture_output=True, text=True,
        )
        assert before.returncode == 1, "target tests must fail before the change"

        monkeypatch.setattr(
            agent_module.MiniMaxClient,
            "chat",
            lambda self, system, user, **kwargs: {
                "text": CANNED_RESPONSE,
                "usage": {"total_tokens": 1234},
                "raw": {},
                "model": "offline-canned",
            },
        )
        record = agent_module.implement(
            run_cfg, context_markdown="# offline test context", task_id="001",
            repo_root=repo,
        )
        assert record.changed_files
        assert record.model == "offline-canned"
        assert (tmp_path / "evidence" / "minimax-records").is_dir()

        after = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q"],
            cwd=project_copy, capture_output=True, text=True,
        )
        assert after.returncode == 0, after.stdout + after.stderr
