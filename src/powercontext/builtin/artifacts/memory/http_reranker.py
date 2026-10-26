"""HTTP scoring adapter with global rank preservation across batches."""

from __future__ import annotations

import math
from collections.abc import Sequence

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference.models import InferenceUsage


class HTTPMemoryReranker:
    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self.endpoint, self.client, self.batch_size, self.policy_id = endpoint, client, batch_size, policy_id

    async def rerank(self, query: str, candidates: Sequence[MemoryHit], limit: int) -> MemoryRerankDecision:
        if not candidates or type(limit) is not int or not 1 <= limit <= len(candidates):
            raise ValueError("limit must select at least one candidate from a non-empty pool")  # noqa: TRY003
        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, len(candidates), self.batch_size):
            batch = [
                {"rank": index + 1, "text": candidates[index].text}
                for index in range(start, min(start + self.batch_size, len(candidates)))
            ]
            response = await self.client.post(self.endpoint, json={"query": query, "candidates": batch})
            requests += 1
            response.raise_for_status()
            scores.update(_batch_scores(response.json(), set(range(start + 1, start + len(batch) + 1))))
        ranks = tuple(sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit])
        return MemoryRerankDecision(selected_ranks=ranks, usage=InferenceUsage(requests=requests))


def _batch_scores(payload: object, expected: set[int]) -> dict[int, float]:
    if not isinstance(payload, dict) or set(payload) != {"scores"} or not isinstance(payload["scores"], list):
        raise ValueError("HTTP scoring response must contain only a scores list")  # noqa: TRY003
    scores = {}
    for item in payload["scores"]:
        if not isinstance(item, dict) or set(item) != {"rank", "score"}:
            raise ValueError("Every scoring record must contain only rank and score")  # noqa: TRY003
        rank, score = item["rank"], item["score"]
        if type(rank) is not int or rank not in expected or rank in scores:
            raise ValueError("Scoring response has invalid or duplicate ranks")  # noqa: TRY003
        if type(score) not in {int, float} or not math.isfinite(score):
            raise ValueError("Scores must be finite numeric values")  # noqa: TRY003
        scores[rank] = float(score)
    if set(scores) != expected:
        raise ValueError("Scoring response must cover exactly its request batch")  # noqa: TRY003
    return scores
