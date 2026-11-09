"""论文解析：把 md / txt / pdf 拆成带章节标签的段落块。

约定 md 文件头部可选元信息块（三引号之间为示例）：

    ---
    title: Event Detection for Non-Intrusive Load Monitoring
    authors: Anderson et al.
    year: 2012
    venue: IECON
    methods: GLR, CUSUM
    datasets: REDD, BLUED
    ---

章节按 Markdown 标题切分；没有标题的文本按固定长度滑动切块。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .text import tokenize

SUPPORTED = {".md", ".markdown", ".txt", ".pdf"}

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)

CHUNK_CHARS = 420
CHUNK_OVERLAP = 60


@dataclass
class Paper:
    paper_id: str
    title: str
    meta: Dict[str, str] = field(default_factory=dict)
    path: str = ""
    passages: List["Passage"] = field(default_factory=list)


@dataclass
class Passage:
    section: str
    ordinal: int
    text: str
    tokens: str


def _parse_front_matter(raw: str) -> tuple[Dict[str, str], str]:
    match = _FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    meta: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip()
    return meta, raw[match.end():]


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as error:  # pragma: no cover - 依赖缺失路径
        raise RuntimeError(
            f"解析 PDF 需要 pypdf：pip install pypdf（{path.name}）"
        ) from error
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _split_sections(body: str) -> List[tuple[str, str]]:
    sections: List[tuple[str, str]] = []
    current, buffer = "正文", []
    for line in body.splitlines():
        match = _HEADING.match(line.strip())
        if match:
            text = "\n".join(buffer).strip()
            if text:
                sections.append((current, text))
            current, buffer = match.group(2).strip() or "正文", []
        else:
            buffer.append(line)
    tail = "\n".join(buffer).strip()
    if tail:
        sections.append((current, tail))
    return sections or [("正文", body.strip())]


def _chunk(text: str) -> List[str]:
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if len(text) <= CHUNK_CHARS:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):
            # 尽量在句号/换行处断开
            window = text[start:end]
            cut = max(window.rfind("。"), window.rfind("."), window.rfind("\n"))
            if cut > CHUNK_CHARS // 2:
                end = start + cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return [c for c in chunks if c]


def parse_file(path: Path) -> Paper:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"不支持的格式：{path.suffix}（支持 {sorted(SUPPORTED)}）")

    raw = _read_pdf(path) if suffix == ".pdf" else path.read_text(encoding="utf-8", errors="replace")
    meta, body = _parse_front_matter(raw)

    title = meta.get("title") or path.stem
    paper_id = meta.get("id") or hashlib.sha1(title.encode("utf-8")).hexdigest()[:8]

    passages: List[Passage] = []
    ordinal = 0
    for section, section_text in _split_sections(body):
        for chunk in _chunk(section_text):
            ordinal += 1
            passages.append(
                Passage(
                    section=section,
                    ordinal=ordinal,
                    text=chunk,
                    tokens=" ".join(tokenize(f"{title} {section} {chunk}")),
                )
            )
    if not passages:
        raise ValueError(f"没有解析出任何正文段落：{path}")
    return Paper(paper_id=paper_id, title=title, meta=meta, path=str(path), passages=passages)
