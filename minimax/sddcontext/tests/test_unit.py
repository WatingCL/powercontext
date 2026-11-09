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
