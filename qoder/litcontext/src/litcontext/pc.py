"""PowerContext 客户端：本作品的"记忆"全部走这里。

只用到 PowerContext 的公开 HTTP 接口：

* ``GET  /health/live``          存活检查
* ``POST /v1/scopes``            按研究方向建一个 scope（幂等）
* ``POST /v1/memory/remember``   写入结论 / 否决理由 / 约束 / 进度
* ``POST /v1/memory/search``     按查询召回原子记忆
* ``POST /v1/sources/content``   把论文摘要存成证据（Source journal）
* ``POST /v1/context/prepare``   按字节预算装配有界上下文

注意：本机回环地址必须绕过 ``HTTP(S)_PROXY``，否则请求会被转发到
无关的代理上并失败。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class PowerContextError(RuntimeError):
    """PowerContext 不可用或返回异常。"""


def _opener(url: str):
    host = (urlparse(url).hostname or "").lower()
    if host in LOOPBACK:
        return build_opener(ProxyHandler({}))
    return build_opener()


class PowerContextClient:
    def __init__(self, base_url: str, scope_key: str, scope_title: str,
                 timeout: int = 20, cache_file: Optional[Path] = None):
        self.base_url = base_url.rstrip("/")
        self.scope_key = scope_key
        self.scope_title = scope_title
        self.timeout = timeout
        self.cache_file = cache_file
        self._scope_id: Optional[str] = None
        self.calls: List[Dict[str, Any]] = []  # 供 UI/日志展示"真实调用过"

    # -- 底层 ---------------------------------------------------------------
    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None,
                 timeout: Optional[int] = None) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, method=method,
                          headers={"Content-Type": "application/json"})
        try:
            with _opener(url).open(request, timeout=timeout or self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:400]
            self.calls.append({"method": method, "path": path, "status": error.code})
            raise PowerContextError(f"{method} {path} -> HTTP {error.code}: {detail}") from error
        except URLError as error:
            self.calls.append({"method": method, "path": path, "status": "unreachable"})
            raise PowerContextError(
                f"{method} {path} 不可达：{error}。请先启动 PowerContext Server"
            ) from error
        self.calls.append({"method": method, "path": path, "status": 200})
        return json.loads(body) if body else {}

    # -- 健康与 scope -------------------------------------------------------
    def healthy(self) -> bool:
        try:
            self._request("GET", "/health/live", timeout=5)
            return True
        except PowerContextError:
            return False

    def ensure_scope(self) -> str:
        """取得本研究方向对应的 scope_id（首次创建，之后复用）。

        PowerContext 的 ``idempotency_key`` 只在参数完全一致时幂等；
        若用户改了 scope 标题而 key 不变，服务端会返回 409。这里先读本地
        缓存，冲突时再按标题在整个 Server 里找回同一个 scope。
        """
        if self._scope_id:
            return self._scope_id
        if self.cache_file and self.cache_file.exists():
            cached = self.cache_file.read_text(encoding="utf-8").strip()
            if cached.startswith("scp_"):
                self._scope_id = cached
                return cached
        payload = {
            "title": self.scope_title,
            "summary": "NILM 事件检测方向的文献结论、否决理由与阅读进度",
            "idempotency_key": self.scope_key,
        }
        try:
            result = self._request("POST", "/v1/scopes", payload)
        except PowerContextError as error:
            if "409" not in str(error):
                raise
            result = self._find_scope_by_title() or {}
        scope_id = result.get("scope_id") or result.get("id") or ""
        if not scope_id:
            raise PowerContextError(f"/v1/scopes 返回异常：{result}")
        self._scope_id = scope_id
        if self.cache_file:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(scope_id, encoding="utf-8")
        return scope_id

    def _find_scope_by_title(self) -> Optional[Dict[str, Any]]:
        listing = self._request("GET", "/v1/scopes")
        for item in listing.get("items", []):
            if item.get("title") == self.scope_title:
                return item
        return None

    # -- 记忆读写 -----------------------------------------------------------
    def remember(self, kind: str, text: str, reason: str = "") -> Dict[str, Any]:
        payload: Dict[str, Any] = {"scope_id": self.ensure_scope(), "kind": kind, "text": text}
        if reason:
            payload["reason"] = reason
        try:
            return self._request("POST", "/v1/memory/remember", payload)
        except PowerContextError:
            if kind == "decision":
                raise
            payload["kind"] = "decision"  # 兼容 kind 枚举较窄的构建
            return self._request("POST", "/v1/memory/remember", payload)

    def search_memory(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        """召回原子记忆，返回统一成 ``{"text","kind","artifact"}`` 的列表。

        PowerContext 1.5 的响应形如
        ``{"mode":"text","hits":[{"memory":{...,"text":...},"score":...}]}``，
        这里做一层归一化，免得上层关心版本差异。
        """
        result = self._request("POST", "/v1/memory/search", {
            "scope_id": self.ensure_scope(), "query": query, "limit": limit,
        })
        hits = result.get("hits") or []
        entries: List[Dict[str, Any]] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            memory = hit.get("memory")
            if isinstance(memory, dict):
                entries.append({
                    "text": memory.get("text", ""),
                    "kind": memory.get("kind", ""),
                    "artifact": memory.get("artifact", {}),
                    "score": hit.get("score"),
                })
            elif isinstance(hit.get("text"), str):
                entries.append(hit)
        if not entries:
            for key in ("entries", "items", "results", "memories"):
                value = result.get(key)
                if isinstance(value, list):
                    return [e for e in value if isinstance(e, dict)]
        return entries

    def capture_source(self, source_id: str, content: str,
                       metadata: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/v1/sources/content", {
            "scope_id": self.ensure_scope(),
            "source_id": source_id,
            "content": content[:100_000],
            "metadata": metadata,
        })

    def prepare(self, query: str, max_bytes: int = 4000) -> Dict[str, Any]:
        """有界上下文装配。返回 ``content`` / ``status`` / ``content_bytes``。"""
        result = self._request("POST", "/v1/context/prepare", {
            "scope_id": self.ensure_scope(),
            "query": query,
            "max_bytes": max_bytes,
        })
        content = result.get("content") or ""
        result.setdefault("content_bytes", len(content.encode("utf-8")))
        return result
