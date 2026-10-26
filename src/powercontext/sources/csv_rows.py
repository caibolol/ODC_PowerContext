"""Captured CSV rows with stable identities and lossless text evidence."""

from __future__ import annotations

import csv
import io
import json
from typing import Self
from urllib.parse import quote

from pydantic import BaseModel, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


def _validate_document_id(document_id: str) -> None:
    if not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty and have no surrounding whitespace")  # noqa: TRY003


def _validate_columns(columns: tuple[str, ...], primary_key: str) -> int:
    if not columns or any(not column.strip() for column in columns) or len(set(columns)) != len(columns):
        raise ValueError("CSV headers must be non-blank and unique")  # noqa: TRY003
    if not primary_key or primary_key not in columns:
        raise ValueError("primary_key must exactly match a CSV column")  # noqa: TRY003
    return columns.index(primary_key)


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Encode a document and exact primary key as a bounded row identity."""
    _validate_document_id(document_id)
    if not primary_key_value.strip():
        raise ValueError("primary key values must not be blank")  # noqa: TRY003
    identity = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError("CSV row identity exceeds the source ID length limit")  # noqa: TRY003
    return identity


class CSVDocumentInput(BaseModel):
    """One complete offline UTF-8 CSV document."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """An exact row, including its original header and field ordering."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_row(self) -> Self:
        csv_row_source_id(self.document_id, self.primary_key_value)
        key_index = _validate_columns(self.columns, self.primary_key)
        if len(self.values) != len(self.columns):
            raise ValueError("CSV row width must match the header")  # noqa: TRY003
        if self.values[key_index] != self.primary_key_value:
            raise ValueError("primary_key_value must match the row's primary key field")  # noqa: TRY003
        return self


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Validate the whole CSV atomically, preserving all field strings."""
    _validate_document_id(value.document_id)
    try:
        reader = csv.reader(io.StringIO(value.content.decode("utf-8-sig"), newline=""), strict=True)
        columns = tuple(next(reader, ()))
        key_index = _validate_columns(columns, value.primary_key)
        rows: list[CSVRowInput] = []
        seen: set[str] = set()
        for fields in reader:
            # csv.reader distinguishes a physical blank record from a quoted empty field.
            if not fields:
                continue
            if len(fields) != len(columns):
                raise ValueError("CSV row width must match the header")  # noqa: TRY003
            key = fields[key_index]
            if key in seen:
                raise ValueError("CSV primary key values must be unique within a document")  # noqa: TRY003
            rows.append(
                CSVRowInput(
                    document_id=value.document_id,
                    primary_key=value.primary_key,
                    primary_key_value=key,
                    columns=columns,
                    values=tuple(fields),
                )
            )
            seen.add(key)
        return tuple(rows)
    except csv.Error as error:
        raise ValueError("Malformed CSV document") from error  # noqa: TRY003


class CSVRowSource(Source):
    """A captured original CSV record."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSourceAdapter:
    input_class: type[CSVRowInput] = CSVRowInput
    name = "csv-row"
    source_class: type[CSVRowSource] = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        identity = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput.model_validate(source.model_dump())


class CSVRowTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[CSVRowSource] = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type="csv-row",
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    CSVRowSourceAdapter(),
    projections=(CSVRowTextEvidenceProjection(),),
)
