"""Regression checks for cancellation isolation and interrupted lifecycle writes."""

import asyncio
import sqlite3

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft


def test_late_embedding_waiters_share_work_and_other_batches_survive_failure():
    class Provider:
        profile = EmbeddingProfile(profile_id="recovery", model="offline", dimension=1)

        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = []

        async def embed(self, texts):
            self.calls.append(texts)
            if texts == ("bad",):
                raise ValueError("controlled failed batch")  # noqa: TRY003
            self.started.set()
            await self.release.wait()
            return EmbeddingResult(vectors=((1.0,),), usage=InferenceUsage(requests=3, input_tokens=7))

    async def run():
        base = Provider()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, cache_size=0, coalesce_ms=0)
        first = asyncio.create_task(model.embed(("shared",)))
        await base.started.wait()
        late = asyncio.create_task(model.embed(("shared", "shared")))
        with pytest.raises(ValueError):
            await model.embed(("bad",))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        base.release.set()
        result = await late
        assert result.vectors == ((1.0,), (1.0,))
        assert result.usage.requests == 3 and result.usage.input_tokens == 7
        assert base.calls.count(("shared",)) == 1
        await model.embed(("shared",))
        assert base.calls.count(("shared",)) == 2

    asyncio.run(run())


def test_lifecycle_replay_recovers_after_real_native_write_failure(tmp_path):
    async def run():
        path = tmp_path / "recovery.db"
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{path}"))
        async with open_builtin_runtime(config) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="Recovery", summary="Evidence", idempotency_key="recovery")
            )
            sid = scope.scope_id
            source = await runtime.sources.for_scope(sid).capture(
                CaptureSource(source_id="root", content="Original evidence", metadata={})
            )
            memory = runtime.memory.for_scope(sid)
            created = await memory.remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text="Supported fact"),))
            )
            assert created.entry is not None
            citation = created.entry.citation
            lifecycle = runtime.lifecycle.for_scope(sid)
            await lifecycle.register_source("root", source.source_ref, revision=1)
            await lifecycle.register_memory("fact", citation, parents=("root",), policy="all")
            event = SourceLifecycleEvent(node_id="root", revision=1, sequence=1, available=False, reason="Withdraw")
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_memory BEFORE INSERT ON pc_artifacts WHEN NEW.family='memory' BEGIN SELECT RAISE(ABORT,'controlled'); END"
                )
            with pytest.raises(Exception, match="controlled"):
                await lifecycle.apply(event)
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TRIGGER fail_memory")
        async with open_builtin_runtime(config) as runtime:
            lifecycle = runtime.lifecycle.for_scope(sid)
            assert await lifecycle.apply(event) == []
            memory = runtime.memory.for_scope(sid)
            assert (await memory.list()).entries == ()
            before = (await memory.list()).memory_ref
            await lifecycle.apply(event)
            assert (await memory.list()).memory_ref == before
            assert (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text == "Supported fact"
            restored = event.model_copy(update={"sequence": 2, "available": True})
            assert await lifecycle.apply(restored) == ["fact", "root"]
            assert len((await memory.list()).entries) == 1

    asyncio.run(run())
