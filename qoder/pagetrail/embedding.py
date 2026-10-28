"""离线确定性嵌入：词元与字符 n-gram 的带符号哈希向量。

不依赖任何外部模型或网络，同一文本在任何平台得到同一向量，
保证评审在干净环境中复现出完全相同的检索结果。
"""

from __future__ import annotations

import hashlib
import math
import re

import pyseekdb

DIMENSION = 512

_WORD = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _tokens(text: str) -> list[tuple[str, float]]:
    lowered = text.lower()
    tokens: list[tuple[str, float]] = [("w:" + word, 1.6) for word in _WORD.findall(lowered)]
    cjk = "".join(_CJK.findall(lowered))
    for i in range(len(cjk) - 1):
        tokens.append(("c2:" + cjk[i : i + 2], 1.0))
        if i + 2 < len(cjk):
            tokens.append(("c3:" + cjk[i : i + 3], 0.6))
    return tokens


def embed(text: str) -> list[float]:
    vector = [0.0] * DIMENSION
    for token, weight in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        hashed = int.from_bytes(digest, "big")
        sign = 1.0 if hashed & 1 else -1.0
        vector[(hashed >> 1) % DIMENSION] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


@pyseekdb.register_embedding_function
class LocalHashEmbedding:
    """pyseekdb 的 EmbeddingFunction 实现。"""

    @staticmethod
    def name() -> str:
        return "pagetrail-local-hash-v1"

    def __call__(self, documents):
        if isinstance(documents, str):
            return [embed(documents)]
        return [embed(document) for document in documents]

    def get_config(self) -> dict:
        return {"dimension": DIMENSION}

    @staticmethod
    def build_from_config(config: dict) -> "LocalHashEmbedding":
        return LocalHashEmbedding()
