"""Import project material (specs / code symbols / test cases) into the store.

The importer parses:

- ``specs/*.md``  - specification documents, split into addressable items
  (``## SPEC-XXX-N title`` headings define item boundaries);
- ``src/**/*.py`` - code symbols (modules, classes, functions, methods) via
  the ``ast`` module, with file + line + signature + docstring;
- ``tests/*.py``  - test functions with a coarse role classification
  (``target`` for new-behaviour tests, ``regression`` otherwise).

Re-running the importer after a spec file changes replaces the stored rows,
so the context builder always reflects the latest imported content.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config
from .store import SPEC_TABLE, SYMBOL_TABLE, TEST_TABLE, BaseStore, content_hash

SPEC_ITEM_RE = re.compile(r"^##\s+(SPEC-\d+-[A-Z])\s+(.*)$")
SPEC_DOC_RE = re.compile(r"^#\s+(SPEC-\d+)[：:\s]*(.*)$")

TEST_ROLE_HINTS = ("filter", "筛选")


@dataclass
class SpecItem:
    item_key: str
    spec_id: str
    item_id: str
    title: str
    content: str
    file: str

    def to_row(self) -> Dict[str, str]:
        return {
            "item_key": self.item_key,
            "spec_id": self.spec_id,
            "item_id": self.item_id,
            "title": self.title,
            "content": self.content,
            "file": self.file,
            "content_hash": content_hash(self.content),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


@dataclass
class CodeSymbol:
    symbol: str
    kind: str
    qualname: str
    file: str
    line: int
    signature: str
    docstring: str

    @property
    def symbol_key(self) -> str:
        return f"{self.file}::{self.qualname}"

    def to_row(self) -> Dict[str, object]:
        return {
            "symbol_key": self.symbol_key,
            "symbol": self.symbol,
            "kind": self.kind,
            "qualname": self.qualname,
            "file": self.file,
            "line": self.line,
            "signature": self.signature,
            "docstring": self.docstring or "",
        }


@dataclass
class TestCaseInfo:
    test_name: str
    file: str
    role: str
    docstring: str

    @property
    def test_key(self) -> str:
        return f"{self.file}::{self.test_name}"

    def to_row(self) -> Dict[str, object]:
        return {
            "test_key": self.test_key,
            "test_name": self.test_name,
            "file": self.file,
            "role": self.role,
            "docstring": self.docstring or "",
        }


@dataclass
class TaskInfo:
    task_id: str
    title: str
    file: str
    goal: str = ""
    preserve: str = ""
    verification: str = ""
    change_targets: str = ""
    raw: str = field(default="", repr=False)

    def summary(self) -> Dict[str, str]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "file": self.file,
            "goal": self.goal,
            "change_targets": self.change_targets,
            "preserve": self.preserve,
            "verification": self.verification,
        }


def _rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def parse_spec_file(path: Path, project_dir: Path) -> List[SpecItem]:
    text = path.read_text(encoding="utf-8")
    rel_path = _rel(path, project_dir)
    items: List[SpecItem] = []
    spec_id = ""
    spec_doc_title = ""
    current_key: Optional[str] = None
    current_title = ""
    buffer: List[str] = []

    def flush() -> None:
        if current_key is None:
            return
        content = "\n".join(buffer).strip()
        if content:
            items.append(
                SpecItem(
                    item_key=current_key,
                    spec_id=spec_id,
                    item_id=current_key,
                    title=current_title,
                    content=content,
                    file=rel_path,
                )
            )

    for line in text.splitlines():
        doc_match = SPEC_DOC_RE.match(line)
        if doc_match and not spec_id:
            spec_id = doc_match.group(1)
            spec_doc_title = doc_match.group(2).strip()
            continue
        item_match = SPEC_ITEM_RE.match(line)
        if item_match:
            flush()
            current_key = item_match.group(1)
            current_title = item_match.group(2).strip()
            buffer = []
            continue
        if current_key is not None:
            buffer.append(line)
    flush()

    # Documents with a spec id but no itemised headings: keep the whole body
    # as one item keyed by the spec id itself.
    if spec_id and not items:
        body = "\n".join(
            ln for ln in text.splitlines()
            if not SPEC_DOC_RE.match(ln) and not ln.startswith(">")
        ).strip()
        if body:
            items.append(
                SpecItem(
                    item_key=spec_id,
                    spec_id=spec_id,
                    item_id=spec_id,
                    title=spec_doc_title or spec_id,
                    content=body,
                    file=rel_path,
                )
            )
    for item in items:
        if not item.spec_id:
            item.spec_id = spec_id
    return items


def _signature(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = [a.arg for a in node.args.args]
        defaults_offset = len(args) - len(node.args.defaults)
        rendered = []
        for i, name in enumerate(args):
            di = i - defaults_offset
            if di >= 0 and node.args.defaults[di] is not None:
                rendered.append(f"{name}={ast.unparse(node.args.defaults[di])}")
            else:
                rendered.append(name)
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({', '.join(rendered)})"
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(b) for b in node.bases]
        return f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
    return ""


def _docstring(node: ast.AST) -> str:
    doc = ast.get_docstring(node)
    return (doc or "").strip().splitlines()[0] if doc else ""


def parse_code_symbols(src_dir: Path, project_dir: Path) -> List[CodeSymbol]:
    symbols: List[CodeSymbol] = []
    for path in sorted(src_dir.rglob("*.py")):
        rel_path = _rel(path, project_dir)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_doc = (_docstring(tree) or "")[:200]

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.prefix: List[str] = []

            def _add(self, node: ast.AST, kind: str) -> None:
                name = getattr(node, "name", "")
                qualname = ".".join([*self.prefix, name])
                symbols.append(
                    CodeSymbol(
                        symbol=name,
                        kind=kind,
                        qualname=qualname,
                        file=rel_path,
                        line=node.lineno,
                        signature=_signature(node),
                        docstring=_docstring(node) or (module_doc if kind == "module" else ""),
                    )
                )

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self._add(node, "class")
                self.prefix.append(node.name)
                self.generic_visit(node)
                self.prefix.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                kind = "method" if self.prefix else "function"
                self._add(node, kind)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                kind = "method" if self.prefix else "function"
                self._add(node, kind)

        if module_doc:
            symbols.append(
                CodeSymbol(
                    symbol=path.stem,
                    kind="module",
                    qualname=path.stem,
                    file=rel_path,
                    line=1,
                    signature=f"module {path.stem}",
                    docstring=module_doc,
                )
            )
        Visitor().visit(tree)
    return symbols


def parse_test_cases(tests_dir: Path, project_dir: Path) -> List[TestCaseInfo]:
    cases: List[TestCaseInfo] = []
    for path in sorted(tests_dir.rglob("test_*.py")):
        rel_path = _rel(path, project_dir)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                doc = ast.get_docstring(node) or ""
                hint = doc.lower() + rel_path.lower()
                role = "target" if any(h in hint for h in TEST_ROLE_HINTS) else "regression"
                cases.append(
                    TestCaseInfo(
                        test_name=node.name,
                        file=rel_path,
                        role=role,
                        docstring=doc.strip().splitlines()[0] if doc else "",
                    )
                )
    return cases


TASK_TITLE_RE = re.compile(r"^#\s+任务\s*(\S+)[：:\s]+(.*)$")


def parse_task_file(path: Path) -> TaskInfo:
    text = path.read_text(encoding="utf-8")
    task_id, title = "unknown", path.stem
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        title_match = TASK_TITLE_RE.match(line)
        if title_match:
            task_id, title = title_match.group(1), title_match.group(2).strip()
            continue
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    section_text = lambda key: "\n".join(sections.get(key, [])).strip()
    return TaskInfo(
        task_id=task_id,
        title=title,
        file=path.as_posix(),
        goal=section_text("目标"),
        change_targets=section_text("需要修改的位置"),
        preserve=section_text("必须保持的行为（回归要求）") or section_text("必须保持的行为"),
        verification=section_text("验证"),
        raw=text,
    )


def import_project(cfg: Config, store: BaseStore) -> Dict[str, int]:
    """(Re)import all project material into the store. Returns row counts."""
    if not cfg.project_dir.is_dir():
        raise FileNotFoundError(
            f"project directory not found: {cfg.project_dir} "
            f"(cwd={Path.cwd()}; set SDD_PROJECT_DIR if you run from elsewhere)"
        )
    for required in (cfg.specs_dir, cfg.src_dir, cfg.tests_dir):
        if not required.is_dir():
            raise FileNotFoundError(f"expected directory missing: {required}")

    store.init_schema()

    spec_rows: List[Dict[str, Any]] = []
    for path in sorted(cfg.specs_dir.glob("*.md")):
        spec_rows.extend(item.to_row() for item in parse_spec_file(path, cfg.project_dir))
    store.replace_rows(SPEC_TABLE, spec_rows)

    symbol_rows = [s.to_row() for s in parse_code_symbols(cfg.src_dir, cfg.project_dir)]
    store.replace_rows(SYMBOL_TABLE, symbol_rows)

    test_rows = [t.to_row() for t in parse_test_cases(cfg.tests_dir, cfg.project_dir)]
    store.replace_rows(TEST_TABLE, test_rows)

    total = len(spec_rows) + len(symbol_rows) + len(test_rows)
    if total == 0:
        raise RuntimeError(
            "import found no material at all - refusing to wipe the store silently"
        )

    return {
        "spec_items": len(spec_rows),
        "code_symbols": len(symbol_rows),
        "test_cases": len(test_rows),
    }
