"""Regression tests for todoapp existing behaviour.

These tests must pass BEFORE and AFTER task 001 (see tasks/001-add-status-filter.md).
They pin the behaviour required by SPEC-001 / SPEC-002-A / SPEC-003.
"""

from __future__ import annotations

import json
import os

import pytest

from todoapp.models import Task, STATUS_TODO
from todoapp.service import TaskService
from todoapp.storage import TaskStore


@pytest.fixture()
def store_path(tmp_path):
    return str(tmp_path / "tasks.json")


@pytest.fixture()
def service(store_path):
    return TaskService(TaskStore(store_path))


def test_add_task_returns_created_task(service):
    task = service.add_task("write spec", notes="first", priority=1)
    assert task.title == "write spec"
    assert task.status == STATUS_TODO
    assert task.priority == 1
    assert task.notes == "first"
    assert task.id


def test_add_task_rejects_empty_title(service):
    with pytest.raises(ValueError):
        service.add_task("   ")


def test_add_task_rejects_invalid_priority(service):
    with pytest.raises(ValueError):
        service.add_task("bad", priority=9)


def test_list_tasks_returns_all_in_creation_order(service):
    first = service.add_task("first")
    second = service.add_task("second")
    third = service.add_task("third")
    tasks = service.list_tasks()
    assert [t.id for t in tasks] == [first.id, second.id, third.id]


def test_complete_task_changes_status(service):
    task = service.add_task("to finish")
    done = service.complete_task(task.id)
    assert done.status == "done"
    assert service.get_task(task.id).status == "done"


def test_delete_task_removes_it(service):
    task = service.add_task("gone soon")
    service.delete_task(task.id)
    with pytest.raises(KeyError):
        service.get_task(task.id)


def test_unknown_task_id_raises(service):
    with pytest.raises(KeyError):
        service.complete_task("nope")
    with pytest.raises(KeyError):
        service.delete_task("nope")
    with pytest.raises(KeyError):
        service.get_task("nope")


def test_persistence_roundtrip_keeps_format(store_path):
    svc = TaskService(TaskStore(store_path))
    t = svc.add_task("persisted", notes="keep format")
    svc.complete_task(t.id)

    # SPEC-003-A: JSON object with "tasks" array
    with open(store_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert set(data.keys()) == {"tasks"}
    assert data["tasks"][0]["title"] == "persisted"
    assert data["tasks"][0]["status"] == "done"

    # reload from disk via a new service instance
    svc2 = TaskService(TaskStore(store_path))
    loaded = svc2.list_tasks()
    assert len(loaded) == 1
    assert isinstance(loaded[0], Task)
    assert loaded[0].status == "done"


def test_load_missing_file_returns_empty(store_path):
    assert not os.path.exists(store_path)
    assert TaskStore(store_path).load() == []
