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

"""Propagate Source withdrawal and restoration through recorded dependencies.

Every Scope owns one evidence DAG. Sources are the roots, Memory entries and
Topic Memories are derived nodes, and each derived node declares whether it
needs *all* of its parents or *any* of them. A lifecycle event moves one Source
and the availability of every descendant is recomputed from that graph, so a
withdrawn Source stops supporting the text it was cited for while a fact that
an independent Source still supports survives untouched.

Withdrawal only changes eligibility. Memory entries are deactivated through the
Memory service (the body and its versions stay readable), Topic Memories stop
being searchable while their Artifact revision stays exactly readable, and both
return when the Source comes back.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.errors import DatabaseClosedError
from powercontext.builtin.persistence.source_lifecycle import (
    LifecycleNodeKind,
    SourceLifecycleRepository,
    StoredLifecycleNode,
)
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.errors import PowerContextError
from powercontext.sources.models import SourceRef
from powercontext._logging import log_safely

if TYPE_CHECKING:
    from powercontext.builtin.persistence.database import AsyncDatabase
    from powercontext.builtin.runtime.application import BuiltinRuntime

logger = logging.getLogger(__name__)

__all__ = [
    "SourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
    "SourceLifecycleService",
    "StoredLifecycleNode",
]

LifecyclePolicy = Literal["all", "any"]
ResolvePurpose = Literal["generation", "audit"]

_SOURCE_LIFECYCLE_REASON = "source-lifecycle"


class SourceLifecycleError(ValueError):
    """A rejected lifecycle registration, event, or resolution."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SourceLifecycleEvent(BaseModel):
    """One immutable Source lifecycle transition.

    ``revision`` identifies the Source lifecycle version the event belongs to,
    while ``sequence`` orders events per Source. Extra fields are rejected so a
    typo can never be silently ignored by the propagating writer.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must be a non-empty, non-blank string")
        return stripped


def _validate_node_id(node_id: str) -> str:
    if not isinstance(node_id, str):
        raise SourceLifecycleError("node-id")
    stripped = node_id.strip()
    if not stripped:
        raise SourceLifecycleError("node-id")
    return stripped


def _validate_parents(node_id: str, parents: Sequence[str]) -> tuple[str, ...]:
    values = tuple(parents)
    if not values:
        raise SourceLifecycleError("parents")
    for parent in values:
        if not isinstance(parent, str) or not parent.strip():
            raise SourceLifecycleError("parents")
        if parent.strip() == node_id:
            raise SourceLifecycleError("cycle")
    if len(set(values)) != len(values):
        raise SourceLifecycleError("parents")
    return values


def _validate_policy(policy: str) -> LifecyclePolicy:
    if policy not in ("all", "any"):
        raise SourceLifecycleError("policy")
    return policy


def _propagate(nodes: Mapping[str, StoredLifecycleNode], overrides: Mapping[str, bool]) -> dict[str, bool]:
    """Recompute every node's availability in registration (topological) order."""

    ordered = sorted(nodes.values(), key=lambda node: node.ordinal)
    states = {node.node_id: node.available for node in ordered}
    states.update(overrides)
    for node in ordered:
        if node.kind == "source":
            continue
        support = [states[parent] for parent in node.parents]
        states[node.node_id] = all(support) if node.policy == "all" else any(support)
    return states


class ScopedSourceLifecycle:
    """Register one Scope's evidence graph and apply Source lifecycle events."""

    def __init__(
        self,
        runtime: BuiltinRuntime,
        database: AsyncDatabase,
        repository: SourceLifecycleRepository,
        scope_id: str,
    ) -> None:
        self._runtime = runtime
        self._database = database
        self._repository = repository
        self.scope_id = scope_id

    async def register_source(self, node_id: str, reference: SourceRef, /, *, revision: int = 1) -> None:
        """Register one Source root at an exact lifecycle revision."""

        node = _validate_node_id(node_id)
        if not isinstance(reference, SourceRef):
            raise SourceLifecycleError("reference")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise SourceLifecycleError("revision")
        await self._require_source(reference)
        async with self._runtime._scoped_operation(self.scope_id):
            async with self._database.transaction() as connection:
                nodes = await self._repository.load(connection, self.scope_id)
                index = {item.node_id: item for item in nodes}
                existing = index.get(node)
                if existing is not None:
                    if (
                        existing.kind == "source"
                        and existing.source_type == reference.source_type
                        and existing.source_id == reference.source_id
                        and existing.source_revision == revision
                    ):
                        return
                    raise SourceLifecycleError("binding")
                await self._repository.create(
                    connection,
                    StoredLifecycleNode(
                        scope_id=self.scope_id,
                        node_id=node,
                        kind="source",
                        policy=None,
                        parents=(),
                        ordinal=len(nodes),
                        available=True,
                        source_revision=revision,
                        last_sequence=None,
                        last_available=None,
                        last_reason=None,
                        source_type=reference.source_type,
                        source_id=reference.source_id,
                        family=None,
                        artifact_id=None,
                        artifact_revision=None,
                        entry_id=None,
                        entry_version_id=None,
                    ),
                )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: Sequence[str],
        policy: str = "all",
    ) -> None:
        """Register one Memory entry backed by the named parents."""

        node = _validate_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("reference")
        normalized = _validate_parents(node, parents)
        chosen = _validate_policy(policy)
        await self._require_memory(citation)
        await self._register_derived(
            node_id=node,
            kind="memory",
            parents=normalized,
            policy=chosen,
            source_type=None,
            source_id=None,
            family=citation.memory_ref.family,
            artifact_id=citation.memory_ref.artifact_id,
            artifact_revision=citation.memory_ref.revision,
            entry_id=citation.entry_id,
            entry_version_id=citation.entry_version_id,
        )

    async def register_topic(
        self,
        node_id: str,
        reference: ArtifactRef,
        /,
        *,
        parents: Sequence[str],
        policy: str = "all",
    ) -> None:
        """Register one Topic Memory revision backed by the named parents."""

        node = _validate_node_id(node_id)
        if not isinstance(reference, ArtifactRef):
            raise SourceLifecycleError("reference")
        normalized = _validate_parents(node, parents)
        chosen = _validate_policy(policy)
        await self._require_artifact(reference)
        await self._register_derived(
            node_id=node,
            kind="topic",
            parents=normalized,
            policy=chosen,
            source_type=None,
            source_id=None,
            family=reference.family,
            artifact_id=reference.artifact_id,
            artifact_revision=reference.revision,
            entry_id=None,
            entry_version_id=None,
        )

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        """Apply one Source event and return every available node in id order."""

        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event")
        replayed = False
        async with self._runtime._scoped_operation(self.scope_id):
            async with self._database.transaction() as connection:
                nodes = await self._repository.load(connection, self.scope_id)
                index = {item.node_id: item for item in nodes}
                node = index.get(event.node_id)
                if node is None or node.kind != "source":
                    raise SourceLifecycleError("unknown-node")
                if node.source_revision != event.revision:
                    raise SourceLifecycleError("revision")
                replayed = self._check_sequence(node, event)
                states = _propagate(index, {node.node_id: event.available})
                if not replayed:
                    changed = {
                        node_id: available
                        for node_id, available in states.items()
                        if index[node_id].available != available
                    }
                    await self._repository.save_availability(connection, self.scope_id, changed)
                    await self._repository.record_event(
                        connection,
                        self.scope_id,
                        node.node_id,
                        revision=event.revision,
                        sequence=event.sequence,
                        available=event.available,
                        reason=event.reason,
                    )
            await self._sync_memory(nodes, states)
        return sorted(node_id for node_id, available in states.items() if available)

    async def resolve(self, node_id: str, /, *, purpose: str) -> SourceRef | MemoryCitation | ArtifactRef:
        """Return a node's original reference for generation or audit use."""

        node = _validate_node_id(node_id)
        if purpose not in ("generation", "audit"):
            raise SourceLifecycleError("purpose")
        async with self._runtime._scoped_operation(self.scope_id):
            async with self._database.transaction() as connection:
                nodes = await self._repository.load(connection, self.scope_id)
            index = {item.node_id: item for item in nodes}
            stored = index.get(node)
            if stored is None:
                raise SourceLifecycleError("unknown-node")
            if purpose == "generation" and not stored.available:
                raise SourceLifecycleError("unavailable")
            return _reference_of(stored)

    async def suspended_topics(self) -> frozenset[str]:
        """Return the Artifact ids of Topic nodes currently withheld from search."""

        async with self._database.transaction() as connection:
            return await self._repository.withdrawn_topics(connection, self.scope_id)

    # -- registration helpers -------------------------------------------------

    async def _register_derived(
        self,
        *,
        node_id: str,
        kind: LifecycleNodeKind,
        parents: tuple[str, ...],
        policy: LifecyclePolicy,
        source_type: str | None,
        source_id: str | None,
        family: str | None,
        artifact_id: str | None,
        artifact_revision: int | None,
        entry_id: str | None,
        entry_version_id: str | None,
    ) -> None:
        async with self._runtime._scoped_operation(self.scope_id):
            async with self._database.transaction() as connection:
                nodes = await self._repository.load(connection, self.scope_id)
                index = {item.node_id: item for item in nodes}
                existing = index.get(node_id)
                if existing is not None:
                    if (
                        existing.kind == kind
                        and existing.parents == parents
                        and existing.policy == policy
                        and existing.family == family
                        and existing.artifact_id == artifact_id
                        and existing.artifact_revision == artifact_revision
                        and existing.entry_id == entry_id
                        and existing.entry_version_id == entry_version_id
                    ):
                        return
                    raise SourceLifecycleError("binding")
                for parent in parents:
                    if parent not in index:
                        raise SourceLifecycleError("unknown-parent")
                created = StoredLifecycleNode(
                    scope_id=self.scope_id,
                    node_id=node_id,
                    kind=kind,
                    policy=policy,
                    parents=parents,
                    ordinal=len(nodes),
                    available=True,
                    source_revision=None,
                    last_sequence=None,
                    last_available=None,
                    last_reason=None,
                    source_type=source_type,
                    source_id=source_id,
                    family=family,
                    artifact_id=artifact_id,
                    artifact_revision=artifact_revision,
                    entry_id=entry_id,
                    entry_version_id=entry_version_id,
                )
                states = _propagate({**index, node_id: created}, {})
                await self._repository.create(
                    connection,
                    StoredLifecycleNode(**{**_as_dict(created), "available": states[node_id]}),
                )
                created = StoredLifecycleNode(**{**_as_dict(created), "available": states[node_id]})
            await self._sync_memory((*nodes, created), states)

    # -- native propagation ---------------------------------------------------

    async def _sync_memory(
        self,
        nodes: Sequence[StoredLifecycleNode],
        states: Mapping[str, bool],
    ) -> None:
        """Make native Memory entry states match the propagated availability."""

        memory_nodes = [node for node in nodes if node.kind == "memory"]
        if not memory_nodes:
            return
        configured = self._runtime.memory is not None
        if not configured:
            raise SourceLifecycleError("memory")
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            artifact_id = context.artifacts.memory_artifact_id
            async with self._runtime._locked(self.scope_id):
                await self._reconcile(service, artifact_id, memory_nodes, states, target="inactive")
                await self._reconcile(service, artifact_id, memory_nodes, states, target="active")

    async def _reconcile(
        self,
        service: Any,
        artifact_id: str,
        nodes: Sequence[StoredLifecycleNode],
        states: Mapping[str, bool],
        *,
        target: Literal["active", "inactive"],
    ) -> None:
        try:
            memory, versions = await service.head_entries(artifact_id)
        except Exception as error:  # noqa: BLE001 - normalized into the lifecycle contract
            raise SourceLifecycleError("memory") from error
        current = {item.entry_id: item.state for item in memory.content.manifest.entries}
        by_entry = {version.entry_id: version for version in versions}
        wanted: list[Any] = []
        for node in nodes:
            desired = "active" if states.get(node.node_id, node.available) else "inactive"
            if desired != target or node.entry_id is None:
                continue
            state = current.get(node.entry_id)
            if state is None:
                raise SourceLifecycleError("missing-entry")
            if state != desired:
                wanted.append(by_entry[node.entry_id])
        if not wanted:
            return
        if target == "active":
            await service.reactivate(memory, entries=tuple(wanted), reason=_SOURCE_LIFECYCLE_REASON)
        else:
            await service.forget(memory, entries=tuple(wanted), reason=_SOURCE_LIFECYCLE_REASON)

    # -- reference checks -----------------------------------------------------

    async def _require_source(self, reference: SourceRef) -> None:
        try:
            await self._runtime.records.for_scope(self.scope_id).get_source(
                reference.source_type,
                reference.source_id,
            )
        except (PowerContextError, LookupError, DatabaseClosedError) as error:
            raise SourceLifecycleError("reference") from error

    async def _require_memory(self, citation: MemoryCitation) -> None:
        try:
            await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=citation))
        except (PowerContextError, LookupError, DatabaseClosedError) as error:
            raise SourceLifecycleError("reference") from error

    async def _require_artifact(self, reference: ArtifactRef) -> None:
        try:
            await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                reference.family,
                reference.artifact_id,
                reference.revision,
            )
        except (PowerContextError, LookupError, DatabaseClosedError) as error:
            raise SourceLifecycleError("reference") from error

    @staticmethod
    def _check_sequence(node: StoredLifecycleNode, event: SourceLifecycleEvent) -> bool:
        """Enforce monotonic per-Source sequences and exact replay semantics."""

        if node.last_sequence is None:
            return False
        if event.sequence < node.last_sequence:
            raise SourceLifecycleError("sequence")
        if event.sequence > node.last_sequence:
            return False
        if event.available != node.last_available or event.reason != node.last_reason:
            raise SourceLifecycleError("sequence")
        # A replay still reconciles native state: an interrupted propagation must
        # be able to finish on retry without creating another Memory revision.
        return True


def _as_dict(node: StoredLifecycleNode) -> dict[str, Any]:
    return {
        "scope_id": node.scope_id,
        "node_id": node.node_id,
        "kind": node.kind,
        "policy": node.policy,
        "parents": node.parents,
        "ordinal": node.ordinal,
        "available": node.available,
        "source_revision": node.source_revision,
        "last_sequence": node.last_sequence,
        "last_available": node.last_available,
        "last_reason": node.last_reason,
        "source_type": node.source_type,
        "source_id": node.source_id,
        "family": node.family,
        "artifact_id": node.artifact_id,
        "artifact_revision": node.artifact_revision,
        "entry_id": node.entry_id,
        "entry_version_id": node.entry_version_id,
    }


def _reference_of(node: StoredLifecycleNode) -> SourceRef | MemoryCitation | ArtifactRef:
    if node.kind == "source":
        if node.source_type is None or node.source_id is None:
            raise SourceLifecycleError("reference")
        return SourceRef(source_type=node.source_type, source_id=node.source_id)
    if node.family is None or node.artifact_id is None or node.artifact_revision is None:
        raise SourceLifecycleError("reference")
    artifact = ArtifactRef(family=node.family, artifact_id=node.artifact_id, revision=node.artifact_revision)
    if node.kind == "topic":
        return artifact
    if node.entry_id is None or node.entry_version_id is None:
        raise SourceLifecycleError("reference")
    return MemoryCitation(
        memory_ref=artifact,
        entry_id=node.entry_id,
        entry_version_id=node.entry_version_id,
    )


class SourceLifecycleService:
    """Own one repository and hand out per-Scope lifecycle services."""

    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase) -> None:
        self._runtime = runtime
        self._database = database
        self._repository = SourceLifecycleRepository()

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self._runtime, self._database, self._repository, scope_id)

    async def withdrawn_topics(self, scope_id: str, /) -> frozenset[str]:
        """Answer Topic search visibility without constructing a Scope service."""

        try:
            async with self._database.transaction() as connection:
                return await self._repository.withdrawn_topics(connection, scope_id)
        except DatabaseClosedError:
            raise
        except Exception as error:  # noqa: BLE001 - search must stay available
            log_safely(
                logger,
                logging.WARNING,
                "Source lifecycle Topic filter failed",
                exc_info=error,
                extra={"event": "source_lifecycle.filter.failed", "outcome": "degraded"},
            )
            return frozenset()


class SourceLifecycleApplication:
    """Select the lifecycle service for one Scope."""

    def __init__(self, runtime: BuiltinRuntime, service: SourceLifecycleService | None) -> None:
        self._runtime = runtime
        self._service = service

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        if self._service is None:
            raise SourceLifecycleError("lifecycle")
        return self._service.for_scope(scope_id)


def suspended_topic_filter(
    search: Callable[..., Awaitable[Any]],
    suspended: Callable[[str], Awaitable[frozenset[str]]],
) -> Callable[..., Awaitable[Any]]:
    """Hide withdrawn Topic revisions from the native Topic search path."""

    async def filtered(scope_id: str, query: str, /, *, limit: int, **kwargs: Any) -> Any:
        hidden = await suspended(scope_id)
        result = await search(scope_id, query, limit=limit, **kwargs)
        if not hidden:
            return result
        hits = tuple(hit for hit in result.hits if hit.artifact_ref.artifact_id not in hidden)
        if len(hits) == len(result.hits):
            return result
        return result.model_copy(update={"hits": hits})

    return filtered
