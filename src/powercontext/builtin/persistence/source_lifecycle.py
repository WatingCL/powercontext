# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Persistence for Source lifecycle registrations, events, and propagated state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.persistence.tables import (
    SOURCE_LIFECYCLE_EVENTS_TABLE,
    SOURCE_LIFECYCLE_NODES_TABLE,
)

LifecycleNodeKind = Literal["source", "memory", "topic"]


@dataclass(frozen=True)
class StoredLifecycleNode:
    """One registered node with its reference and last applied Source event."""

    scope_id: str
    node_id: str
    kind: LifecycleNodeKind
    policy: str | None
    parents: tuple[str, ...]
    ordinal: int
    available: bool
    source_revision: int | None
    last_sequence: int | None
    last_available: bool | None
    last_reason: str | None
    source_type: str | None
    source_id: str | None
    family: str | None
    artifact_id: str | None
    artifact_revision: int | None
    entry_id: str | None
    entry_version_id: str | None


def _parents_text(parents: tuple[str, ...]) -> str:
    return json.dumps(list(parents), ensure_ascii=False, separators=(",", ":"))


def _decode_parents(value: object) -> tuple[str, ...]:
    decoded = json.loads(str(value))
    return tuple(str(item) for item in decoded)


def _decode(row: object) -> StoredLifecycleNode:
    values = cast("dict[str, object]", dict(row))  # type: ignore[arg-type]
    return StoredLifecycleNode(
        scope_id=str(values["scope_id"]),
        node_id=str(values["node_id"]),
        kind=cast(LifecycleNodeKind, str(values["kind"])),
        policy=None if values["policy"] is None else str(values["policy"]),
        parents=_decode_parents(values["parents"]),
        ordinal=int(values["ordinal"]),  # type: ignore[arg-type]
        available=bool(values["available"]),
        source_revision=None if values["source_revision"] is None else int(values["source_revision"]),  # type: ignore[arg-type]
        last_sequence=None if values["last_sequence"] is None else int(values["last_sequence"]),  # type: ignore[arg-type]
        last_available=None if values["last_available"] is None else bool(values["last_available"]),
        last_reason=None if values["last_reason"] is None else str(values["last_reason"]),
        source_type=None if values["source_type"] is None else str(values["source_type"]),
        source_id=None if values["source_id"] is None else str(values["source_id"]),
        family=None if values["family"] is None else str(values["family"]),
        artifact_id=None if values["artifact_id"] is None else str(values["artifact_id"]),
        artifact_revision=None if values["artifact_revision"] is None else int(values["artifact_revision"]),  # type: ignore[arg-type]
        entry_id=None if values["entry_id"] is None else str(values["entry_id"]),
        entry_version_id=None if values["entry_version_id"] is None else str(values["entry_version_id"]),
    )


class SourceLifecycleRepository:
    """Read and write lifecycle state inside a caller-owned transaction."""

    async def load(self, connection: AsyncConnection, scope_id: str, /) -> tuple[StoredLifecycleNode, ...]:
        """Return every registered node in registration order."""

        rows = (
            await connection.execute(
                select(SOURCE_LIFECYCLE_NODES_TABLE)
                .where(SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id)
                .order_by(SOURCE_LIFECYCLE_NODES_TABLE.c.ordinal)
            )
        ).mappings()
        return tuple(_decode(row) for row in rows)

    async def create(self, connection: AsyncConnection, node: StoredLifecycleNode, /) -> None:
        """Insert one freshly validated registration."""

        await connection.execute(
            insert(SOURCE_LIFECYCLE_NODES_TABLE).values(
                scope_id=node.scope_id,
                node_id=node.node_id,
                kind=node.kind,
                policy=node.policy,
                parents=_parents_text(node.parents),
                ordinal=node.ordinal,
                available=node.available,
                source_revision=node.source_revision,
                last_sequence=None,
                last_available=None,
                last_reason=None,
                source_type=node.source_type,
                source_id=node.source_id,
                family=node.family,
                artifact_id=node.artifact_id,
                artifact_revision=node.artifact_revision,
                entry_id=node.entry_id,
                entry_version_id=node.entry_version_id,
            )
        )

    async def save_availability(self, connection: AsyncConnection, scope_id: str, states: dict[str, bool], /) -> None:
        """Persist propagation results for every node whose state moved."""

        for node_id, available in states.items():
            await connection.execute(
                update(SOURCE_LIFECYCLE_NODES_TABLE)
                .where(
                    SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
                    SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node_id,
                )
                .values(available=available)
            )

    async def record_event(
        self,
        connection: AsyncConnection,
        scope_id: str,
        node_id: str,
        /,
        *,
        revision: int,
        sequence: int,
        available: bool,
        reason: str,
    ) -> None:
        """Persist one applied event and advance the Source's replay cursor."""

        await connection.execute(
            insert(SOURCE_LIFECYCLE_EVENTS_TABLE).values(
                scope_id=scope_id,
                node_id=node_id,
                sequence=sequence,
                revision=revision,
                available=available,
                reason=reason,
            )
        )
        await connection.execute(
            update(SOURCE_LIFECYCLE_NODES_TABLE)
            .where(
                SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
                SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node_id,
            )
            .values(last_sequence=sequence, last_available=available, last_reason=reason)
        )

    async def withdrawn_topics(self, connection: AsyncConnection, scope_id: str, /) -> frozenset[str]:
        """Return Artifact identities of Topic nodes currently withheld from search."""

        rows = (
            await connection.execute(
                select(SOURCE_LIFECYCLE_NODES_TABLE.c.artifact_id).where(
                    SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
                    SOURCE_LIFECYCLE_NODES_TABLE.c.kind == "topic",
                    SOURCE_LIFECYCLE_NODES_TABLE.c.available.is_(False),
                    SOURCE_LIFECYCLE_NODES_TABLE.c.artifact_id.is_not(None),
                )
            )
        ).scalars()
        return frozenset(str(value) for value in rows)

    async def clear(self, connection: AsyncConnection, scope_id: str, /) -> None:
        """Remove all lifecycle state for one Scope; used by Scope deletion."""

        await connection.execute(
            delete(SOURCE_LIFECYCLE_NODES_TABLE).where(SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id)
        )
        await connection.execute(
            delete(SOURCE_LIFECYCLE_EVENTS_TABLE).where(SOURCE_LIFECYCLE_EVENTS_TABLE.c.scope_id == scope_id)
        )


__all__ = ["LifecycleNodeKind", "SourceLifecycleRepository", "StoredLifecycleNode"]
