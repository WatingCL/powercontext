"""本地 Web UI：标准库 http.server，无额外依赖。

页面只做三件事：检索原文、看/写记忆、导出初稿。
每个面板都会显示它是"本地索引"还是"PowerContext"提供的，
方便评审核对哪种技术在哪一步真的起了作用。
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, urlparse

from . import memory, report
from .builder import build_resume, render_resume_markdown
from .config import Config
from .index import Index
from .pc import PowerContextClient, PowerContextError

STATIC = Path(__file__).resolve().parent / "web"


class Handler(BaseHTTPRequestHandler):
    cfg: Config
    index: Index
    pc: PowerContextClient

    def log_message(self, fmt: str, *args: Any) -> None:  # 安静一点
        return

    # -- 输出 ---------------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    # -- 路由 ---------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path in ("/", "/index.html"):
                page = (STATIC / "index.html").read_text(encoding="utf-8")
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif parsed.path == "/api/stats":
                self._json({"index": self.index.stats(),
                            "papers": self.index.papers(),
                            "pc_url": self.cfg.pc_url,
                            "pc_alive": self.pc.healthy()})
            elif parsed.path == "/api/search":
                self._search(query)
            elif parsed.path == "/api/resume":
                card = build_resume(self.pc, max_bytes=int(query.get("max_bytes", ["4000"])[0]))
                self._json({"card": card, "markdown": render_resume_markdown(card)})
            elif parsed.path == "/api/brief":
                topic = (query.get("topic") or ["事件检测"])[0]
                brief = report.build_brief(self.index, self.pc, topic)
                self._json({"markdown": report.render_brief_markdown(brief),
                            "memory_calls": brief["memory_calls"]})
            elif parsed.path == "/api/compare":
                data = report.build_compare(self.pc)
                self._json({"markdown": report.render_compare_markdown(data),
                            "edges": len(data["edges"])})
            else:
                self._json({"error": "not found"}, 404)
        except PowerContextError as error:
            self._json({"error": str(error)}, 503)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, 400)
            return
        try:
            if parsed.path == "/api/note":
                self._json(self._note(payload))
            else:
                self._json({"error": "not found"}, 404)
        except PowerContextError as error:
            self._json({"error": str(error)}, 503)

    # -- 业务 ---------------------------------------------------------------
    def _search(self, query: Dict[str, list]) -> None:
        q = (query.get("q") or [""])[0].strip()
        if not q:
            self._json({"hits": []})
            return
        year_from = query.get("year_from", [""])[0]
        hits = self.index.search(
            q,
            top_k=int(query.get("top", ["6"])[0]),
            year_from=int(year_from) if year_from.isdigit() else None,
            method=(query.get("method") or [None])[0] or None,
        )
        self._json({"query": q, "hits": [h.as_dict() for h in hits],
                    "backend": "local-sqlite-bm25"})

    def _note(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        kind = payload.get("kind", "finding")
        text = str(payload.get("text", "")).strip()
        if not text:
            return {"error": "text 不能为空"}
        if kind == "decision":
            result = memory.record_decision(
                self.pc, payload.get("topic") or "通用",
                payload.get("method") or "未标注方法",
                payload.get("verdict") or "keep", text,
                reason=payload.get("reason") or "",
            )
        elif kind == "constraint":
            result = memory.record_constraint(self.pc, text, reason=payload.get("reason") or "")
        else:
            result = memory.record_finding(
                self.pc, payload.get("paper") or "?", payload.get("topic") or "通用", text,
                evidence=payload.get("evidence") or "",
            )
        return {"ok": True, "kind": kind, "result": result}


def serve(cfg: Config, port: int = 8765, open_browser: bool = True) -> None:
    Handler.cfg = cfg
    Handler.index = Index(cfg.db_path)
    Handler.pc = PowerContextClient(cfg.pc_url, cfg.scope_key, cfg.scope_title,
                                    timeout=cfg.timeout,
                                    cache_file=cfg.data_dir / "scope_id.txt")
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"litcontext UI 已启动：{url}")
    print(f"  PowerContext: {cfg.pc_url} -> {'可用' if Handler.pc.healthy() else '不可达'}")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
        Handler.index.close()
