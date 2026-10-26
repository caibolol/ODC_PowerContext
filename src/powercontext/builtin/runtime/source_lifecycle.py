"""Durable evidence availability with idempotent native Memory transitions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from sqlalchemy import insert, select, update

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_TABLE
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.sources.models import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime


class SourceLifecycleError(ValueError):
    """Invalid dependency binding, event, or generation access."""


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    node_id: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Lifecycle text must not be blank")  # noqa: TRY003
        return value


class _Node(BaseModel):
    kind: Literal["source", "memory", "topic"]
    reference: dict[str, JsonValue]
    parents: tuple[str, ...] = ()
    policy: Literal["all", "any"] = "all"
    revision: int = 1
    available: bool = True
    last_event: SourceLifecycleEvent | None = None


class _Graph(BaseModel):
    nodes: dict[str, _Node] = Field(default_factory=dict)

    def propagate(self) -> list[str]:
        for node in self.nodes.values():
            if node.parents:
                support = [self.nodes[parent].available for parent in node.parents]
                node.available = all(support) if node.policy == "all" else any(support)
        return sorted(key for key, node in self.nodes.items() if node.available)


class SourceLifecycleApplication:
    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase | None) -> None:
        self.runtime, self.database = runtime, database

    def for_scope(self, scope_id: str):
        from powercontext.builtin.sources import validate_scope_id

        return ScopedSourceLifecycle(self.runtime, self.database, validate_scope_id(scope_id))


class ScopedSourceLifecycle:
    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase | None, scope_id: str) -> None:
        self.runtime, self.database, self.scope_id = runtime, database, scope_id

    def _database(self) -> AsyncDatabase:
        if self.database is None:
            raise SourceLifecycleError("Lifecycle requires persistent runtime storage")  # noqa: TRY003
        return self.database

    async def _load(self) -> _Graph:
        table = SOURCE_LIFECYCLE_TABLE
        async with self._database().transaction() as connection:
            raw = await connection.scalar(select(table.c.payload).where(table.c.scope_id == self.scope_id))
        return _Graph() if raw is None else _Graph.model_validate_json(bytes(raw))

    async def _save(self, graph: _Graph) -> None:
        table = SOURCE_LIFECYCLE_TABLE
        payload = graph.model_dump_json().encode("utf-8")
        async with self._database().transaction() as connection:
            exists = await connection.scalar(select(table.c.scope_id).where(table.c.scope_id == self.scope_id))
            if exists is None:
                await connection.execute(insert(table).values(scope_id=self.scope_id, payload=payload))
            else:
                await connection.execute(update(table).where(table.c.scope_id == self.scope_id).values(payload=payload))

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int = 1) -> None:
        if type(revision) is not int or revision < 1:
            raise SourceLifecycleError("Source revision must be positive")  # noqa: TRY003
        await self._register(
            node_id, _Node(kind="source", reference=source_ref.model_dump(mode="json"), revision=revision)
        )

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, *, parents: tuple[str, ...], policy: str
    ) -> None:
        await self._register_derived(node_id, "memory", citation, parents, policy)

    async def register_topic(
        self, node_id: str, artifact_ref: ArtifactRef, *, parents: tuple[str, ...], policy: str
    ) -> None:
        await self._register_derived(node_id, "topic", artifact_ref, parents, policy)

    async def _register_derived(self, node_id, kind, reference, parents, policy) -> None:
        if policy not in {"all", "any"} or not parents or len(set(parents)) != len(parents):
            raise SourceLifecycleError("Dependencies require distinct parents and an all/any policy")  # noqa: TRY003
        await self._register(
            node_id, _Node(kind=kind, reference=reference.model_dump(mode="json"), parents=parents, policy=policy)
        )

    async def _validate_reference(self, node: _Node) -> None:
        try:
            records = self.runtime.records.for_scope(self.scope_id)
            if node.kind == "source":
                ref = SourceRef.model_validate(node.reference)
                await records.get_source(ref.source_type, ref.source_id)
            elif node.kind == "memory":
                await self.runtime.memory.for_scope(self.scope_id).get(
                    GetMemoryEntryRequest(citation=MemoryCitation.model_validate(node.reference))
                )
            else:
                ref = ArtifactRef.model_validate(node.reference)
                if ref.family != "topic-memory":
                    raise SourceLifecycleError("Topic reference must point to topic-memory")  # noqa: TRY003, TRY301
                await records.get_artifact_revision(ref.family, ref.artifact_id, ref.revision)
        except Exception as error:
            raise SourceLifecycleError("Lifecycle reference must exist in this scope") from error  # noqa: TRY003

    async def _register(self, node_id: str, node: _Node) -> None:
        if not isinstance(node_id, str) or not node_id.strip():
            raise SourceLifecycleError("Node id must not be blank")  # noqa: TRY003
        async with self.runtime._context(self.scope_id), self.runtime._locked(self.scope_id):
            graph = await self._load()
            existing = graph.nodes.get(node_id)
            if existing is not None:
                fields = ("kind", "reference", "parents", "policy", "revision")
                if any(getattr(existing, field) != getattr(node, field) for field in fields):
                    raise SourceLifecycleError("Conflicting lifecycle registration")  # noqa: TRY003
                await self._sync_memory(graph, "lifecycle registration")
                return
            if any(parent not in graph.nodes or parent == node_id for parent in node.parents):
                raise SourceLifecycleError("Parents must be registered before their children")  # noqa: TRY003
            await self._validate_reference(node)
            graph.nodes[node_id] = node
            graph.propagate()
            await self._save(graph)
            await self._sync_memory(graph, "lifecycle registration")

    async def _sync_memory(self, graph: _Graph, reason: str) -> None:
        targets = [node for node in graph.nodes.values() if node.kind == "memory"]
        if not targets:
            return
        async with self.runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            head = await service.head(context.artifacts.memory_artifact_id)
            entries = {entry.entry_id: entry for entry in await service.entries(head)}
            for available in (False, True):
                selected = []
                for node in targets:
                    citation = MemoryCitation.model_validate(node.reference)
                    entry = entries.get(citation.entry_id)
                    if entry is None or entry.entry_version_id != citation.entry_version_id:
                        raise SourceLifecycleError("Registered memory body version changed")  # noqa: TRY003
                    if node.available == available:
                        selected.append(entry)
                if selected:
                    operation = service.reactivate if available else service.forget
                    head = await operation(head, entries=tuple(selected), reason=reason)

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        async with self.runtime._context(self.scope_id), self.runtime._locked(self.scope_id):
            graph = await self._load()
            node = graph.nodes.get(event.node_id)
            if node is None or node.kind != "source" or node.revision != event.revision:
                raise SourceLifecycleError("Unknown source or lifecycle revision")  # noqa: TRY003
            previous = node.last_event
            if previous is not None and (
                event.sequence < previous.sequence or (event.sequence == previous.sequence and event != previous)
            ):
                raise SourceLifecycleError("Lifecycle sequence conflicts with committed history")  # noqa: TRY003
            node.available, node.last_event = event.available, event
            active = graph.propagate()
            # Persist the desired transition first. Replays reconcile native state,
            # so interruption cannot permanently lose downstream state changes.
            await self._save(graph)
            await self._sync_memory(graph, event.reason)
            return active

    async def resolve(self, node_id: str, *, purpose: str):
        graph = await self._load()
        node = graph.nodes.get(node_id)
        if node is None or purpose not in {"generation", "audit"} or (purpose == "generation" and not node.available):
            raise SourceLifecycleError("Node is unavailable for the requested purpose")  # noqa: TRY003
        schema = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[node.kind]
        return schema.model_validate(node.reference)

    async def filter_topics(self, hits):
        if self.database is None:
            return hits
        graph = await self._load()
        blocked = {
            (node.reference["artifact_id"], node.reference["revision"])
            for node in graph.nodes.values()
            if node.kind == "topic" and not node.available
        }
        return tuple(hit for hit in hits if (hit.artifact_ref.artifact_id, hit.artifact_ref.revision) not in blocked)
