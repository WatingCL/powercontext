"""Target feature tests for task 001: filter tasks by status.

Required by SPEC-002-B (filtering) and SPEC-002-C (invalid value handling).
These tests are EXPECTED TO FAIL before the code change and MUST ALL PASS after it.
The test set itself stays identical before and after the change.
"""

from __future__ import annotations

import pytest

from todoapp.service import TaskService
from todoapp.storage import TaskStore


@pytest.fixture()
def service(tmp_path):
    return TaskService(TaskStore(str(tmp_path / "tasks.json")))


@pytest.fixture()
def seeded(service):
    """Three tasks: two todo, one done."""
    a = service.add_task("buy milk")
    b = service.add_task("write report", notes="quarterly")
    c = service.add_task("ship release")
    service.complete_task(c.id)
    return a, b, c


def test_filter_by_status_todo(seeded, service):
    a, b, c = seeded
    result = service.list_tasks(status="todo")
    assert [t.id for t in result] == [a.id, b.id]


def test_filter_by_status_done(seeded, service):
    a, b, c = seeded
    result = service.list_tasks(status="done")
    assert [t.id for t in result] == [c.id]


def test_filter_default_returns_all(seeded, service):
    a, b, c = seeded
    result = service.list_tasks(status=None)
    assert [t.id for t in result] == [a.id, b.id, c.id]


def test_filter_invalid_status_raises_value_error(seeded, service):
    with pytest.raises(ValueError):
        service.list_tasks(status="bogus")


def test_filter_invalid_status_does_not_modify_storage(seeded, service):
    before = service.list_tasks()
    with pytest.raises(ValueError):
        service.list_tasks(status="finished?")
    after = service.list_tasks()
    assert [t.id for t in before] == [t.id for t in after]
