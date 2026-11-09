"""Context builder: assemble the development context for one task.

Given a task file, the builder:

1. extracts retrieval terms from the task description;
2. queries the store (seekdb / OceanBase) for matching spec items, code
   symbols and test cases - every entry in the output comes from these real
   database query results;
3. verifies that every cited source path actually exists in the project;
4. recalls persisted task state from PowerContext (if a server is running),
   including completed work, open TODOs and previous verification results;
5. emits both a machine-readable dict (JSON) and a Markdown rendering for
   the AI coding assistant.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .importer import TaskInfo, parse_task_file
from .retriever import extract_terms, retrieve_specs, retrieve_symbols, retrieve_tests
from .state import PowerContextClient
from .store import BaseStore


def _exists(cfg: Config, rel_path: str) -> bool:
    try:
        return (cfg.project_dir / rel_path).exists()
    except OSError:
        return False


def build_context(cfg: Config, store: BaseStore, task_path: Path,
                  pc: Optional[PowerContextClient] = None) -> Dict[str, Any]:
    task: TaskInfo = parse_task_file(task_path)

    retrieval_text = "\n".join([task.title, task.goal, task.change_targets, task.preserve, task.verification])
    terms = extract_terms(retrieval_text)

    specs = retrieve_specs(store, terms, limit=4)
    symbols = retrieve_symbols(store, terms, limit=6)
    tests = retrieve_tests(store, terms, limit=8)

    # source verification: only cite entries whose file really exists
    specs = [s for s in specs if _exists(cfg, s["file"])]
    symbols = [s for s in symbols if _exists(cfg, s["file"])]
    tests = [t for t in tests if _exists(cfg, t["file"])]

    # task state from PowerContext (survives module restarts)
    task_state: Optional[Dict[str, Any]] = None
    state_error: Optional[str] = None
    if pc is not None:
        try:
            task_state = pc.load_task_state(task.task_id)
        except Exception as error:  # server down etc.
            state_error = str(error)

    # display paths relative to the repo (prefix the project dir name) so
    # evaluators can locate the file directly from the repo root
    project_prefix = cfg.project_dir.resolve().name

    context: Dict[str, Any] = {
        "task": task.summary(),
        "retrieval": {"terms": terms, "backend": cfg.store_backend},
        "specs": [
            {
                "item_key": s["item_key"],
                "spec_id": s["spec_id"],
                "title": s["title"],
                "content": s["content"],
                "source_file": f"{project_prefix}/{s['file']}",
                "content_hash": s["content_hash"],
            }
            for s in specs
        ],
        "code": [
            {
                "symbol": s["symbol"],
                "qualname": s["qualname"],
                "kind": s["kind"],
                "file": f"{project_prefix}/{s['file']}",
                "line": s["line"],
                "signature": s["signature"],
                "docstring": s["docstring"],
            }
            for s in symbols
        ],
        "tests": [
            {
                "test_name": t["test_name"],
                "file": f"{project_prefix}/{t['file']}",
                "role": t["role"],
                "docstring": t["docstring"],
            }
            for t in tests
        ],
        "task_state": task_state,
        "state_source": "powercontext" if task_state is not None else None,
        "state_error": state_error,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return context


def render_markdown(context: Dict[str, Any]) -> str:
    task = context["task"]
    lines: List[str] = []
    lines.append(f"# 开发上下文：{task['title']}")
    lines.append("")
    lines.append(f"- 任务 ID：{task['task_id']}")
    lines.append(f"- 任务定义：{task['file']}")
    lines.append(f"- 生成时间：{context['generated_at']}")
    lines.append(f"- 检索后端：{context['retrieval']['backend']}（查询词：{'、'.join(context['retrieval']['terms'])}）")
    lines.append("")

    lines.append("## 任务目标")
    lines.append(task["goal"] or "（见任务定义文件）")
    if task["change_targets"]:
        lines.append("")
        lines.append("## 预期修改位置（来自任务定义）")
        lines.append(task["change_targets"])
    if task["preserve"]:
        lines.append("")
        lines.append("## 必须保持的行为")
        lines.append(task["preserve"])
    lines.append("")

    lines.append("## 适用规格条目")
    if context["specs"]:
        for spec in context["specs"]:
            lines.append(f"### {spec['item_key']} {spec['title']}")
            lines.append(f"来源：`{spec['source_file']}`（内容指纹 {spec['content_hash']}）")
            lines.append("")
            lines.append(spec["content"])
            lines.append("")
    else:
        lines.append("（未检索到相关规格）")
    lines.append("")

    lines.append("## 相关代码符号")
    if context["code"]:
        lines.append("| 符号 | 类型 | 位置 | 签名 |")
        lines.append("| --- | --- | --- | --- |")
        for sym in context["code"]:
            lines.append(
                f"| `{sym['qualname']}` | {sym['kind']} | `{sym['file']}:{sym['line']}` | `{sym['signature']}` |"
            )
    else:
        lines.append("（未检索到相关符号）")
    lines.append("")

    lines.append("## 验证测试")
    if context["tests"]:
        lines.append("| 测试 | 角色 | 文件 | 说明 |")
        lines.append("| --- | --- | --- | --- |")
        for test in context["tests"]:
            lines.append(
                f"| `{test['test_name']}` | {test['role']} | `{test['file']}` | {test['docstring'] or ''} |"
            )
    else:
        lines.append("（未检索到相关测试）")
    lines.append("")

    lines.append("## 任务状态（来自 PowerContext）")
    state = context.get("task_state")
    if state:
        for key, value in state.items():
            if key.startswith("_"):
                continue
            lines.append(f"- **{key}**：{value}")
    elif context.get("state_error"):
        lines.append(f"（状态读取失败：{context['state_error']}）")
    else:
        lines.append("（尚无已保存状态，本次为该任务的首次上下文构建）")
    lines.append("")

    lines.append("## 使用说明（给 AI 开发助手）")
    lines.append(
        "- 请严格遵循上方“适用规格条目”实现任务目标；"
        "“必须保持的行为”与回归测试不得破坏。\n"
        "- 修改仅限“相关代码符号”及任务定义声明的位置。\n"
        "- 完成后运行“验证测试”中列出的全部测试。"
    )
    return "\n".join(lines)
