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

"""Cross-call Embedding request coalescing with a bounded success cache.

One wrapper instance owns the shared state of a family of concurrent callers:
identical texts submitted by the same call, by a coalescing window, or while a
provider request is still in flight share one provider request. Successful
vectors are kept in a bounded LRU cache, while failures stay uncached so that a
later call can retry them.

Waiter isolation matters as much as sharing does. Every caller awaits its own
shielded future, so cancelling one caller never cancels the provider work other
callers are still waiting for, and one failing batch leaves independent batches
untouched. Usage is aggregated per caller from the distinct provider batches
that caller actually waited for, so a cache hit costs no requests.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import EmbeddingProfile
    from powercontext.builtin.inference.protocols import EmbeddingModel

__all__ = ["CoalescingEmbeddingModel"]

_MISSING = object()


@dataclass(slots=True)
class _Batch:
    """One provider request shared by every caller that needs one of its texts."""

    texts: tuple[str, ...]
    waiters: tuple["_Waiter", ...]
    usage: InferenceUsage | None = None


@dataclass(slots=True)
class _Waiter:
    """The per-text handle a caller awaits while its text is unresolved."""

    future: asyncio.Future[EmbeddingVector]
    batch: _Batch | None = None


def _retrieve_exception(future: asyncio.Future[EmbeddingVector]) -> None:
    """Mark a future's exception as observed so abandoned waiters stay quiet."""

    if future.cancelled():
        return
    future.exception()


class CoalescingEmbeddingModel:
    """Merge concurrent Embedding requests and cache successful vectors."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if max_batch_size < 1:
            raise ValueError("max_batch_size must be positive")
        if coalesce_ms < 0:
            raise ValueError("coalesce_ms must not be negative")
        if cache_size < 0:
            raise ValueError("cache_size must not be negative")
        self._model = model
        self.profile: EmbeddingProfile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = coalesce_ms / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._waiters: dict[str, _Waiter] = {}
        self._pending: dict[str, _Waiter] = {}
        self._inflight: dict[str, _Waiter] = {}
        self._flush_task: asyncio.Task[None] | None = None
        self._batch_tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Return one ordered vector per input text, sharing provider work."""

        ordered = tuple(texts)
        if not ordered:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        cached: dict[str, EmbeddingVector | None] = {}
        waiters: dict[str, _Waiter] = {}
        scheduled = False
        for text in dict.fromkeys(ordered):
            vector = self._cached(text)
            if vector is not None:
                cached[text] = vector
                continue
            cached[text] = None
            waiter = self._waiters.get(text)
            if waiter is None:
                waiter = _Waiter(asyncio.get_running_loop().create_future())
                waiter.future.add_done_callback(_retrieve_exception)
                self._waiters[text] = waiter
                self._pending[text] = waiter
                scheduled = True
            waiters[text] = waiter
        if scheduled:
            self._schedule_flush()

        resolved: dict[str, EmbeddingVector] = {}
        for text, waiter in waiters.items():
            resolved[text] = await asyncio.shield(waiter.future)

        return EmbeddingResult(
            vectors=tuple(cached[text] if cached[text] is not None else resolved[text] for text in ordered),
            usage=self._usage(waiters.values()),
        )

    def _schedule_flush(self) -> None:
        """Start the single pending flush, if one is not already running."""

        if self._flush_task is not None:
            return
        self._flush_task = asyncio.get_running_loop().create_task(self._flush())
        self._flush_task.add_done_callback(self._flushed)

    def _flushed(self, task: asyncio.Task[None]) -> None:
        self._flush_task = None
        if task.cancelled():
            return
        task.exception()

    async def _flush(self) -> None:
        """Wait out the coalescing window, then dispatch bounded provider batches."""

        if self._coalesce_seconds > 0:
            await asyncio.sleep(self._coalesce_seconds)
        else:
            # Even a zero window yields once so same-iteration callers can join.
            await asyncio.sleep(0)
        while self._pending:
            queued = tuple(self._pending.items())
            self._pending.clear()
            for start in range(0, len(queued), self._max_batch_size):
                chunk = queued[start : start + self._max_batch_size]
                batch = _Batch(
                    texts=tuple(text for text, _ in chunk),
                    waiters=tuple(waiter for _, waiter in chunk),
                )
                for text, waiter in chunk:
                    waiter.batch = batch
                    self._inflight[text] = waiter
                task = asyncio.get_running_loop().create_task(self._run(batch))
                self._batch_tasks.add(task)
                task.add_done_callback(self._batch_tasks.discard)
            if self._pending:
                await asyncio.sleep(0)

    async def _run(self, batch: _Batch) -> None:
        """Run one provider batch and hand its outcome to every waiter."""

        try:
            result = await self._model.embed(batch.texts)
        except asyncio.CancelledError:
            self._fail(batch, asyncio.CancelledError())
            raise
        except BaseException as error:
            self._fail(batch, error)
            return
        if len(result.vectors) != len(batch.texts):
            self._fail(batch, ValueError("embedding count does not match batch size"))
            return
        batch.usage = result.usage
        for text, waiter, vector in zip(batch.texts, batch.waiters, result.vectors, strict=True):
            self._resolve(text, waiter, vector)

    def _fail(self, batch: _Batch, error: BaseException) -> None:
        """Propagate a batch failure without caching it or touching other batches."""

        for text, waiter in zip(batch.texts, batch.waiters, strict=True):
            if self._inflight.get(text) is waiter:
                del self._inflight[text]
            if self._waiters.get(text) is waiter:
                del self._waiters[text]
            if not waiter.future.done():
                waiter.future.set_exception(error)

    def _resolve(self, text: str, waiter: _Waiter, vector: EmbeddingVector) -> None:
        """Publish one successful vector and remember it for later callers."""

        if self._inflight.get(text) is waiter:
            del self._inflight[text]
        if self._waiters.get(text) is waiter:
            del self._waiters[text]
        self._store(text, vector)
        if not waiter.future.done():
            waiter.future.set_result(vector)

    def _cached(self, text: str) -> EmbeddingVector | None:
        """Return a cached vector and mark it as the most recently used entry."""

        if self._cache_size <= 0:
            return None
        vector = self._cache.get(text, _MISSING)
        if vector is _MISSING:
            return None
        self._cache.move_to_end(text)
        return vector  # type: ignore[return-value]

    def _store(self, text: str, vector: EmbeddingVector) -> None:
        """Cache a successful vector, evicting the least recently used entry."""

        if self._cache_size <= 0:
            return
        self._cache[text] = vector
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    @staticmethod
    def _usage(waiters: Iterable[_Waiter]) -> InferenceUsage:
        """Sum each distinct provider batch the caller waited for exactly once."""

        batches: dict[int, _Batch] = {}
        for waiter in waiters:
            batch = waiter.batch
            if batch is not None:
                batches[id(batch)] = batch
        requests = 0
        input_tokens = 0
        output_tokens = 0
        has_input = False
        has_output = False
        for batch in batches.values():
            usage = batch.usage
            if usage is None:
                continue
            requests += usage.requests
            if usage.input_tokens is not None:
                input_tokens += usage.input_tokens
                has_input = True
            if usage.output_tokens is not None:
                output_tokens += usage.output_tokens
                has_output = True
        return InferenceUsage(
            requests=requests,
            input_tokens=input_tokens if has_input else None,
            output_tokens=output_tokens if has_output else None,
        )
