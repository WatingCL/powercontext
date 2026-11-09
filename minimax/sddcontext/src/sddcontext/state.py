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
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STATE_PREFIX = "SDD-TASK-STATE"
SCOPE_CACHE = "scope_id.txt"


class PowerContextError(RuntimeError):
    pass


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
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:  # pragma: no cover - network detail
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise PowerContextError(
                f"PowerContext {path} failed with HTTP {error.code}: {detail}"
            ) from error
        except URLError as error:  # pragma: no cover - network detail
            raise PowerContextError(f"PowerContext {path} unreachable: {error}") from error

    def healthy(self) -> bool:
        try:
            self._request("GET", "/health/live")
            return True
        except PowerContextError:
            return False

    # -- scope management ---------------------------------------------------
    def ensure_scope(self, title: str = "SDD todoapp context",
                     idempotency_key: str = "sdd-todoapp-scope") -> str:
        """Create (idempotently) or reuse the project scope."""
        if self._scope_id:
            return self._scope_id
        cache = self.work_dir / SCOPE_CACHE
        if cache.exists():
            cached = cache.read_text(encoding="utf-8").strip()
            if cached:
                self._scope_id = cached
                return cached
        result = self._request(
            "POST",
            "/v1/scopes",
            {
                "title": title,
                "summary": "SDD context for the todoapp demo project",
                "idempotency_key": idempotency_key,
            },
        )
        scope_id = result.get("scope_id") or ""
        if not scope_id:
            raise PowerContextError(f"unexpected /v1/scopes response: {result}")
        self._scope_id = scope_id
        self.work_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(scope_id, encoding="utf-8")
        return scope_id

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

    def _parse_state_entries(self, entries: List[Dict[str, Any]], task_id: str) -> Optional[Dict[str, Any]]:
        matched: List[Dict[str, Any]] = []
        for entry in entries:
            entry_text = ""
            if isinstance(entry, dict):
                for key in ("text", "content", "body"):
                    if isinstance(entry.get(key), str):
                        entry_text = entry[key]
                        break
            if entry_text.startswith(f"{STATE_PREFIX} {task_id}\n"):
                matched.append(json.loads(entry_text.split("\n", 1)[1]))
        if not matched:
            return None
        # merge snapshots: later fields win; list fields are replaced by newest
        merged: Dict[str, Any] = {}
        for snapshot in matched:
            merged.update(snapshot)
        merged["_snapshots"] = len(matched)
        return merged

    def load_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Recall the latest task state from Memory.

        Uses the structured Memory search API; falls back to PreparedContext
        content when the search response shape differs between versions.
        """
        scope_id = self.ensure_scope()
        try:
            result = self._request(
                "POST",
                "/v1/memory/search",
                {"scope_id": scope_id, "query": f"{STATE_PREFIX} {task_id}", "limit": 20},
            )
        except PowerContextError:
            result = {}
        for key in ("entries", "items", "results", "memories"):
            entries = result.get(key)
            if isinstance(entries, list):
                state = self._parse_state_entries(entries, task_id)
                if state is not None:
                    return state
        # fallback: /v1/context/prepare returns assembled text
        try:
            prepared = self._request(
                "POST",
                "/v1/context/prepare",
                {"scope_id": scope_id, "query": f"{STATE_PREFIX} {task_id}", "max_bytes": 8000},
            )
            content = prepared.get("content") or ""
            for block in content.split(f"{STATE_PREFIX} {task_id}")[1:]:
                payload = block.strip().splitlines()
                if not payload:
                    continue
                try:
                    return json.loads(payload[0])
                except json.JSONDecodeError:
                    continue
        except (PowerContextError, json.JSONDecodeError):
            pass
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
