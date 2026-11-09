# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""seekdb Memory index that answers hybrid searches with one native statement."""

from __future__ import annotations

from typing import Any

from pyobvector import VECTOR
from sqlalchemy import Table, bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemoryCapabilities,
    MemoryProjection,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.artifacts.memory.canonical import validate_embedding
from powercontext.builtin.persistence.memory_index import memory_channel_hits
from powercontext.builtin.persistence.oceanbase.memory_index import (
    OceanBaseMemoryFTSIndex,
    OceanBaseMemoryVectorIndex,
)
from powercontext.builtin.persistence.tags import memory_tag_parameters, memory_tag_sql

# One statement carries both candidate channels: the full-text branch ranks the
# active-head projection through the FULLTEXT index while the vector branch walks
# the HNSW index with the APPROXIMATE top-k hint. Scope, artifact, tag and limit
# filters stay inside the statement so the database never ships candidates the
# caller would discard.
_HYBRID_SEARCH_SQL_TEMPLATE = """
SELECT
    memory_artifact_id,
    head_revision,
    entry_id,
    entry_version_id,
    text,
    distance,
    fts_score,
    channel
FROM (
  (SELECT
      h.memory_artifact_id AS memory_artifact_id,
      h.head_revision AS head_revision,
      h.entry_id AS entry_id,
      h.entry_version_id AS entry_version_id,
      v.text AS text,
      NULL AS distance,
      MATCH(h.searchable_text) AGAINST (:analyzed_query) AS fts_score,
      'fts' AS channel
    FROM pc_memory_entry_heads AS h
    JOIN pc_memory_entry_versions AS v
      ON v.scope_id = h.scope_id
     AND v.memory_artifact_id = h.memory_artifact_id
     AND v.entry_version_id = h.entry_version_id
    WHERE h.scope_id = :scope_id
      AND h.memory_artifact_id IN :memory_artifact_ids
      AND MATCH(h.searchable_text) AGAINST (:analyzed_query)
{fts_tag}    ORDER BY MATCH(h.searchable_text) AGAINST (:analyzed_query) DESC, h.memory_artifact_id, h.entry_id, h.entry_version_id
    LIMIT :candidate_limit)
  UNION ALL
  (SELECT
      m.memory_artifact_id AS memory_artifact_id,
      m.head_revision AS head_revision,
      m.entry_id AS entry_id,
      m.entry_version_id AS entry_version_id,
      v.text AS text,
      l2_distance(m.embedding, :query_vector) AS distance,
      NULL AS fts_score,
      'vector' AS channel
    FROM pc_memory_vector_entries AS m
    JOIN pc_memory_entry_versions AS v
      ON v.scope_id = m.scope_id
     AND v.memory_artifact_id = m.memory_artifact_id
     AND v.entry_version_id = m.entry_version_id
    WHERE m.scope_id = :scope_id
      AND m.memory_artifact_id IN :memory_artifact_ids
{vector_tag}    ORDER BY l2_distance(m.embedding, :query_vector){approximate}
    LIMIT :candidate_limit)
) AS hybrid_candidates
"""


class SeekDBMemoryHybridIndex:
    """seekdb strategy exposing fts, vector and one-statement hybrid retrieval."""

    def __init__(self, profile: EmbeddingProfile) -> None:
        self._fts = OceanBaseMemoryFTSIndex()
        self._vector = OceanBaseMemoryVectorIndex(profile)
        self.profile = self._vector.profile
        self.capabilities = MemoryCapabilities(
            fts=True,
            vector=True,
            hybrid=True,
            tag_filter=True,
            embedding_profile=self.profile,
        )
        self.tables: tuple[Table, ...] = self._fts.tables + self._vector.tables
        dimension = self.profile.dimension
        self._search_sql = _bind_hybrid_sql(
            _HYBRID_SEARCH_SQL_TEMPLATE.format(fts_tag="", vector_tag="", approximate=" APPROXIMATE"),
            dimension,
        )
        self._tagged_search_sql = _bind_hybrid_sql(
            _HYBRID_SEARCH_SQL_TEMPLATE.format(
                fts_tag=memory_tag_sql("h"),
                vector_tag=memory_tag_sql("m"),
                approximate="",
            ),
            dimension,
            tagged=True,
        )

    async def initialize(self, connection: AsyncConnection, /) -> None:
        await self._fts.initialize(connection)
        await self._vector.initialize(connection)

    async def replace(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        await self._vector.replace(connection, scope_id, memory_ref, projections)

    async def delete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        entry_ids: tuple[str, ...],
        /,
    ) -> None:
        await self._vector.delete(connection, scope_id, memory_ref, entry_ids)

    async def upsert(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        await self._vector.upsert(connection, scope_id, memory_ref, projections)

    async def search(
        self,
        connection: AsyncConnection,
        scope_id: str,
        request: MemorySearchRequest,
        /,
    ) -> MemorySearchChannels:
        if request.mode == "fts":
            return await self._fts.search(connection, scope_id, request)
        if request.mode == "vector":
            return await self._vector.search(connection, scope_id, request)
        if request.mode != "hybrid":
            return MemorySearchChannels()
        if request.embedding_profile != self.profile or request.query_vector is None:
            raise CapabilityNotSupportedError("embedding-profile")
        if not await self._vector.vector_complete(connection, scope_id, request.memories, self.profile):
            raise CapabilityNotSupportedError("vector")
        rows = (
            (
                await connection.execute(
                    self._search_sql if request.tag_filter is None else self._tagged_search_sql,
                    {
                        "scope_id": scope_id,
                        "memory_artifact_ids": tuple(memory.artifact_id for memory in request.memories),
                        "analyzed_query": request.analyzed_query,
                        "query_vector": validate_embedding(
                            request.query_vector,
                            dimension=self.profile.dimension,
                        ),
                        "candidate_limit": request.candidate_limit,
                        **memory_tag_parameters(request.tag_filter),
                    },
                )
            )
            .mappings()
            .all()
        )
        # Each branch already carries its ORDER BY and LIMIT, so splitting on the
        # channel marker preserves the per-channel ranking the statement produced;
        # the Python-side sort only makes equal-score ties explicit and stable.
        fts_rows = sorted(
            (row for row in rows if str(row["channel"]) == "fts"),
            key=lambda row: (
                -float(row["fts_score"]),
                str(row["memory_artifact_id"]),
                str(row["entry_id"]),
                str(row["entry_version_id"]),
            ),
        )
        vector_rows = sorted(
            (row for row in rows if str(row["channel"]) == "vector"),
            key=lambda row: (float(row["distance"]),),
        )
        return MemorySearchChannels(
            fts=memory_channel_hits(fts_rows, request.memories),
            vector=memory_channel_hits(vector_rows, request.memories),
        )

    async def vector_complete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memories: tuple[ArtifactRef, ...],
        profile: EmbeddingProfile,
        /,
    ) -> bool:
        return await self._vector.vector_complete(connection, scope_id, memories, profile)

    async def hydrate(
        self,
        connection: AsyncConnection,
        scope_id: str,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> tuple[MemoryProjection, ...]:
        return await self._vector.hydrate(connection, scope_id, projections)


def _bind_hybrid_sql(statement: str, dimension: int, *, tagged: bool = False) -> Any:
    parameters = [
        bindparam("memory_artifact_ids", expanding=True),
        bindparam("query_vector", type_=VECTOR(dimension)),
    ]
    if tagged:
        parameters.extend((bindparam("tag_keys", expanding=True), bindparam("tag_hashes", expanding=True)))
    return text(statement).bindparams(*parameters)
