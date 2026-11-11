"""PowerContext client: persist and recall SDD task state.

The module talks to a running PowerContext Server over HTTP (default
``http://127.0.0.1:8000``). Task state is stored as explicit Memory entries
(kind ``state``) tagged with ``SDD-TASK-STATE <task_id>``, so a restarted
module process - or even a restarted PowerContext Server, since state is
durable in its storage - reads the same state back and includes it in the
built context.

Work contracts and outcomes (task objective, verification results, MiniMax
interaction summaries) are additionally captured as Sources, which preserves
exact evidence of the development process.

Server response shapes differ across PowerContext releases (1.2.x returns the
Memory body at the top level of a hit, 1.4.x nests it under ``memory`` and
wraps ``/v1/context/prepare`` payloads in a
``BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1`` envelope). Recall therefore walks
the response structurally and never depends on a single fixed layout.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

STATE_PREFIX = "SDD-TASK-STATE"
SCOPE_CACHE = "scope_id.txt"
SCOPE_TITLE = "SDD todoapp context"
SCOPE_SUMMARY = "SDD context for the todoapp demo project"
SCOPE_KEY = "sdd-todoapp-scope"
PREPARED_MARKER = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"

# Keys that carry the Memory body, newest layout first.
_TEXT_KEYS = ("text", "content", "body", "value")
# Wrappers a server may use around a hit / record / envelope item.
_WRAPPER_KEYS = ("memory", "record", "entry", "item", "hit", "data", "result")
# Response keys that may hold the list of hits.
_HIT_KEYS = ("hits", "entries", "items", "results", "memories", "records")


class PowerContextError(RuntimeError):
    pass


def _opener_for(url: str):
    """Bypass HTTP(S)_PROXY for loopback targets (local PowerContext server).

    Corporate/agent proxy environment variables would otherwise route
    127.0.0.1 traffic through an unrelated proxy and break local calls.
    """
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return build_opener(ProxyHandler({}))
    return build_opener()


def _memory_text(value: Any, depth: int = 0) -> str:
    """Find the Memory body inside an arbitrarily wrapped hit/record."""
    if depth > 4:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    for key in _TEXT_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    for key in _WRAPPER_KEYS:
        nested = value.get(key)
        if isinstance(nested, (dict, str)):
            text = _memory_text(nested, depth + 1)
            if text.strip():
                return text
    return ""


def _unescape(text: str) -> str:
    """Collapse one extra layer of JSON string escaping."""
    return (
        text.replace('\\"', '"')
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace("\\/", "/")
        .replace("\\\\", "\\")
    )


def _first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Decode the first JSON object in ``text``, tolerating escaped variants."""
    stripped = text.lstrip()
    for candidate in (stripped, _unescape(stripped)):
        start = candidate.find("{")
        while start != -1:
            try:
                value, _end = json.JSONDecoder().raw_decode(candidate[start:])
            except json.JSONDecodeError:
                start = candidate.find("{", start + 1)
                continue
            if isinstance(value, dict):
                return value
            start = candidate.find("{", start + 1)
    return None


def _prepared_texts(content: str) -> List[str]:
    """Extract candidate Memory bodies from a PreparedContext payload.

    Releases before 1.4 return the assembled Memory text directly. 1.4+ wrap
    it as ``BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1`` followed by a JSON object
    whose ``items[].content`` fields are JSON-escaped Memory bodies.
    """
    if not content:
        return []
    marker_at = content.find(PREPARED_MARKER)
    if marker_at < 0:
        return [content]
    envelope = _first_json_object(content[marker_at + len(PREPARED_MARKER):])
    if not envelope:
        return [content[marker_at + len(PREPARED_MARKER):]]
    texts: List[str] = []
    items = envelope.get("items")
    if isinstance(items, list):
        for item in items:
            text = _memory_text(item)
            if not text:
                continue
            texts.append(text)
            unescaped = _unescape(text)
            if unescaped != text:
                texts.append(unescaped)
    for key in ("content", "text", "body"):
        value = envelope.get(key)
        if isinstance(value, str):
            texts.append(value)
    return texts


class PowerContextClient:
    def __init__(self, base_url: str, work_dir, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.work_dir = work_dir
        self._scope_id: Optional[str] = None

    # -- low-level helpers -------------------------------------------------
    def _request(self, method: str, path: str, payload: Optional[Dict] = None) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with _opener_for(f"{self.base_url}{path}").open(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:  # pragma: no cover - network detail
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise PowerContextError(
                f"PowerContext {path} failed with HTTP {error.code}: {detail}"
            ) from error
        except URLError as error:  # pragma: no cover - network detail
            raise PowerContextError(f"PowerContext {path} unreachable: {error}") from error

    def _get_json(self, path: str) -> Dict[str, Any]:
        return self._request("GET", path)

    def healthy(self) -> bool:
        for path in ("/health/live", "/health"):
            try:
                self._request("GET", path)
                return True
            except PowerContextError:
                continue
        return False

    # -- scope management ---------------------------------------------------
    def _create_scope(self) -> str:
        result = self._request(
            "POST",
            "/v1/scopes",
            {
                "title": SCOPE_TITLE,
                "summary": SCOPE_SUMMARY,
                "idempotency_key": SCOPE_KEY,
            },
        )
        scope_id = result.get("scope_id") or ""
        if not scope_id:
            raise PowerContextError(f"unexpected /v1/scopes response: {result}")
        self._scope_id = scope_id
        self.work_dir.mkdir(parents=True, exist_ok=True)
        (self.work_dir / SCOPE_CACHE).write_text(scope_id, encoding="utf-8")
        return scope_id

    def ensure_scope(self) -> str:
        """Create (idempotently) or reuse the project scope.

        ``POST /v1/scopes`` is idempotent on ``idempotency_key``, so the local
        cache is only a fast path: deleting it re-resolves to the same scope.
        """
        if self._scope_id:
            return self._scope_id
        cache = self.work_dir / SCOPE_CACHE
        if cache.exists():
            cached = cache.read_text(encoding="utf-8").strip()
            if cached:
                self._scope_id = cached
                return cached
        return self._create_scope()

    def scope_candidates(self) -> List[str]:
        """Scopes to search: the resolved one plus any scope we recognise.

        A stale cache (data directory recreated, scope created outside this
        module) must not hide previously saved state, so the server's own scope
        listing is consulted for scopes carrying our project title.
        """
        candidates: List[str] = []
        try:
            primary = self.ensure_scope()
        except PowerContextError:
            primary = ""
        if primary:
            candidates.append(primary)
        try:
            listing = self._get_json("/v1/scopes")
        except PowerContextError:
            listing = {}
        for scope in listing.get("items") or listing.get("scopes") or []:
            if not isinstance(scope, dict):
                continue
            scope_id = scope.get("scope_id") or ""
            if not scope_id or scope_id in candidates:
                continue
            if scope.get("title") == SCOPE_TITLE or scope.get("summary") == SCOPE_SUMMARY:
                candidates.append(scope_id)
        return candidates

    # -- task state as Memory -----------------------------------------------
    def remember(self, kind: str, text: str, reason: str = "") -> Dict[str, Any]:
        scope_id = self.ensure_scope()
        payload: Dict[str, Any] = {"scope_id": scope_id, "kind": kind, "text": text}
        if reason:
            payload["reason"] = reason
        try:
            return self._request("POST", "/v1/memory/remember", payload)
        except PowerContextError:
            if kind != "decision":
                # some server builds accept a narrower kind enum
                payload["kind"] = "decision"
                return self._request("POST", "/v1/memory/remember", payload)
            raise

    def save_task_state(self, task_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Persist task state (done/todo/verification results) as Memory."""
        text = (
            f"{STATE_PREFIX} {task_id}\n"
            + json.dumps(state, ensure_ascii=False, sort_keys=True)
        )
        return self.remember("state", text, reason=f"task {task_id} progress snapshot")

    # -- state parsing -------------------------------------------------------
    @staticmethod
    def _state_body(text: str, task_id: str) -> Optional[Dict[str, Any]]:
        """Return the JSON body recorded after ``SDD-TASK-STATE <task_id>``."""
        if not text:
            return None
        pattern = re.compile(rf"{re.escape(STATE_PREFIX)} {re.escape(task_id)}(?!\d)")
        match = pattern.search(text)
        if not match:
            return None
        body = _first_json_object(text[match.end():])
        if not isinstance(body, dict):
            return None
        return body

    def _parse_state_entries(
        self, entries: Iterable[Any], task_id: str
    ) -> Optional[Dict[str, Any]]:
        matched: List[Dict[str, Any]] = []
        for entry in entries:
            body = self._state_body(_memory_text(entry), task_id)
            if body is not None:
                matched.append(body)
        if not matched:
            return None
        # merge snapshots: later fields win; list fields are replaced by newest
        merged: Dict[str, Any] = {}
        for snapshot in matched:
            merged.update(snapshot)
        merged["_snapshots"] = len(matched)
        return merged

    def _search_state(self, scope_id: str, query: str, task_id: str) -> Optional[Dict[str, Any]]:
        try:
            result = self._request(
                "POST",
                "/v1/memory/search",
                {"scope_id": scope_id, "query": query, "limit": 50},
            )
        except PowerContextError:
            return None
        for key in _HIT_KEYS:
            entries = result.get(key)
            if isinstance(entries, list):
                state = self._parse_state_entries(entries, task_id)
                if state is not None:
                    return state
        return None

    def _prepare_state(self, scope_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        try:
            prepared = self._request(
                "POST",
                "/v1/context/prepare",
                {"scope_id": scope_id, "query": f"{STATE_PREFIX} {task_id}", "max_bytes": 16000},
            )
        except PowerContextError:
            return None
        bodies = [
            body
            for body in (
                self._state_body(text, task_id)
                for text in _prepared_texts(prepared.get("content") or "")
            )
            if body is not None
        ]
        if not bodies:
            return None
        merged: Dict[str, Any] = {}
        for body in bodies:
            merged.update(body)
        merged["_snapshots"] = len(bodies)
        return merged

    def load_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Recall the latest task state from Memory.

        Tries Memory search first (a targeted query, then the bare prefix), then
        the PreparedContext assembly across every recognised scope, so state is
        recovered whether or not the local scope cache survived and regardless
        of the server's response layout.
        """
        scopes = self.scope_candidates()
        queries = (f"{STATE_PREFIX} {task_id}", STATE_PREFIX)
        for scope_id in scopes:
            for query in queries:
                state = self._search_state(scope_id, query, task_id)
                if state is not None:
                    return state
        for scope_id in scopes:
            state = self._prepare_state(scope_id, task_id)
            if state is not None:
                return state
        return None

    # -- development evidence as Sources -------------------------------------
    def record_source(self, source_id: str, content: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        scope_id = self.ensure_scope()
        return self._request(
            "POST",
            "/v1/sources/content",
            {
                "scope_id": scope_id,
                "source_id": source_id,
                "content": content[:100_000],
                "metadata": metadata,
            },
        )
