"""Domain models for todoapp.

Implements SPEC-001 (see specs/SPEC-001-task-model.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

# Status values allowed by SPEC-001-B.
STATUS_TODO = "todo"
STATUS_DONE = "done"
VALID_STATUSES = (STATUS_TODO, STATUS_DONE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    """A single todo item (SPEC-001-A)."""

    id: str
    title: str
    status: str = STATUS_TODO
    notes: str = ""
    priority: int = 2
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(
            id=data["id"],
            title=data["title"],
            status=data.get("status", STATUS_TODO),
            notes=data.get("notes", ""),
            priority=int(data.get("priority", 2)),
            created_at=data.get("created_at", _now_iso()),
        )
