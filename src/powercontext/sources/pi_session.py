"""Lossless Pi v3 branch evidence and durable incremental acquisition."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import cast

from pydantic import BaseModel, JsonValue

from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunSession, ConnectorRunStatus
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class PiSessionInput(BaseModel):
    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _identity(session_id: str, event_id: str) -> str:
    return "pi:" + hashlib.sha256(_canonical([session_id, event_id]).encode("utf-8")).hexdigest()


def _text_blocks(value: JsonValue, *, tools: bool = False) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if block.get("type") == "text" and isinstance(text, str):
            parts.append(text)
        elif tools and block.get("type") == "toolCall":
            parts.append(
                f"[tool_call {block.get('name', '')} {block.get('id', '')}] {_canonical(block.get('arguments', {}))}"
            )
    return "\n".join(parts)


def _visible_event(session_id: str, record: dict[str, JsonValue]) -> PiEventInput | None:
    event_type = cast(str, record["type"])
    role, body = "", ""
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("role"), str):
            raise ValueError("Pi messages must declare a role")  # noqa: TRY003
        role = cast(str, message["role"])
        body = _text_blocks(message.get("content"), tools=True)
        if role == "toolResult":
            body = f"[tool_result {message.get('toolName', '')} {message.get('toolCallId', '')}] {body}"
        elif role == "bashExecution":
            body = f"$ {message.get('command', '')}\n{message.get('output', '')}"
    elif event_type in {"compaction", "branch_summary"}:
        role = event_type
        summary = record.get("summary")
        body = summary if isinstance(summary, str) else ""
    elif event_type == "custom_message":
        role, body = "custom", _text_blocks(record.get("content"))
    if not body.strip():
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=cast(str, record["id"]),
        parent_id=cast(str | None, record["parentId"]),
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")  # noqa: TRY003


def _index_records(records: list[dict[str, JsonValue]]) -> dict[str, dict[str, JsonValue]]:
    by_id: dict[str, dict[str, JsonValue]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Pi records must be JSON objects")  # noqa: TRY003, TRY004
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip() or event_id in by_id:
            raise ValueError("Pi event ids must be non-empty and unique")  # noqa: TRY003
        if not isinstance(record.get("type"), str) or not record["type"]:
            raise ValueError("Pi records must declare a type")  # noqa: TRY003
        if "parentId" not in record:
            raise ValueError("Pi records must declare parentId")  # noqa: TRY003
        parent_id = record["parentId"]
        if parent_id is not None and (not isinstance(parent_id, str) or (parent_id != "" and parent_id not in by_id)):
            raise ValueError("Pi parents must refer to an earlier event")  # noqa: TRY003
        by_id[event_id] = record
    return by_id


def _parse_archive(value: PiSessionInput) -> tuple[str, dict[str, dict[str, JsonValue]], tuple[PiEventInput, ...]]:
    try:
        records = [
            json.loads(line, parse_constant=_reject_constant)
            for line in value.content.decode("utf-8-sig").splitlines()
            if line.strip()
        ]
        if not records or not isinstance(records[0], dict):
            raise ValueError("Pi archive must start with a session header")  # noqa: TRY003
        header = records[0]
        session_id = header.get("id")
        if (
            header.get("type") != "session"
            or type(header.get("version")) is not int
            or header["version"] != 3
            or not isinstance(session_id, str)
            or not session_id.strip()
        ):
            raise ValueError("Pi archive requires a version 3 session with a non-empty id")  # noqa: TRY003
        by_id = _index_records(records[1:])
        last_id = next(reversed(by_id), None)
        leaf = value.leaf_id if value.leaf_id is not None else last_id
        if leaf is not None and leaf not in by_id:
            raise ValueError("Pi leaf does not exist")  # noqa: TRY003
        chain = []
        while leaf:
            record = by_id[leaf]
            chain.append(record)
            leaf = cast(str | None, record["parentId"])
        events = []
        for record in reversed(chain):
            event = _visible_event(session_id, record)
            if event is not None:
                events.append(event)
        return session_id, by_id, tuple(events)
    except (TypeError, KeyError, RecursionError) as error:
        raise ValueError("Invalid Pi session archive") from error  # noqa: TRY003


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Return original visible events on the complete selected ancestor path."""
    return _parse_archive(value)[2]


class PiEventSourceAdapter:
    input_class: type[PiEventInput] = PiEventInput
    source_class: type[PiEventSource] = PiEventSource
    name = "pi-event"

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(
            name=_identity(value.session_id, value.event_id),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput.model_validate(source.model_dump())


class PiEventTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[PiEventSource] = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pi-event",
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PiEventSourceAdapter(), projections=(PiEventTextEvidenceProjection(),)
)


class _PiCheckpoint(BaseModel):
    sessions: dict[str, dict[str, str]] = {}


class PiSessionConnector:
    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({"pi-event"})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        content = await asyncio.to_thread(self.path.read_bytes)
        session_id, records, events = _parse_archive(PiSessionInput(content=content, leaf_id=self.leaf_id))
        checkpoint = _PiCheckpoint.model_validate(session.checkpoint if session.checkpoint is not None else {})
        imported = checkpoint.sessions.setdefault(session_id, {})
        # Validate all previously imported events, including those on another branch,
        # before any writes. A failed run leaves the lifecycle's durable progress intact.
        for event_id, digest in imported.items():
            record = records.get(event_id)
            if record is None or hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest() != digest:
                raise ValueError("Previously imported Pi event was changed or removed")  # noqa: TRY003
        for event in events:
            if event.event_id not in imported:
                await session.submit(_identity(session_id, event.event_id), "pi-event", event)
                imported[event.event_id] = hashlib.sha256(_canonical(event.record).encode("utf-8")).hexdigest()
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint.model_dump(mode="json"))
