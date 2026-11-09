"""把"研究判断"写成 PowerContext 记忆，并能读回来。

每条记忆的正文是单行 JSON（前缀 ``LITCORE|``），这样既能被人读，
也能被程序解析成结构化的方法对比表；``reason`` 字段单独承载"为什么"。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .pc import PowerContextClient, PowerContextError

PREFIX = "LITCORE|"
PREFIX_KEY = "LITCORE"  # 召回键：每条记忆正文都以它开头

# PowerContext 的 kind 是自由字符串（1–128 字符），这里直接用语义名，
# 便于在 Dashboard / 检索结果里一眼看出这条是结论、取舍还是约束。
KIND_MAP = {
    "finding": "finding",
    "decision": "decision",
    "constraint": "constraint",
    "progress": "progress",
    "edge": "edge",
}


@dataclass
class MemoryRecord:
    type: str
    payload: Dict[str, Any]
    raw: str = ""

    @property
    def text(self) -> str:
        return str(self.payload.get("text") or self.payload.get("summary") or "")

    def as_dict(self) -> Dict[str, Any]:
        return {"type": self.type, **self.payload}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _write(pc: PowerContextClient, record_type: str, payload: Dict[str, Any],
           reason: str = "") -> Dict[str, Any]:
    payload = {"created": _now(), **payload}
    text = PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return pc.remember(KIND_MAP.get(record_type, "decision"), text, reason=reason)


def record_finding(pc: PowerContextClient, paper_id: str, topic: str, text: str,
                   evidence: str = "") -> Dict[str, Any]:
    return _write(pc, "finding",
                  {"type": "finding", "paper": paper_id, "topic": topic, "text": text,
                   "evidence": evidence},
                  reason=f"{paper_id} 的结论：{topic}")


def record_decision(pc: PowerContextClient, topic: str, method: str, verdict: str,
                    text: str, reason: str = "") -> Dict[str, Any]:
    return _write(pc, "decision",
                  {"type": "decision", "topic": topic, "method": method,
                   "verdict": verdict, "text": text},
                  reason=reason or f"{method} 的取舍判断")


def record_constraint(pc: PowerContextClient, text: str, reason: str = "") -> Dict[str, Any]:
    return _write(pc, "constraint", {"type": "constraint", "text": text},
                  reason=reason or "实验约束")


def record_progress(pc: PowerContextClient, done: str, next_step: str,
                    current: str = "") -> Dict[str, Any]:
    return _write(pc, "progress",
                  {"type": "progress", "done": done, "next": next_step, "current": current},
                  reason="阅读/实验进度快照")


def record_edge(pc: PowerContextClient, paper_id: str, method: str, dataset: str,
                metric: str, value: str, note: str = "") -> Dict[str, Any]:
    return _write(pc, "edge",
                  {"type": "edge", "paper": paper_id, "method": method,
                   "dataset": dataset, "metric": metric, "value": value, "note": note},
                  reason=f"方法对比：{method} @ {dataset}")


def parse_records(entries: Iterable[Dict[str, Any]]) -> List[MemoryRecord]:
    """从 memory/search 或 context/prepare 的结果里抠出我们的记录。"""
    records: List[MemoryRecord] = []
    for entry in entries:
        text = ""
        for key in ("text", "content", "body", "memory", "value"):
            value = entry.get(key) if isinstance(entry, dict) else None
            if isinstance(value, str):
                text = value
                break
        for line in text.splitlines():
            line = line.strip()
            index = line.find(PREFIX)
            if index < 0:
                continue
            try:
                payload = json.loads(line[index + len(PREFIX):])
            except json.JSONDecodeError:
                continue
            records.append(MemoryRecord(type=payload.get("type", "unknown"),
                                        payload=payload, raw=line))
    # 去重（同一个 scope 里同一段文本可能被多个召回路径重复返回）
    seen, unique = set(), []
    for record in records:
        key = json.dumps(record.payload, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def load_records(pc: PowerContextClient, query: str = PREFIX_KEY, limit: int = 50) -> List[MemoryRecord]:
    """按前缀召回本模块写入的全部记忆。

    PowerContext 的检索是"查询词全部命中"语义，长句查询会命中为空，
    因此这里统一用前缀 ``LITCORE`` 作召回键（每条记忆都带这个前缀），
    再在本地按类型/主题筛选。limit 上限为服务端允许的 50 条。
    """
    try:
        entries = pc.search_memory(query, limit=min(limit, 50))
    except PowerContextError:
        return []
    records = parse_records(entries)
    if records:
        return records
    # 兜底：search 的响应形状不一致时，用有界上下文再解析一次
    try:
        prepared = pc.prepare(query, max_bytes=20000)
    except PowerContextError:
        return []
    content = prepared.get("content") or ""
    return parse_records([{"text": content}])


def by_type(records: Iterable[MemoryRecord], wanted: str) -> List[MemoryRecord]:
    return [r for r in records if r.type == wanted]


def latest_progress(records: Iterable[MemoryRecord]) -> Optional[MemoryRecord]:
    progress = by_type(records, "progress")
    return progress[-1] if progress else None
