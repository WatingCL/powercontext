"""Application services for todoapp.

Implements SPEC-002 (see specs/SPEC-002-filtering.md) for query behaviour
and coordinates the store.
"""

from __future__ import annotations

import uuid
from typing import List

from .models import Task, STATUS_TODO
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

    def list_tasks(self) -> List[Task]:
        """Return all tasks in creation order (SPEC-002-A)."""
        return self._store.load()

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
