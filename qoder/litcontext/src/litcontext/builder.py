"""有界上下文装配：把"上次读到哪、为什么这么定"拼成下次开工前该看的一屏。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from . import memory
from .pc import PowerContextClient, PowerContextError

RESUME_QUERY = memory.PREFIX_KEY

BEGIN = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
END = "END_POWERCONTEXT_PREPARED_CONTEXT_V1"


def items_from_prepared(content: str) -> List[Dict[str, Any]]:
    """从 PreparedContext 的载荷里取出条目（内容是 JSON，不是给人读的散文）。"""
    start, end = content.find(BEGIN), content.find(END)
    if start < 0 or end < 0:
        return []
    blob = content[start + len(BEGIN):end].strip()
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        return []
    return [{"text": str(item.get("content", ""))}
            for item in payload.get("items", []) if isinstance(item, dict)]


def build_resume(pc: PowerContextClient, max_bytes: int = 4000) -> Dict[str, Any]:
    """召回进度/否决/约束/结论，并附上 PowerContext 的真实调用痕迹。"""
    errors: List[str] = []
    records = memory.load_records(pc, RESUME_QUERY, limit=40)
    prepared: Dict[str, Any] = {}
    try:
        prepared = pc.prepare(RESUME_QUERY, max_bytes=max_bytes)
    except PowerContextError as error:
        errors.append(str(error))

    content = prepared.get("content") or ""
    prepared_records = memory.parse_records(items_from_prepared(content))
    known = {json.dumps(r.payload, ensure_ascii=False, sort_keys=True) for r in records}
    for record in prepared_records:
        key = json.dumps(record.payload, ensure_ascii=False, sort_keys=True)
        if key not in known:
            records.append(record)
            known.add(key)

    progress = memory.latest_progress(records)
    rejected = [r for r in memory.by_type(records, "decision")
                if str(r.payload.get("verdict", "")).lower() in {"reject", "drop", "否", "否决"}]

    return {
        "records": [r.as_dict() for r in records],
        "progress": progress.as_dict() if progress else None,
        "rejected": [r.as_dict() for r in rejected],
        "constraints": [r.as_dict() for r in memory.by_type(records, "constraint")],
        "findings": [r.as_dict() for r in memory.by_type(records, "finding")],
        "prepared": {
            "status": prepared.get("status", "unknown"),
            "items": len(prepared_records),
            "bytes": prepared.get("content_bytes") or len(content.encode("utf-8")),
            "budget": max_bytes,
            "schema": prepared.get("schema", ""),
        },
        "calls": pc.calls[-6:],
        "errors": errors,
    }


def render_resume_markdown(card: Dict[str, Any]) -> str:
    lines: List[str] = ["# 上次的进度", ""]
    progress = card.get("progress")
    if progress:
        lines += [
            f"- 已完成：{progress.get('done') or '（未记录）'}",
            f"- 正在做：{progress.get('current') or '（未记录）'}",
            f"- 下一步：{progress.get('next') or '（未记录）'}",
            f"- 记录时间：{progress.get('created', '')}",
        ]
    else:
        lines.append("- 还没有进度记录（先用 `litcontext progress` 写一条）")

    if card.get("rejected"):
        lines += ["", "## 已经否掉的方向（别再走一遍）", ""]
        for item in card["rejected"]:
            lines.append(f"- **{item.get('method', '未标注')}**：{item.get('text', '')}")

    if card.get("constraints"):
        lines += ["", "## 实验约束", ""]
        for item in card["constraints"]:
            lines.append(f"- {item.get('text', '')}")

    findings = card.get("findings") or []
    if findings:
        lines += ["", f"## 已积累的结论（{len(findings)} 条）", ""]
        for item in findings[-8:]:
            lines.append(f"- [{item.get('paper', '?')}] {item.get('text', '')}")

    prepared = card.get("prepared", {})
    lines += [
        "",
        "## 上下文预算",
        "",
        f"- 状态：`{prepared.get('status')}`　占用：{prepared.get('bytes')} / {prepared.get('budget')} 字节",
    ]
    if card.get("errors"):
        lines += ["", "> PowerContext 调用异常：" + "；".join(card["errors"])]
    return "\n".join(lines) + "\n"
