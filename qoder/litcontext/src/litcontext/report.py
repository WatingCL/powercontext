"""把检索结果与记忆拼成两样能直接用的东西：综述初稿、方法对比表。

初稿是确定性的（不依赖任何大模型）：每条论断都带 [paper_id] 出处，
结构由记忆里的结论、否决理由、约束决定。这样评审在自己机器上跑出来的
结果和这里完全一致。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from . import memory
from .index import Index
from .pc import PowerContextClient

TOPIC_QUERY = memory.PREFIX_KEY


def _refs_block(records: List[memory.MemoryRecord]) -> Dict[str, str]:
    refs: Dict[str, str] = {}
    for record in records:
        paper = record.payload.get("paper")
        if paper and paper not in refs:
            refs[paper] = str(record.payload.get("title") or paper)
    return refs


def build_brief(index: Index, pc: PowerContextClient, topic: str,
                top_k: int = 6) -> Dict[str, Any]:
    records = memory.load_records(pc, TOPIC_QUERY, limit=50)
    all_findings = memory.by_type(records, "finding")
    # 主题命中的结论排前面，其余结论仍然保留——写综述时需要全领域视角
    matched = [r for r in all_findings
               if topic in str(r.payload.get("topic", "")) or not r.payload.get("topic")]
    rest = [r for r in all_findings if r not in matched]
    findings = matched + rest
    decisions = memory.by_type(records, "decision")
    rejected = [r for r in decisions if str(r.payload.get("verdict", "")).lower()
                in {"reject", "drop", "否", "否决"}]
    constraints = memory.by_type(records, "constraint")
    hits = index.search(topic, top_k=top_k)

    papers = {paper["paper_id"]: paper for paper in index.papers()}
    return {
        "topic": topic,
        "findings": [r.as_dict() for r in findings],
        "rejected": [r.as_dict() for r in rejected],
        "constraints": [r.as_dict() for r in constraints],
        "hits": [hit.as_dict() for hit in hits],
        "papers": papers,
        "memory_calls": pc.calls[-4:],
    }


def render_brief_markdown(brief: Dict[str, Any]) -> str:
    topic = brief["topic"]
    papers: Dict[str, Any] = brief["papers"]
    findings = brief["findings"]
    rejected = brief["rejected"]
    constraints = brief["constraints"]
    hits = brief["hits"]

    lines: List[str] = [f"# 综述初稿：{topic}", ""]

    cited = []
    for item in findings:
        if item.get("paper") and item["paper"] not in cited:
            cited.append(item["paper"])
    for hit in hits:
        if hit["paper_id"] not in cited:
            cited.append(hit["paper_id"])

    years = sorted(
        (papers[pid]["year"], pid) for pid in cited
        if pid in papers and papers[pid].get("year")
    )
    if years:
        lines += ["## 研究脉络", ""]
        for year, pid in years:
            lines.append(f"- **{year}**　{papers[pid]['title']}　`[{pid}]`")
        lines.append("")

    lines += ["## 已有结论", ""]
    if findings:
        for item in findings:
            note = f"（依据：{item['evidence']}）" if item.get("evidence") else ""
            lines.append(f"- {item.get('text', '')} `[{item.get('paper', '?')}]` {note}")
    else:
        lines.append("- 还没有该主题的结论记录，先用 `litcontext note --kind finding` 补几条。")
    lines.append("")

    if rejected:
        lines += ["## 已排除的路线（附理由）", ""]
        for item in rejected:
            lines.append(f"- **{item.get('method', '未标注')}**：{item.get('text', '')}")
        lines.append("")

    if constraints:
        lines += ["## 实验约束", ""]
        for item in constraints:
            lines.append(f"- {item.get('text', '')}")
        lines.append("")

    if hits:
        lines += ["## 可直接引用的原文段落", ""]
        for hit in hits:
            body = hit["text"].strip().replace("\n", " ")
            lines.append(f"- {body} `[{hit['paper_id']} {hit['section']}]`")
        lines.append("")

    lines += ["## 参考文献", ""]
    for pid in cited:
        paper = papers.get(pid, {})
        authors = paper.get("authors") or "（未记录作者）"
        year = paper.get("year") or "n.d."
        venue = paper.get("venue") or ""
        lines.append(f"- [{pid}] {authors}. {paper.get('title', pid)}. {venue}, {year}.")
    lines.append("")
    return "\n".join(lines)


def build_compare(pc: PowerContextClient) -> Dict[str, Any]:
    records = memory.load_records(pc, TOPIC_QUERY, limit=50)
    edges = memory.by_type(records, "edge")
    return {"edges": [r.as_dict() for r in edges], "calls": pc.calls[-3:]}


def render_compare_markdown(compare: Dict[str, Any]) -> str:
    edges = compare["edges"]
    lines = ["# 方法对比表", ""]
    if not edges:
        lines.append("还没有对比数据，用 `litcontext edge` 记录一条。")
        return "\n".join(lines) + "\n"
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        grouped[str(edge.get("dataset") or "未标注")].append(edge)
    for dataset, rows in grouped.items():
        lines += [f"## 数据集：{dataset}", "",
                  "| 方法 | 指标 | 数值 | 来源 | 备注 |",
                  "| --- | --- | --- | --- | --- |"]
        for row in rows:
            cells = [
                str(row.get("method", "")),
                str(row.get("metric", "")),
                str(row.get("value", "")),
                f"`[{row.get('paper', '?')}]`",
                str(row.get("note", "")),
            ]
            # 表格里的竖线必须转义，否则会被当成列分隔符
            cells = [cell.replace("|", "\\|") for cell in cells]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


def related_topics(records: List[memory.MemoryRecord]) -> Optional[Dict[str, int]]:
    counter: Dict[str, int] = defaultdict(int)
    for record in memory.by_type(records, "finding"):
        topic = record.payload.get("topic")
        if topic:
            counter[str(topic)] += 1
    return dict(counter) or None
