"""One native seekdb statement for ordered full-text and vector candidates."""

from __future__ import annotations

from pyobvector import VECTOR
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection
from typing_extensions import override

from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.artifacts.memory.canonical import validate_embedding
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex, memory_channel_hits
from powercontext.builtin.persistence.oceanbase.memory_index import OceanBaseMemoryFTSIndex, OceanBaseMemoryVectorIndex
from powercontext.builtin.persistence.tags import memory_tag_parameters, memory_tag_sql


class SeekDBMemoryHybridIndex(CompositeMemoryIndex):
    def __init__(self, profile: EmbeddingProfile) -> None:
        self.vector = OceanBaseMemoryVectorIndex(profile)
        super().__init__(OceanBaseMemoryFTSIndex(), self.vector)
        self._queries = {tagged: self._statement(profile.dimension, tagged) for tagged in (False, True)}

    @staticmethod
    def _statement(dimension: int, tagged: bool):
        tag_clause = memory_tag_sql("m") if tagged else ""
        approximate = "" if tagged else " APPROXIMATE"
        sql = f"""
SELECT * FROM (
  SELECT 'fts' AS channel, m.memory_artifact_id, m.head_revision,
         m.entry_id, m.entry_version_id, v.text, NULL AS distance,
         MATCH(m.searchable_text) AGAINST(:query) AS ordering_score
  FROM pc_memory_entry_heads AS m
  JOIN pc_memory_entry_versions AS v
    ON v.scope_id=m.scope_id AND v.memory_artifact_id=m.memory_artifact_id
   AND v.entry_version_id=m.entry_version_id
  WHERE m.scope_id=:scope_id AND m.memory_artifact_id IN :memory_artifact_ids
    AND MATCH(m.searchable_text) AGAINST(:query)
    {tag_clause}
  ORDER BY ordering_score DESC, m.memory_artifact_id, m.entry_id, m.entry_version_id
  LIMIT :candidate_limit
) AS lexical
UNION ALL
SELECT * FROM (
  SELECT 'vector' AS channel, m.memory_artifact_id, m.head_revision,
         m.entry_id, m.entry_version_id, v.text,
         l2_distance(m.embedding, :query_vector) AS distance,
         -l2_distance(m.embedding, :query_vector) AS ordering_score
  FROM pc_memory_vector_entries AS m
  JOIN pc_memory_entry_versions AS v
    ON v.scope_id=m.scope_id AND v.memory_artifact_id=m.memory_artifact_id
   AND v.entry_version_id=m.entry_version_id
  WHERE m.scope_id=:scope_id AND m.memory_artifact_id IN :memory_artifact_ids
    {tag_clause}
  ORDER BY l2_distance(m.embedding, :query_vector){approximate}
  LIMIT :candidate_limit
) AS semantic
ORDER BY channel, ordering_score DESC, memory_artifact_id, entry_id, entry_version_id
"""  # noqa: S608 - clauses are fixed SQL; all data uses bound parameters
        parameters = [
            bindparam("memory_artifact_ids", expanding=True),
            bindparam("query_vector", type_=VECTOR(dimension)),
        ]
        if tagged:
            parameters.extend((bindparam("tag_keys", expanding=True), bindparam("tag_hashes", expanding=True)))
        return text(sql).bindparams(*parameters)

    @override
    async def search(
        self, connection: AsyncConnection, scope_id: str, request: MemorySearchRequest, /
    ) -> MemorySearchChannels:
        if request.mode != "hybrid":
            return await super().search(connection, scope_id, request)
        if request.embedding_profile != self.vector.profile or request.query_vector is None:
            raise CapabilityNotSupportedError("embedding-profile")
        if not await self.vector.vector_complete(connection, scope_id, request.memories, self.vector.profile):
            raise CapabilityNotSupportedError("vector")
        rows = (
            (
                await connection.execute(
                    self._queries[request.tag_filter is not None],
                    {
                        "scope_id": scope_id,
                        "memory_artifact_ids": tuple(memory.artifact_id for memory in request.memories),
                        "query": request.analyzed_query,
                        "query_vector": validate_embedding(
                            request.query_vector, dimension=self.vector.profile.dimension
                        ),
                        "candidate_limit": request.candidate_limit,
                        **memory_tag_parameters(request.tag_filter),
                    },
                )
            )
            .mappings()
            .all()
        )
        return MemorySearchChannels(
            fts=memory_channel_hits((row for row in rows if row["channel"] == "fts"), request.memories),
            vector=memory_channel_hits((row for row in rows if row["channel"] == "vector"), request.memories),
        )
