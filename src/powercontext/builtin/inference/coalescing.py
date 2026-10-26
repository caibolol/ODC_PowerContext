"""Share in-flight embedding work and cache successful vectors with bounded LRU."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel


@dataclass(frozen=True)
class _Embedded:
    vector: EmbeddingVector
    batch: object
    usage: InferenceUsage


class CoalescingEmbeddingModel:
    def __init__(
        self, model: EmbeddingModel, *, max_batch_size: int = 64, coalesce_ms: float = 5.0, cache_size: int = 1024
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1 or type(cache_size) is not int or cache_size < 0:
            raise ValueError("Batch size must be positive and cache size nonnegative")  # noqa: TRY003
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            raise ValueError("coalesce_ms must be finite and nonnegative")  # noqa: TRY003
        self._model = model
        self._max_batch_size, self._delay, self._cache_size = max_batch_size, coalesce_ms / 1000, cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[_Embedded]] = {}
        self._pending: list[str] = []
        self._timer: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def profile(self):
        return self._model.profile

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        vectors: dict[str, EmbeddingVector] = {}
        waits: dict[str, asyncio.Future[_Embedded]] = {}
        for text in texts:
            if text in self._cache:
                vectors[text] = self._cache[text]
                self._cache.move_to_end(text)
            else:
                future = self._inflight.get(text)
                if future is None:
                    future = asyncio.get_running_loop().create_future()
                    # Consume errors even if every external waiter has been cancelled.
                    future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
                    self._inflight[text] = future
                    self._pending.append(text)
                waits[text] = future
        if self._pending and self._timer is None:
            self._timer = asyncio.create_task(self._flush())
        batches: dict[object, InferenceUsage] = {}
        for text, result in zip(
            waits, await asyncio.gather(*(asyncio.shield(future) for future in waits.values())), strict=True
        ):
            vectors[text] = result.vector
            batches[result.batch] = result.usage

        def tokens(field: str) -> int | None:
            values = [getattr(usage, field) for usage in batches.values()]
            return (
                sum(value for value in values if value is not None)
                if any(value is not None for value in values)
                else None
            )

        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=InferenceUsage(
                requests=sum(usage.requests for usage in batches.values()),
                input_tokens=tokens("input_tokens"),
                output_tokens=tokens("output_tokens"),
            ),
        )

    async def _flush(self) -> None:
        await asyncio.sleep(self._delay)
        pending, self._pending = self._pending, []
        self._timer = None
        for start in range(0, len(pending), self._max_batch_size):
            task = asyncio.create_task(self._embed_batch(tuple(pending[start : start + self._max_batch_size])))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _embed_batch(self, texts: tuple[str, ...]) -> None:
        futures = [self._inflight[text] for text in texts]
        try:
            result = await self._model.embed(texts)
            if len(result.vectors) != len(texts):
                raise ValueError("Embedding vector count does not match batch size")  # noqa: TRY003, TRY301
            batch = object()
            for text, vector, future in zip(texts, result.vectors, futures, strict=True):
                if self._cache_size:
                    self._cache[text] = vector
                    self._cache.move_to_end(text)
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
                future.set_result(_Embedded(vector, batch, result.usage))
        except (Exception, asyncio.CancelledError) as error:
            for future in futures:
                if not future.done():
                    future.set_exception(error)
        finally:
            for text in texts:
                self._inflight.pop(text, None)
