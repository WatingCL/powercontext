# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Context Pack wire protocol: full packs, prefix-reuse deltas, and rebuild.

A Context Pack represents one prepared context as bounded UTF-8 chunks with a
self-describing canonical JSON serialization and a SHA-256 digest. A delta
names a common prefix of a previously delivered pack and carries only the
appended suffix chunks, so a receiver can rebuild the target pack from its own
base pack and the delta alone.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass

CONTEXT_PACK_SCHEMA = "powercontext.context-pack.v1"
CONTEXT_PACK_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512
_DIGEST_PREFIX = "sha256:"


class ContextPackError(ValueError):
    """A Context Pack protocol or chunking violation."""


def _canonical_json(payload: dict) -> bytes:
    """UTF-8 canonical JSON: sorted keys, compact separators, no extra whitespace."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pack_digest(schema: str, items: tuple[bytes, ...]) -> str:
    unsigned = _canonical_json(
        {"schema": schema, "items": [base64.b64encode(item).decode("ascii") for item in items]}
    )
    return _DIGEST_PREFIX + hashlib.sha256(unsigned).hexdigest()


def _validate_digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(_DIGEST_PREFIX)
        or len(value) != len(_DIGEST_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in value[len(_DIGEST_PREFIX) :])
    ):
        raise ContextPackError("digest must be 'sha256:' followed by 64 hex characters")
    return value


def _decode_base64_items(value: object, *, field: str) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError(f"{field} must be a list of base64 strings")
    items: list[bytes] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ContextPackError(f"{field} entries must be base64 strings")
        try:
            items.append(base64.b64decode(entry, validate=True))
        except (binascii.Error, ValueError) as error:
            raise ContextPackError(f"{field} entries must be valid base64") from error
    return tuple(items)


def _encode_base64_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _self_referential_byte_count(payload_builder) -> int:
    """Solve ``byte_count == len(serialization including byte_count)`` by iteration."""

    count = 0
    for _ in range(16):
        length = len(payload_builder(count))
        if length == count:
            return count
        count = length
    raise ContextPackError("byte count failed to converge")


@dataclass(frozen=True)
class ContextPack:
    """One complete context: bounded chunks with digest and exact wire size."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        """Build a pack from a bytes tuple, computing digest and self-inclusive size."""

        if isinstance(items, (bytes, bytearray)) or not isinstance(items, (tuple, list)):
            raise ContextPackError("items must be a tuple of bytes")
        normalized = tuple(bytes(item) for item in items)
        digest = _pack_digest(CONTEXT_PACK_SCHEMA, normalized)
        byte_count = _self_referential_byte_count(
            lambda count: _canonical_json(
                {
                    "schema": CONTEXT_PACK_SCHEMA,
                    "items": _encode_base64_items(normalized),
                    "digest": digest,
                    "byte_count": count,
                }
            )
        )
        return cls(items=normalized, digest=digest, byte_count=byte_count)

    @classmethod
    def from_content(cls, content: str | None, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContextPack:
        """Chunk content deterministically at UTF-8 character boundaries.

        Every chunk is valid UTF-8 and at most ``chunk_bytes`` bytes; a bound
        that cannot fit even one character raises ``ContextPackError``.
        """

        if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes < 1:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ContextPackError("content must be a string")
        items: list[bytes] = []
        current: list[bytes] = []
        current_size = 0
        for character in content:
            encoded = character.encode("utf-8")
            size = len(encoded)
            if size > chunk_bytes:
                raise ContextPackError("chunk_bytes cannot hold a single UTF-8 character")
            if current_size + size > chunk_bytes:
                items.append(b"".join(current))
                current = [encoded]
                current_size = size
            else:
                current.append(encoded)
                current_size += size
        if current:
            items.append(b"".join(current))
        return cls.build(tuple(items))

    def to_bytes(self) -> bytes:
        """Serialize to canonical JSON with the self-inclusive ``byte_count`` field."""

        return _canonical_json(
            {
                "schema": CONTEXT_PACK_SCHEMA,
                "items": _encode_base64_items(self.items),
                "digest": self.digest,
                "byte_count": self.byte_count,
            }
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        """Decode and fully validate a serialized pack: fields, digest, byte count."""

        try:
            payload = json.loads(data)
        except (ValueError, UnicodeDecodeError) as error:
            raise ContextPackError("context pack is not valid JSON") from error
        if not isinstance(payload, dict) or set(payload) != {"schema", "items", "digest", "byte_count"}:
            raise ContextPackError("context pack must contain exactly schema, items, digest, byte_count")
        if payload["schema"] != CONTEXT_PACK_SCHEMA:
            raise ContextPackError("unknown context pack schema")
        items = _decode_base64_items(payload["items"], field="items")
        digest = _validate_digest(payload["digest"])
        if digest != _pack_digest(CONTEXT_PACK_SCHEMA, items):
            raise ContextPackError("context pack digest does not match its items")
        byte_count = payload["byte_count"]
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 1:
            raise ContextPackError("byte_count must be a positive integer")
        expected = len(
            _canonical_json(
                {
                    "schema": CONTEXT_PACK_SCHEMA,
                    "items": _encode_base64_items(items),
                    "digest": digest,
                    "byte_count": byte_count,
                }
            )
        )
        if byte_count != expected:
            raise ContextPackError("context pack byte_count does not match its serialization")
        return cls(items=items, digest=digest, byte_count=byte_count)


@dataclass(frozen=True)
class ContextPackDelta:
    """A prefix-reuse delta from one base pack to one target pack.

    ``prefix_items`` is how many leading base chunks the receiver keeps;
    ``appended`` carries the target chunks after that prefix.
    """

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        """Select a valid common chunk prefix of the two packs."""

        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("between requires two ContextPack instances")
        prefix = 0
        for base_item, target_item in zip(base.items, target.items):
            if base_item != target_item:
                break
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    def to_bytes(self) -> bytes:
        """Serialize to canonical delta JSON; ``byte_count`` measures this output."""

        return _canonical_json(
            {
                "schema": CONTEXT_PACK_DELTA_SCHEMA,
                "base_digest": self.base_digest,
                "target_digest": self.target_digest,
                "prefix_items": self.prefix_items,
                "appended": _encode_base64_items(self.appended),
            }
        )

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        """Decode and validate a serialized delta: fields, schema, prefix bounds."""

        try:
            payload = json.loads(data)
        except (ValueError, UnicodeDecodeError) as error:
            raise ContextPackError("context pack delta is not valid JSON") from error
        required = {"schema", "base_digest", "target_digest", "prefix_items", "appended"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise ContextPackError(
                "context pack delta must contain exactly schema, base_digest, target_digest, prefix_items, appended"
            )
        if payload["schema"] != CONTEXT_PACK_DELTA_SCHEMA:
            raise ContextPackError("unknown context pack delta schema")
        base_digest = _validate_digest(payload["base_digest"])
        target_digest = _validate_digest(payload["target_digest"])
        prefix = payload["prefix_items"]
        if isinstance(prefix, bool) or not isinstance(prefix, int) or prefix < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        appended = _decode_base64_items(payload["appended"], field="appended")
        return cls(base_digest=base_digest, target_digest=target_digest, prefix_items=prefix, appended=appended)


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Validate a delta against ``base`` and rebuild the target pack."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("apply requires a ContextPack base and a ContextPackDelta")
    if delta.base_digest != base.digest:
        raise ContextPackError("delta base digest does not match the provided base pack")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix exceeds the base pack chunk count")
    rebuilt = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if rebuilt.digest != delta.target_digest:
        raise ContextPackError("rebuilt pack digest does not match the delta target digest")
    return rebuilt


__all__ = [
    "CONTEXT_PACK_SCHEMA",
    "CONTEXT_PACK_DELTA_SCHEMA",
    "DEFAULT_CHUNK_BYTES",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
