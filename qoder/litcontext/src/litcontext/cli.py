"""命令行入口：导入 / 检索 / 记笔记 / 召回 / 出稿。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import memory, report
from .builder import build_resume, render_resume_markdown
from .config import Config
from .index import Index
from .parser import SUPPORTED
from .pc import PowerContextClient, PowerContextError
from .text import highlight_snippet


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def _ctx(args: argparse.Namespace):
    cfg = Config.load(
        data_dir=getattr(args, "data_dir", None),
        pc_url=getattr(args, "pc_url", None),
        scope_key=getattr(args, "scope_key", None),
    )
    index = Index(cfg.db_path)
    pc = PowerContextClient(cfg.pc_url, cfg.scope_key, cfg.scope_title,
                            timeout=cfg.timeout,
                            cache_file=cfg.data_dir / "scope_id.txt")
    return cfg, index, pc


def _expand(paths: List[str]) -> List[Path]:
    files: List[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(
                p for p in path.rglob("*")
                if p.suffix.lower() in SUPPORTED and not p.name.lower().startswith("readme")
            ))
        elif path.exists():
            files.append(path)
        else:
            raise SystemExit(f"路径不存在：{raw}")
    return files


# -- 子命令 -----------------------------------------------------------------
def cmd_doctor(args: argparse.Namespace) -> int:
    cfg, index, pc = _ctx(args)
    stats = index.stats()
    alive = pc.healthy()
    print(f"数据目录       {cfg.data_dir}")
    print(f"本地索引       {stats['papers']} 篇 / {stats['passages']} 段（SQLite）")
    print(f"PowerContext   {cfg.pc_url} -> {'可用' if alive else '不可达'}")
    if alive:
        scope_id = pc.ensure_scope()
        print(f"scope          {scope_id}（{cfg.scope_key}）")
        records = memory.load_records(pc, "LITCORE", limit=50)
        counts = {}
        for record in records:
            counts[record.type] = counts.get(record.type, 0) + 1
        print(f"记忆条数       {len(records)}  {counts if counts else ''}")
    else:
        print("启动方式       powercontext server run   （详见 RUNBOOK.md）")
        return 2
    index.close()
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    cfg, index, pc = _ctx(args)
    files = _expand(args.paths)
    if not files:
        print("没有找到可导入的文件")
        return 1
    total = 0
    for path in files:
        info = index.import_file(path)
        total += 1
        print(f"[导入] {info['paper_id']:<8} {info['title'][:48]:<48} {info['passages']:>3} 段")
        if not args.no_source:
            try:
                first = index.contexts_around(str(info["paper_id"]), limit=2)
                excerpt = "\n\n".join(str(item["text"]) for item in first)
                pc.capture_source(
                    f"litcontext/paper/{info['paper_id']}",
                    f"{info['title']}\n\n{excerpt}",
                    {"kind": "paper", "paper_id": info["paper_id"],
                     "title": info["title"], "year": info["year"]},
                )
            except PowerContextError as error:
                print(f"       （Source 未写入：{error}）")
    stats = index.stats()
    print(f"完成：新增/更新 {total} 篇，索引现有 {stats['papers']} 篇 {stats['passages']} 段")
    index.close()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    cfg, index, pc = _ctx(args)
    hits = index.search(args.query, top_k=args.top, year_from=args.year_from,
                        year_to=args.year_to, method=args.method, dataset=args.dataset)
    if args.json:
        print(json.dumps([hit.as_dict() for hit in hits], ensure_ascii=False, indent=2))
        index.close()
        return 0 if hits else 1
    if not hits:
        print("没有命中。试试更短的关键词，或先 `litcontext ingest` 导入文献。")
        index.close()
        return 1
    for rank, hit in enumerate(hits, 1):
        year = hit.year or "----"
        print(f"{rank}. [{hit.paper_id}] {year} {hit.title}")
        print(f"   §{hit.section}  score={hit.score:.2f}")
        print(f"   {highlight_snippet(hit.text, args.query, 200)}")
        print()
    index.close()
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    cfg, index, pc = _ctx(args)
    try:
        if args.kind == "finding":
            result = memory.record_finding(pc, args.paper or "?", args.topic or "通用",
                                           args.text, evidence=args.evidence or "")
        elif args.kind == "decision":
            result = memory.record_decision(pc, args.topic or "通用", args.method or "未标注",
                                            args.verdict, args.text, reason=args.reason or "")
        else:
            result = memory.record_constraint(pc, args.text, reason=args.reason or "")
    except PowerContextError as error:
        print(f"写入失败：{error}")
        return 2
    print(f"[记忆已写入] {args.kind} -> {json.dumps(result, ensure_ascii=False)[:120]}")
    index.close()
    return 0


def cmd_progress(args: argparse.Namespace) -> int:
    cfg, index, pc = _ctx(args)
    try:
        memory.record_progress(pc, args.done, args.next, current=args.current or "")
    except PowerContextError as error:
        print(f"写入失败：{error}")
        return 2
    print("[记忆已写入] progress")
    index.close()
    return 0


def cmd_edge(args: argparse.Namespace) -> int:
    cfg, index, pc = _ctx(args)
    try:
        memory.record_edge(pc, args.paper, args.method, args.dataset, args.metric,
                           args.value, note=args.note or "")
    except PowerContextError as error:
        print(f"写入失败：{error}")
        return 2
    print("[记忆已写入] edge")
    index.close()
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    cfg, index, pc = _ctx(args)
    card = build_resume(pc, max_bytes=args.max_bytes)
    if args.json:
        print(json.dumps(card, ensure_ascii=False, indent=2))
    else:
        print(render_resume_markdown(card))
        print("PowerContext 调用：")
        for call in card["calls"]:
            print(f"  {call['method']} {call['path']} -> {call['status']}")
    index.close()
    return 0 if not card["errors"] else 2


def cmd_brief(args: argparse.Namespace) -> int:
    cfg, index, pc = _ctx(args)
    brief = report.build_brief(index, pc, args.topic, top_k=args.top)
    markdown = report.render_brief_markdown(brief)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        print(f"已写出 {out}（{len(markdown)} 字符，引用 {len(brief['hits'])} 段原文）")
    else:
        print(markdown)
    index.close()
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    cfg, index, pc = _ctx(args)
    data = report.build_compare(pc)
    markdown = report.render_compare_markdown(data)
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"已写出 {args.out}（{len(data['edges'])} 条对比记忆）")
    else:
        print(markdown)
    index.close()
    return 0


def cmd_papers(args: argparse.Namespace) -> int:
    cfg, index, pc = _ctx(args)
    rows = index.papers()
    if not rows:
        print("索引为空，先 `litcontext ingest data/samples`")
    for row in rows:
        print(f"[{row['paper_id']}] {row['year'] or '----'}  {row['title']}  "
              f"({row['passage_count']} 段, {row['methods'] or '未标注方法'})")
    index.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .web import serve
    cfg, index, pc = _ctx(args)
    index.close()
    serve(cfg, port=args.port, open_browser=not args.no_browser)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="litcontext",
        description="NILM 科研文献助手：本地段落检索 + PowerContext 记忆",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", help="数据目录（默认 qoder/.data）")
    common.add_argument("--pc-url", help="PowerContext 地址（默认 http://127.0.0.1:8000）")
    common.add_argument("--scope-key", help="scope 幂等键，同一研究方向用同一个")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", parents=[common], help="检查索引与 PowerContext 状态")
    sub.epilog = ""

    p = sub.add_parser("ingest", parents=[common], help="导入论文（md/txt/pdf 或目录）")
    p.add_argument("paths", nargs="+")
    p.add_argument("--no-source", action="store_true", help="不写 PowerContext Source")

    p = sub.add_parser("search", parents=[common], help="检索原文段落")
    p.add_argument("query")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--year-from", type=int)
    p.add_argument("--year-to", type=int)
    p.add_argument("--method")
    p.add_argument("--dataset")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("note", parents=[common], help="写入一条结论/取舍/约束记忆")
    p.add_argument("--kind", choices=["finding", "decision", "constraint"], default="finding")
    p.add_argument("--text", required=True)
    p.add_argument("--paper")
    p.add_argument("--topic")
    p.add_argument("--method")
    p.add_argument("--verdict", default="keep", choices=["keep", "reject", "unsure"])
    p.add_argument("--evidence")
    p.add_argument("--reason")

    p = sub.add_parser("progress", parents=[common], help="写入阅读/实验进度")
    p.add_argument("--done", required=True)
    p.add_argument("--next", required=True)
    p.add_argument("--current")

    p = sub.add_parser("edge", parents=[common], help="写入一条方法对比记录")
    p.add_argument("--paper", required=True)
    p.add_argument("--method", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--metric", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--note")

    p = sub.add_parser("resume", parents=[common], help="召回上次进度与已否决路线")
    p.add_argument("--json", action="store_true")
    p.add_argument("--max-bytes", type=int, default=4000)

    p = sub.add_parser("brief", parents=[common], help="生成综述初稿")
    p.add_argument("--topic", required=True)
    p.add_argument("--top", type=int, default=6)
    p.add_argument("-o", "--out")

    p = sub.add_parser("compare", parents=[common], help="生成方法对比表")
    p.add_argument("-o", "--out")

    sub.add_parser("papers", parents=[common], help="列出已导入文献")

    p = sub.add_parser("serve", parents=[common], help="启动本地 Web UI")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    return parser


COMMANDS = {
    "doctor": cmd_doctor,
    "ingest": cmd_ingest,
    "search": cmd_search,
    "note": cmd_note,
    "progress": cmd_progress,
    "edge": cmd_edge,
    "resume": cmd_resume,
    "brief": cmd_brief,
    "compare": cmd_compare,
    "papers": cmd_papers,
    "serve": cmd_serve,
}


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_stdout()
    args = build_parser().parse_args(argv)
    handler = COMMANDS[args.command]
    try:
        return handler(args)
    except PowerContextError as error:
        print(f"PowerContext 调用失败：{error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
