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

"""Row-level CSV Source: parse offline documents into per-row captured evidence."""

from __future__ import annotations

import csv
import io
import json
from typing import ClassVar
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

CSV_ROW_SOURCE_NAME = "csv-row"


class CSVDocumentInput(BaseModel):
    """One complete offline CSV document awaiting atomic row parsing."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One parsed data row that preserves header order and raw field values."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """One captured CSV row whose identity is document plus primary key value."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def _validate_document_id(value: object) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("document_id must be non-empty without leading or trailing whitespace")  # noqa: TRY003


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Build the stable row identity from percent-encoded identity components."""

    _validate_document_id(document_id)
    if not primary_key_value:
        raise ValueError("primary_key_value must be non-empty")  # noqa: TRY003
    source_id = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse one complete CSV document atomically: all rows or ``ValueError``."""

    _validate_document_id(value.document_id)
    if not value.primary_key:
        raise ValueError("primary_key must be non-empty")  # noqa: TRY003

    # Strict UTF-8 decode that accepts a leading UTF-8 BOM.
    try:
        text = value.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"document is not valid UTF-8: {error}") from None

    # ``newline=''`` keeps CRLF inside quoted fields; ``strict=True`` rejects malformed quoting.
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        records = list(reader)
    except csv.Error as error:
        raise ValueError(f"malformed CSV: {error}") from None

    if not records or not records[0]:
        raise ValueError("document must contain a non-empty header record")  # noqa: TRY003

    columns = tuple(records[0])
    seen_columns: set[str] = set()
    for column in columns:
        if not column or not column.strip():
            raise ValueError("header columns must be non-empty and not whitespace-only")  # noqa: TRY003
        if column in seen_columns:
            raise ValueError(f"duplicate header column: {column!r}")  # noqa: TRY003
        seen_columns.add(column)

    if value.primary_key not in seen_columns:
        raise ValueError(f"primary_key column {value.primary_key!r} not found in header")  # noqa: TRY003

    key_index = columns.index(value.primary_key)
    seen_keys: set[str] = set()
    rows: list[CSVRowInput] = []
    for record in records[1:]:
        if not record:
            # Completely blank physical records are ignored.
            continue
        if len(record) != len(columns):
            raise ValueError("data record width does not match the header")  # noqa: TRY003
        values = tuple(record)
        primary_key_value = values[key_index]
        if not primary_key_value or not primary_key_value.strip():
            raise ValueError("primary key value must be non-empty and not whitespace-only")  # noqa: TRY003
        if primary_key_value in seen_keys:
            raise ValueError(f"duplicate primary key value: {primary_key_value!r}")  # noqa: TRY003
        seen_keys.add(primary_key_value)
        rows.append(
            CSVRowInput(
                document_id=value.document_id,
                primary_key=value.primary_key,
                primary_key_value=primary_key_value,
                columns=columns,
                values=values,
            )
        )
    return tuple(rows)


class _CSVRowSourceAdapter:
    """Resolve one CSV row input into a captured row Source and read it back."""

    input_class: ClassVar[type[CSVRowInput]] = CSVRowInput
    name: ClassVar[str] = CSV_ROW_SOURCE_NAME
    source_class: ClassVar[type[CSVRowSource]] = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            definition_version="1",
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class _CSVRowTextEvidenceProjection:
    """Project one row Source as compact JSON text evidence."""

    name: ClassVar[str] = TEXT_EVIDENCE_PROJECTION_KEY.name
    version: ClassVar[str] = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: ClassVar[type[CSVRowSource]] = CSVRowSource
    output_class: ClassVar[type[BaseModel]] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
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


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = AdapterSourceDefinition(
    _CSVRowSourceAdapter(),
    projections=(_CSVRowTextEvidenceProjection(),),
)

__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
