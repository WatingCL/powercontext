"""JSON file persistence for todoapp.

Implements SPEC-003 (see specs/SPEC-003-persistence.md).
"""

from __future__ import annotations

import json
import os
from typing import List

from .models import Task


class TaskStore:
    """Stores tasks in a JSON file (SPEC-003-A).

    The on-disk format is a JSON object:

        {"tasks": [{"id": "...", "title": "...", ...}, ...]}

    Tasks are keyed by ``id``; saving replaces the whole file atomically
    (SPEC-003-B).
    """

    def __init__(self, path: str):
        self.path = path

    def load(self) -> List[Task]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [Task.from_dict(item) for item in data.get("tasks", [])]

    def save(self, tasks: List[Task]) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump({"tasks": [t.to_dict() for t in tasks]}, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)
