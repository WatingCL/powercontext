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

"""HTTP cross-encoder reranking adapter for Memory search.

Splits the coarse candidate pool into bounded batches, scores every candidate
exactly once through an HTTP scoring service, and performs one global
selection over the full pool so that a high score in any batch can win.
"""

from __future__ import annotations

import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

HTTP_MEMORY_RERANK_POLICY_VERSION = "http-cross-encoder-v1"


class HTTPMemoryReranker:
    """Rerank Memory candidates with one HTTP scoring service.

    Candidates are sent in batches of at most ``batch_size``; each candidate's
    one-based rank in the full pool is preserved in every request so responses
    can be mapped back to the original hits regardless of batch order.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = HTTP_MEMORY_RERANK_POLICY_VERSION,
    ) -> None:
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every candidate once and globally select the best ``limit`` ranks."""

        candidate_count = len(candidates)
        if candidate_count < 1:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > candidate_count:
            raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003

        scores: dict[int, float] = {}
        request_count = 0
        for start in range(0, candidate_count, self._batch_size):
            batch_ranks = range(start + 1, min(start + self._batch_size, candidate_count) + 1)
            payload = {
                "query": query,
                "candidates": [
                    {"rank": rank, "text": candidates[rank - 1].text} for rank in batch_ranks
                ],
            }
            response = await self._client.post(self._endpoint, json=payload)
            response.raise_for_status()
            batch_scores = _parse_score_response(response, expected_ranks=frozenset(batch_ranks))
            scores.update(batch_scores)
            request_count += 1

        ordered = sorted(scores, key=lambda rank: (-scores[rank], rank))
        selected_ranks = tuple(ordered[:limit])
        return MemoryRerankDecision(
            selected_ranks=selected_ranks,
            usage=InferenceUsage(requests=request_count),
        )


def _parse_score_response(response: httpx.Response, *, expected_ranks: frozenset[int]) -> dict[int, float]:
    """Validate one batch response: exactly ``scores`` covering the batch ranks once."""

    try:
        payload = response.json()
    except ValueError as error:
        raise ValueError("reranker response is not valid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"scores"}:
        raise ValueError("reranker response must contain exactly the 'scores' field")
    records = payload["scores"]
    if not isinstance(records, list):
        raise ValueError("reranker scores must be a list")
    parsed: dict[int, float] = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"rank", "score"}:
            raise ValueError("each score record must contain exactly 'rank' and 'score'")
        rank = record["rank"]
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ValueError("reranker score rank must be an integer")
        score = record["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError("reranker score must be a finite number")
        if rank not in expected_ranks or rank in parsed:
            raise ValueError("reranker scores must cover each batch rank exactly once")
        parsed[rank] = float(score)
    if set(parsed) != set(expected_ranks):
        raise ValueError("reranker scores must cover each batch rank exactly once")
    return parsed


__all__ = [
    "HTTP_MEMORY_RERANK_POLICY_VERSION",
    "HTTPMemoryReranker",
]
