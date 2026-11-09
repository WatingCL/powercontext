"""中英混排分词：英文数字按词切，中文按字符二元组切。

不引第三方分词器是刻意的：评审只要装了 Python 就能跑，检索质量对本场景
（论文段落，术语密集）已经够用，且分词结果可解释、可复现。
"""

from __future__ import annotations

import re
from typing import List

_LATIN = re.compile(r"[a-z0-9][a-z0-9_\-\.]*")
_CJK = re.compile(r"[\u4e00-\u9fff]+")
_STOP = {
    "the", "a", "an", "of", "and", "or", "to", "in", "for", "on", "with",
    "is", "are", "was", "were", "be", "by", "as", "at", "from", "that", "this",
    "we", "our", "it", "its", "can", "which", "these", "using", "used",
    "的", "了", "和", "是", "在", "与", "对", "也", "并", "而", "或", "被", "把",
    "我们", "可以", "一个", "这个", "进行", "通过", "基于", "以及",
}


def tokenize(text: str) -> List[str]:
    """返回检索用 token 列表（已去停用词、已小写）。"""
    text = (text or "").lower()
    tokens: List[str] = []
    for match in _LATIN.finditer(text):
        word = match.group(0).strip(".-")
        if len(word) > 1 and word not in _STOP:
            tokens.append(word)
    for match in _CJK.finditer(text):
        run = match.group(0)
        for i in range(len(run) - 1):
            bigram = run[i:i + 2]
            if bigram not in _STOP:
                tokens.append(bigram)
        if len(run) == 1:
            tokens.append(run)
    return tokens


def highlight_snippet(text: str, query: str, width: int = 160) -> str:
    """截取命中位置附近的片段，用于结果展示。"""
    if not text:
        return ""
    lower, needle = text.lower(), (query or "").strip().lower()
    pos = lower.find(needle) if needle else -1
    if pos < 0:
        for token in tokenize(query)[:6]:
            pos = lower.find(token)
            if pos >= 0:
                break
    if pos < 0:
        return text[:width] + ("…" if len(text) > width else "")
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"
