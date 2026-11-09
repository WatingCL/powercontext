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

"""Pi session branch capture: selected-branch parsing, event Sources, and resumable ingestion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote

from pydantic import BaseModel, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunSession, ConnectorRunStatus
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
_PI_CHECKPOINT_VERSION = 1


class PiSessionInput(BaseModel):
    """One complete offline Pi session JSONL document and the selected leaf."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected branch with its complete raw record."""

    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """One captured Pi event whose identity is session id plus event id."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Build the stable event identity from percent-encoded identity components."""

    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id must be non-empty")  # noqa: TRY003
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id must be non-empty")  # noqa: TRY003
    source_id = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def _json_arguments(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _visible_message_body(content: object) -> str:
    """Render message content as visible text, joining text blocks and tool calls by newline."""

    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            raise ValueError("message content blocks must be JSON objects")  # noqa: TRY003
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise ValueError("text blocks must carry string text")  # noqa: TRY003
            parts.append(text)
        elif block_type == "toolCall":
            name = block.get("name")
            call_id = block.get("id")
            if not isinstance(name, str) or not isinstance(call_id, str):
                raise ValueError("toolCall blocks must carry string name and id")  # noqa: TRY003
            parts.append(f"[tool_call {name} {call_id}] {_json_arguments(block.get('arguments', {}))}")
        # thinking, image and unknown blocks stay out of the visible evidence text.
    return "\n".join(parts)


def _tool_result_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            raise ValueError("toolResult content blocks must be JSON objects")  # noqa: TRY003
        if block.get("type") == "text":
            text = block.get("text")
            if not isinstance(text, str):
                raise ValueError("text blocks must carry string text")  # noqa: TRY003
            parts.append(text)
    return "\n".join(parts)


def _event_from_record(session_id: str, record: dict[str, JsonValue]) -> PiEventInput | None:
    """Build one visible event from a raw session record, or ``None`` for control nodes."""

    event_type = record.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("session records must declare a string type")  # noqa: TRY003

    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            raise ValueError("message records must contain a message object")  # noqa: TRY003
        role = message.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError("message role must be a non-empty string")  # noqa: TRY003
        if role == "toolResult":
            tool_name = message.get("toolName", "")
            tool_call_id = message.get("toolCallId", "")
            body = f"[tool_result {tool_name} {tool_call_id}] {_tool_result_text(message.get('content'))}"
        elif role == "bashExecution":
            body = f"$ {message.get('command', '')}\n{message.get('output', '')}"
        else:
            body = _visible_message_body(message.get("content"))
            if not body:
                return None
    elif event_type in ("compaction", "branch_summary"):
        role = event_type
        body = record.get("summary")
        body = body if isinstance(body, str) else ""
        if not body:
            return None
    elif event_type == "custom_message":
        role = "custom"
        body = _visible_message_body(record.get("content"))
        if not body:
            return None
    else:
        # Control nodes keep the graph connected but produce no text evidence.
        return None

    parent_id = record.get("parentId")
    parent_id = parent_id if isinstance(parent_id, str) and parent_id else None
    return PiEventInput(
        session_id=session_id,
        event_id=record["id"],
        parent_id=parent_id,
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse the selected branch atomically: all visible events or ``ValueError``."""

    # Strict UTF-8 decode that accepts a leading UTF-8 BOM.
    try:
        text = value.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"session is not valid UTF-8: {error}") from None

    records: list[dict[str, JsonValue]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"malformed JSONL: {error}") from None
        if not isinstance(record, dict):
            raise ValueError("session records must be JSON objects")  # noqa: TRY003
        records.append(record)

    if not records:
        raise ValueError("session must begin with a session header record")  # noqa: TRY003

    header, *rest = records
    if header.get("type") != "session" or header.get("version") != 3:
        raise ValueError("first record must declare type session and version 3")  # noqa: TRY003
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session header id must be a non-empty string")  # noqa: TRY003

    nodes: dict[str, dict[str, JsonValue]] = {session_id: header}
    order: list[str] = []
    for record in rest:
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("record id must be a non-empty string")  # noqa: TRY003
        if record_id in nodes:
            raise ValueError(f"duplicate record id: {record_id!r}")  # noqa: TRY003
        parent_id = record.get("parentId")
        if parent_id is None or parent_id == "":
            pass  # root record
        elif isinstance(parent_id, str) and parent_id in nodes:
            pass  # parent appeared earlier in the file
        else:
            raise ValueError(
                f"record {record_id!r} references missing or forward parent {parent_id!r}"  # noqa: TRY003
            ) from None
        nodes[record_id] = record
        order.append(record_id)

    if value.leaf_id is None:
        leaf = order[-1] if order else session_id
    elif isinstance(value.leaf_id, str) and value.leaf_id in nodes:
        leaf = value.leaf_id
    else:
        raise ValueError(f"leaf {value.leaf_id!r} not found in session")  # noqa: TRY003

    path: list[str] = []
    cursor: str | None = leaf
    while cursor is not None:
        path.append(cursor)
        parent_id = nodes[cursor].get("parentId")
        cursor = parent_id if isinstance(parent_id, str) and parent_id else None
    path.reverse()

    return tuple(
        event
        for node_id in path
        if (event := _event_from_record(session_id, nodes[node_id])) is not None
    )


class _PiEventSourceAdapter:
    """Resolve one Pi event input into a captured event Source and read it back."""

    input_class: ClassVar[type[PiEventInput]] = PiEventInput
    name: ClassVar[str] = PI_EVENT_SOURCE_NAME
    source_class: ClassVar[type[PiEventSource]] = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            definition_version="1",
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class _PiEventTextEvidenceProjection:
    """Project one event Source as its complete visible text evidence."""

    name: ClassVar[str] = TEXT_EVIDENCE_PROJECTION_KEY.name
    version: ClassVar[str] = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: ClassVar[type[PiEventSource]] = PiEventSource
    output_class: ClassVar[type[BaseModel]] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = AdapterSourceDefinition(
    _PiEventSourceAdapter(),
    projections=(_PiEventTextEvidenceProjection(),),
)


def _record_digest(record: dict[str, JsonValue]) -> str:
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PiSessionConnector:
    """Ingest the selected branch incrementally with a durable event checkpoint."""

    name: ClassVar[str] = PI_SESSION_CONNECTOR_NAME
    version: ClassVar[str] = "1"
    source_definitions: frozenset[str] = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: Path | str, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        raw = self._path.read_bytes()
        events = parse_pi_session(PiSessionInput(content=raw, leaf_id=self._leaf_id))

        previous = session.checkpoint
        stored_session_id: str | None = None
        stored_events: dict[str, str] = {}
        if isinstance(previous, dict):
            stored_session_id = previous.get("session_id")
            if isinstance(stored_session_id, str) and not stored_session_id:
                stored_session_id = None
            raw_events = previous.get("events")
            if isinstance(raw_events, dict):
                stored_events = {
                    key: value
                    for key, value in raw_events.items()
                    if isinstance(key, str) and isinstance(value, str)
                }

        if events and stored_session_id is not None and stored_session_id != events[0].session_id:
            raise ValueError("persisted checkpoint belongs to a different session")  # noqa: TRY003

        imported = dict(stored_events)
        for event in events:
            digest = _record_digest(event.record)
            known = imported.get(event.event_id)
            if known is not None:
                if known != digest:
                    raise ValueError(f"imported event {event.event_id!r} was rewritten")  # noqa: TRY003
                continue
            await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            imported[event.event_id] = digest

        checkpoint = {
            "version": _PI_CHECKPOINT_VERSION,
            "session_id": events[0].session_id if events else stored_session_id,
            "events": imported,
        }
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint)


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
