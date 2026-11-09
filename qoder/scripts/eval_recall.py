#!/usr/bin/env python
"""检索召回评测：16 条标注查询，对比"关闭同义扩展"与"开启同义扩展"。

判定口径：某条查询的结果里出现任一期望论文即算命中（Recall@k）；
MRR 取第一条命中论文排名的倒数。标注的标准是"哪篇文献真正回答了这个问题"，
不是"哪篇文献恰好字面重合"——所以字面检索的漏召回会在这里显形。

用法（索引里要先有 data/samples 的 5 篇）：
    python scripts/eval_recall.py
    python scripts/eval_recall.py --out evidence/recall-eval.md --json evidence/recall-eval.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "litcontext" / "src"))

from litcontext.index import Index  # noqa: E402

# 每条：提问（研究者口语）+ 真正能回答它的论文 + 这条想问什么
QUERIES: List[Dict[str, Any]] = [
    {"q": "投切那一刻怎么捕捉", "expect": ["p-anderson12", "p-hart92"],
     "intent": "事件检测的基本动作"},
    {"q": "门限设多少才不虚警", "expect": ["p-anderson12", "p-review20"],
     "intent": "阈值与虚警（虚警=误报，考同义词）"},
    {"q": "false alarm 太多怎么办", "expect": ["p-anderson12", "p-zeifman11"],
     "intent": "英文提问命中中文正文（误报）"},
    {"q": "隐状态序列怎么推", "expect": ["p-zeifman11"],
     "intent": "HMM 推断（隐状态只在该文出现）"},
    {"q": "有没有事件级标注的公开数据集", "expect": ["p-blued12", "p-review20"],
     "intent": "数据集与标注粒度"},
    {"q": "把总功率拆成单台电器", "expect": ["p-hart92", "p-review20"],
     "intent": "负荷分解（不用分解二字提问）"},
    {"q": "滑动窗口多长合适", "expect": ["p-anderson12"],
     "intent": "窗长选择"},
    {"q": "查准查全怎么一起报", "expect": ["p-review20"],
     "intent": "评测口径（精确率/召回/F1）"},
    {"q": "小功率变化检不出来", "expect": ["p-anderson12", "p-review20"],
     "intent": "小幅跃变瓶颈"},
    {"q": "好几台电器同时开", "expect": ["p-anderson12", "p-review20"],
     "intent": "同时投切导致合并"},
    {"q": "变频空调那种斜坡负载", "expect": ["p-anderson12"],
     "intent": "阶跃假设失效"},
    {"q": "换个房子就失效", "expect": ["p-anderson12", "p-review20"],
     "intent": "跨户迁移与重新标定"},
    {"q": "采样率不同怎么比", "expect": ["p-review20"],
     "intent": "跨数据集可比性"},
    {"q": "有哪些公开数据", "expect": ["p-review20", "p-blued12"],
     "intent": "数据集清单"},
    {"q": "deep learning 在 NILM 上", "expect": ["p-review20"],
     "intent": "数据驱动路线"},
    {"q": "维特比解码", "expect": ["p-zeifman11"],
     "intent": "解码算法（Viterbi 的中文说法）"},
]

TOP_K = 20  # 取够深，避免"排名第 6 也算漏"这种口径争议


def ranked_papers(index: Index, query: str, expand: bool, top_k: int = TOP_K) -> List[str]:
    order: List[str] = []
    for hit in index.search(query, top_k=top_k, expand=expand):
        if hit.paper_id not in order:
            order.append(hit.paper_id)
    return order


def first_rank(order: List[str], expect: List[str]) -> Optional[int]:
    for position, paper_id in enumerate(order, 1):
        if paper_id in expect:
            return position
    return None


def evaluate(index: Index, expand: bool) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for item in QUERIES:
        order = ranked_papers(index, item["q"], expand)
        rank = first_rank(order, item["expect"])
        rows.append({
            "query": item["q"],
            "intent": item["intent"],
            "expect": item["expect"],
            "rank": rank,
            "top3": order[:3],
        })
    total = len(rows)
    return {
        "expand": expand,
        "queries": total,
        "hit_at_1": sum(1 for r in rows if r["rank"] == 1) / total,
        "hit_at_3": sum(1 for r in rows if r["rank"] and r["rank"] <= 3) / total,
        "hit_at_5": sum(1 for r in rows if r["rank"] and r["rank"] <= 5) / total,
        "miss_rate": sum(1 for r in rows if r["rank"] is None) / total,
        "mrr": sum(1 / r["rank"] for r in rows if r["rank"]) / total,
        "rows": rows,
    }


def render_markdown(off: Dict[str, Any], on: Dict[str, Any], stats: Dict[str, Any]) -> str:
    def pct(value: float) -> str:
        return f"{value * 100:.0f}%"

    lines = [
        "# 检索召回评测：同义扩展前 vs 后",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 语料：本地索引 {stats['papers']} 篇 / {stats['passages']} 段（data/samples）",
        f"- 评测查询：{off['queries']} 条标注问题；判定取去重后的前 {TOP_K} 篇论文，"
        "首个命中论文的名次即为结果，无命中记为空",
        "- 关闭扩展 = 纯 BM25 字面重合；开启扩展 = BM25 + 领域同义扩展（扩展词权重 0.4）",
        "",
        "## 总体",
        "",
        "| 指标 | 关闭同义扩展 | 开启同义扩展 | 变化 |",
        "| --- | --- | --- | --- |",
    ]
    for label, key in [("命中@1", "hit_at_1"), ("命中@3", "hit_at_3"),
                       ("命中@5", "hit_at_5"), ("完全未命中率", "miss_rate"),
                       ("MRR", "mrr")]:
        a, b = off[key], on[key]
        delta = b - a
        if key == "miss_rate":
            delta_text = f"{delta * 100:+.0f} pt"  # 降得越多越好
        elif key == "mrr":
            delta_text = f"{delta:+.3f}"
        else:
            delta_text = f"{delta * 100:+.0f} pt"
        formatter = (lambda v: f"{v:.3f}") if key == "mrr" else pct
        lines.append(f"| {label} | {formatter(a)} | {formatter(b)} | {delta_text} |")

    lines += ["", "## 逐条结果", "",
              "| # | 提问 | 想问什么 | 期望论文 | 关闭扩展名次 | 开启扩展名次 |",
              "| --- | --- | --- | --- | --- | --- |"]
    for i, (left, right) in enumerate(zip(off["rows"], on["rows"]), 1):
        expect = "、".join(f"`{pid}`" for pid in left["expect"])
        a = f"{left['rank']}" if left["rank"] else "未命中"
        b = f"{right['rank']}" if right["rank"] else "未命中"
        mark = "" if (left["rank"] or 0) <= (right["rank"] or 99) else " ⬆"
        lines.append(f"| {i} | {left['query']} | {left['intent']} | {expect} | {a} | {b}{mark} |")

    improved = [right["query"] for left, right in zip(off["rows"], on["rows"])
                if right["rank"] and not left["rank"]]
    promoted = [right["query"] for left, right in zip(off["rows"], on["rows"])
                if right["rank"] and left["rank"] and right["rank"] < left["rank"]]
    regressed = [(left["query"], left["rank"], right["rank"])
                 for left, right in zip(off["rows"], on["rows"])
                 if right["rank"] and left["rank"] and right["rank"] > left["rank"]]
    lines += ["", "## 结论", ""]
    if improved:
        lines.append("扩展救回、原先完全搜不到的：")
        lines.append("")
        for item in improved:
            lines.append(f"- 「{item}」")
        lines.append("")
    if promoted:
        lines.append("名次上升的：")
        lines.append("")
        for item in promoted:
            lines.append(f"- 「{item}」")
        lines.append("")
    if regressed:
        lines.append("名次下降的（扩展词稀释了原词权重，代价要说清楚）：")
        lines.append("")
        for item, before, after in regressed:
            lines.append(f"- 「{item}」第 {before} → 第 {after}")
        lines.append("")
    lines += [
        "没变化的条目说明字面检索本来就够用（该术语在本领域只有一种写法），",
        "这类查询不需要扩展——扩展只补「换个说法就问不到」的那部分。",
        "",
        "复现：`python scripts/eval_recall.py`（脚本自带标注，不读外部文件）。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="同义扩展前后的召回对比")
    parser.add_argument("--db", default=str(ROOT / ".data" / "index.sqlite3"))
    parser.add_argument("--out", default=str(ROOT / "evidence" / "recall-eval.md"))
    parser.add_argument("--json", default=str(ROOT / "evidence" / "recall-eval.json"))
    parser.add_argument("--check", action="store_true",
                        help="阈值校验：命中@5 ≥ 0.95 且未命中率 ≤ 0.05，否则退出码 1（CI 用）")
    args = parser.parse_args(argv)

    if not Path(args.db).exists():
        print(f"索引不存在：{args.db}\n先运行：litcontext ingest data/samples")
        return 2

    index = Index(Path(args.db))
    stats = index.stats()
    if not stats["papers"]:
        print("索引为空，先运行：litcontext ingest data/samples")
        index.close()
        return 2

    off = evaluate(index, expand=False)
    on = evaluate(index, expand=True)
    index.close()

    markdown = render_markdown(off, on, stats)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, encoding="utf-8")
    payload = OrderedDict([
        ("generated_at", datetime.now().isoformat(timespec="seconds")),
        ("corpus", stats),
        ("without_synonyms", off),
        ("with_synonyms", on),
    ])
    Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"语料 {stats['papers']} 篇 / {stats['passages']} 段；{off['queries']} 条查询")
    print(f"{'指标':<12}{'关闭扩展':>10}{'开启扩展':>10}")
    for label, key in [("命中@1", "hit_at_1"), ("命中@3", "hit_at_3"),
                       ("命中@5", "hit_at_5"), ("未命中率", "miss_rate"), ("MRR", "mrr")]:
        print(f"{label:<12}{off[key]:>10.3f}{on[key]:>10.3f}")
    print(f"已写出 {out}\n已写出 {args.json}")
    if args.check:
        ok = on["hit_at_5"] >= 0.95 and on["miss_rate"] <= 0.05
        print(f"阈值校验（命中@5≥0.95 且 未命中率≤0.05）：{'通过' if ok else '未通过'}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
