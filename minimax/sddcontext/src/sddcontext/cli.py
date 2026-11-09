"""Command line entry point.

Usage:
    sdd import                          # (re)import specs/code/tests into the store
    sdd context --task project/tasks/001-add-status-filter.md
    sdd implement --task project/tasks/001-add-status-filter.md
    sdd verify --label pre|post
    sdd state save --task <task.md> --json '{"done": [...], "todo": [...]}'
    sdd state show --task <task.md>
    sdd check                            # health/config check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .agent import implement
from .config import Config
from .context_builder import build_context, render_markdown
from .importer import import_project, parse_task_file
from .state import PowerContextClient
from .store import open_store
from .verify import run_tests


def _repo_root(cfg: Config) -> Path:
    """The git repo root that contains the minimax/ directory."""
    for ancestor in cfg.project_dir.resolve().parents:
        if (ancestor / "minimax").is_dir():
            return ancestor
        if (ancestor / ".git").exists():
            return ancestor
    return cfg.project_dir.resolve().parent


def _powercontext(cfg: Config, required: bool) -> Optional[PowerContextClient]:
    pc = PowerContextClient(cfg.powercontext_url, cfg.work_dir)
    if pc.healthy():
        return pc
    if required:
        print(
            f"error: PowerContext server is not reachable at {cfg.powercontext_url}. "
            "Start it with: powercontext server run",
            file=sys.stderr,
        )
        sys.exit(2)
    return None


def cmd_import(cfg: Config, args: argparse.Namespace) -> int:
    store = open_store(cfg)
    counts = import_project(cfg, store)
    store.close()
    print(f"[import] backend={cfg.store_backend}")
    for key, value in counts.items():
        print(f"[import] {key}: {value}")
    return 0


def cmd_context(cfg: Config, args: argparse.Namespace) -> int:
    task_path = Path(args.task)
    if not task_path.exists():
        print(f"error: task file not found: {task_path}", file=sys.stderr)
        return 1
    store = open_store(cfg)
    pc = _powercontext(cfg, required=False)
    context = build_context(cfg, store, task_path, pc)
    store.close()

    if args.out == "json":
        print(json.dumps(context, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(context))

    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(
            json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[context] machine-readable context saved to {args.save}", file=sys.stderr)
    return 0


def cmd_implement(cfg: Config, args: argparse.Namespace) -> int:
    task_path = Path(args.task)
    if not task_path.exists():
        print(f"error: task file not found: {task_path}", file=sys.stderr)
        return 1
    store = open_store(cfg)
    pc = _powercontext(cfg, required=False)
    context = build_context(cfg, store, task_path, pc)
    store.close()
    markdown = render_markdown(context)

    task_id = context["task"]["task_id"]
    task_json = Path(args.context_out or (cfg.work_dir / f"context-{task_id}.json"))
    task_json.parent.mkdir(parents=True, exist_ok=True)
    task_json.write_text(
        json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    record = implement(cfg, markdown, task_id, _repo_root(cfg), pc)
    print(f"[implement] model={record.model} task={record.task_id}")
    for path in record.changed_files:
        print(f"[implement] changed: {path}")
    print(f"[implement] interaction record saved under {cfg.evidence_dir}/minimax-records/")
    return 0


def cmd_verify(cfg: Config, args: argparse.Namespace) -> int:
    result = run_tests(cfg, args.label)
    print(
        f"[verify:{args.label}] exit={result.exit_code} "
        f"passed={result.passed} failed={result.failed} errors={result.errors} "
        f"commit={result.commit}"
    )
    print(f"[verify:{args.label}] log: {result.log_file}")
    return result.exit_code


def cmd_state_save(cfg: Config, args: argparse.Namespace) -> int:
    pc = _powercontext(cfg, required=True)
    task = parse_task_file(Path(args.task))
    try:
        state = json.loads(args.json)
    except json.JSONDecodeError as error:
        print(f"error: --json is not valid JSON: {error}", file=sys.stderr)
        return 1
    if not isinstance(state, dict):
        print("error: --json must be a JSON object", file=sys.stderr)
        return 1
    result = pc.save_task_state(task.task_id, state)
    print(f"[state] saved task {task.task_id} state to PowerContext")
    print(f"[state] citation: {json.dumps(result, ensure_ascii=False)[:300]}")
    return 0


def cmd_state_show(cfg: Config, args: argparse.Namespace) -> int:
    pc = _powercontext(cfg, required=True)
    task = parse_task_file(Path(args.task))
    state = pc.load_task_state(task.task_id)
    if state is None:
        print(f"[state] no saved state for task {task.task_id}")
        return 1
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def cmd_check(cfg: Config, args: argparse.Namespace) -> int:
    print(f"[check] sddcontext {__version__}")
    print(f"[check] store backend: {cfg.store_backend}")
    ok = True
    try:
        store = open_store(cfg)
        store.init_schema()
        from .store import SPEC_TABLE, SYMBOL_TABLE, TEST_TABLE
        print(f"[check] store ok: specs={store.count(SPEC_TABLE)} "
              f"symbols={store.count(SYMBOL_TABLE)} tests={store.count(TEST_TABLE)}")
        store.close()
    except Exception as error:
        ok = False
        print(f"[check] store FAILED: {error}")
    pc = PowerContextClient(cfg.powercontext_url, cfg.work_dir)
    pc_ok = pc.healthy()
    print(f"[check] powercontext at {cfg.powercontext_url}: "
          f"{'healthy' if pc_ok else 'unreachable'}")
    print(f"[check] minimax base_url={cfg.minimax_base_url} "
          f"model={cfg.minimax_model} key={'set' if cfg.minimax_api_key else 'NOT SET'}")
    return 0 if ok and pc_ok else 1


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="sdd", description="SDD context module")
    parser.add_argument("--project", default=None, help="business project directory")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("import", help="(re)import specs/code/tests into the store")

    p_ctx = sub.add_parser("context", help="build the development context for a task")
    p_ctx.add_argument("--task", required=True)
    p_ctx.add_argument("--out", choices=["md", "json"], default="md")
    p_ctx.add_argument("--save", default=None, help="also save JSON context to this path")

    p_imp = sub.add_parser("implement", help="run the MiniMax implementation step")
    p_imp.add_argument("--task", required=True)
    p_imp.add_argument("--context-out", default=None)

    p_ver = sub.add_parser("verify", help="run project tests and record logs")
    p_ver.add_argument("--label", default="run", help="log label, e.g. pre / post")

    p_save = sub.add_parser("state", help="task state operations")
    state_sub = p_save.add_subparsers(dest="state_command", required=True)
    p_ssave = state_sub.add_parser("save")
    p_ssave.add_argument("--task", required=True)
    p_ssave.add_argument("--json", required=True, help="JSON object with task state")
    p_sshow = state_sub.add_parser("show")
    p_sshow.add_argument("--task", required=True)

    sub.add_parser("check", help="health/configuration check")

    args = parser.parse_args(argv)
    cfg = Config()
    if args.project:
        cfg.project_dir = Path(args.project)
    cfg.ensure_dirs()

    handlers = {
        "import": cmd_import,
        "context": cmd_context,
        "implement": cmd_implement,
        "verify": cmd_verify,
        "state": None,  # dispatched below
        "check": cmd_check,
    }
    if args.command == "state":
        handler = cmd_state_save if args.state_command == "save" else cmd_state_show
        return handler(cfg, args)
    return handlers[args.command](cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
