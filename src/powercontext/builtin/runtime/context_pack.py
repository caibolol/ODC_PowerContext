"""Self-contained, checked UTF-8 context packs and prefix deltas."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

_PACK_SCHEMA = "powercontext.context-pack.v1"
_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"


class ContextPackError(ValueError):
    """Invalid context wire data or an unverifiable reconstruction."""


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _encoded(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _validate_items(items: tuple[bytes, ...]) -> None:
    try:
        if not isinstance(items, tuple) or any(not isinstance(item, bytes) for item in items):
            raise ContextPackError("Pack items must be a tuple of bytes")  # noqa: TRY003
        for item in items:
            item.decode("utf-8")
    except UnicodeError as error:
        raise ContextPackError("Pack items must each contain valid UTF-8") from error  # noqa: TRY003


def _decoded(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContextPackError("Expected a Base64 string array")  # noqa: TRY003
    try:
        result = tuple(base64.b64decode(item, validate=True) for item in value)
    except (ValueError, binascii.Error) as error:
        raise ContextPackError("Invalid Base64 items") from error  # noqa: TRY003
    if _encoded(result) != value:
        raise ContextPackError("Noncanonical Base64 items")  # noqa: TRY003
    _validate_items(result)
    return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError("Duplicate wire field")  # noqa: TRY003
        result[key] = value
    return result


def _payload(raw: bytes, schema: str, fields: set[str]) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except (ValueError, UnicodeError, AttributeError, RecursionError) as error:
        raise ContextPackError("Invalid context JSON") from error  # noqa: TRY003
    if not isinstance(value, dict) or set(value) != fields | {"schema"} or value["schema"] != schema:
        raise ContextPackError("Invalid context schema or fields")  # noqa: TRY003
    return value


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class ContextPack:
    items: tuple[bytes, ...]
    digest: str

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        _validate_items(items)
        digest = "sha256:" + hashlib.sha256(_json({"schema": _PACK_SCHEMA, "items": _encoded(items)})).hexdigest()
        return cls(items, digest)

    @classmethod
    def from_content(cls, content: str | None, *, chunk_bytes: int = 512) -> ContextPack:
        if type(chunk_bytes) is not int or chunk_bytes < 1:
            raise ContextPackError("chunk_bytes must be a positive integer")  # noqa: TRY003
        try:
            raw = (content or "").encode("utf-8")
            items = []
            start = 0
            while start < len(raw):
                end = min(start + chunk_bytes, len(raw))
                while end > start:
                    try:
                        raw[start:end].decode("utf-8")
                        break
                    except UnicodeError:
                        end -= 1
                if end == start:
                    raise ContextPackError("chunk_bytes cannot fit a UTF-8 character")  # noqa: TRY003
                items.append(raw[start:end])
                start = end
            return cls.build(tuple(items))
        except (UnicodeError, AttributeError) as error:
            raise ContextPackError("Invalid UTF-8 context") from error  # noqa: TRY003

    def to_bytes(self) -> bytes:
        if self != self.build(self.items):
            raise ContextPackError("Pack digest mismatch")  # noqa: TRY003
        payload = {"schema": _PACK_SCHEMA, "items": _encoded(self.items), "digest": self.digest, "byte_count": 0}
        while True:
            raw = _json(payload)
            if payload["byte_count"] == len(raw):
                return raw
            payload["byte_count"] = len(raw)

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    @classmethod
    def from_bytes(cls, raw: bytes) -> ContextPack:
        payload = _payload(raw, _PACK_SCHEMA, {"items", "digest", "byte_count"})
        pack = cls.build(_decoded(payload["items"]))
        if (
            pack.digest != payload["digest"]
            or type(payload["byte_count"]) is not int
            or payload["byte_count"] != pack.byte_count
        ):
            raise ContextPackError("Pack digest or byte count mismatch")  # noqa: TRY003
        return pack


@dataclass(frozen=True)
class ContextPackDelta:
    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        prefix = 0
        for left, right in zip(base.items, target.items, strict=False):
            if left != right:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    def _validate(self) -> None:
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("Invalid prefix count")  # noqa: TRY003
        if not _valid_digest(self.base_digest) or not _valid_digest(self.target_digest):
            raise ContextPackError("Invalid delta digest")  # noqa: TRY003
        _validate_items(self.appended)

    def to_bytes(self) -> bytes:
        self._validate()
        return _json({
            "schema": _DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encoded(self.appended),
        })

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    @classmethod
    def from_bytes(cls, raw: bytes) -> ContextPackDelta:
        payload = _payload(raw, _DELTA_SCHEMA, {"base_digest", "target_digest", "prefix_items", "appended"})
        delta = cls(
            payload["base_digest"], payload["target_digest"], payload["prefix_items"], _decoded(payload["appended"])
        )
        delta._validate()
        return delta


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    delta._validate()
    if (
        base != ContextPack.build(base.items)
        or base.digest != delta.base_digest
        or delta.prefix_items > len(base.items)
    ):
        raise ContextPackError("Delta base or prefix mismatch")  # noqa: TRY003
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("Delta target digest mismatch")  # noqa: TRY003
    return target
