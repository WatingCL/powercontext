"""Retrieval layer: pull relevant specs / code symbols / tests from the store.

Terms are extracted from the task description (CJK bigrams + latin words and
identifiers). Every candidate set is fetched by a real database query (see
``BaseStore.search``) and then re-ranked in-process by term-hit counts, which
keeps results deterministic and explainable.
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence

from .store import SPEC_TABLE, SYMBOL_TABLE, TEST_TABLE, BaseStore

LATIN_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
CJK_RE = re.compile(r"[\u4e00-\u9fff]+")

# Terms that carry no signal for spec/code retrieval.
STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "for", "in", "on", "with",
    "must", "be", "is", "are", "as", "by", "not", "it", "this", "that",
    "version", "file", "task", "test", "tests", "project", "see", "md",
    "当前的", "目前", "以及", "并且", "或者", "必须", "一个", "上述", "如下",
}


def extract_terms(text: str, max_terms: int = 14) -> List[str]:
    """Extract retrieval terms: latin identifiers/words + CJK bigrams."""
    terms: List[str] = []
    for match in LATIN_TOKEN_RE.findall(text):
        token = match.rstrip(".").lower()
        if len(token) >= 3 and token not in STOPWORDS:
            terms.append(token)
    for run in CJK_RE.findall(text):
        compact = re.sub(r"[的了吗呢吧，。；：、（）》]", "", run)
        for i in range(len(compact) - 1):
            terms.append(compact[i : i + 2])
        if len(compact) == 1:
            terms.append(compact)
    # de-duplicate, keep order
    seen: Dict[str, None] = {}
    for term in terms:
        if term not in STOPWORDS:
            seen.setdefault(term, None)
    return list(seen.keys())[:max_terms]


def _hit_count(row: Dict, terms: Sequence[str]) -> int:
    blob = " ".join(str(v) for v in row.values()).lower()
    return sum(1 for term in terms if term.lower() in blob)


def _rerank(rows: List[Dict], terms: Sequence[str], limit: int) -> List[Dict]:
    scored = sorted(rows, key=lambda r: -_hit_count(r, terms))
    return scored[:limit]


def retrieve_specs(store: BaseStore, terms: Sequence[str], limit: int = 4) -> List[Dict]:
    rows = store.search(SPEC_TABLE, terms, limit=limit)
    return _rerank(rows, terms, limit)


def retrieve_symbols(store: BaseStore, terms: Sequence[str], limit: int = 6) -> List[Dict]:
    rows = store.search(SYMBOL_TABLE, terms, limit=limit)
    return _rerank(rows, terms, limit)


def retrieve_tests(store: BaseStore, terms: Sequence[str], limit: int = 8) -> List[Dict]:
    rows = store.search(TEST_TABLE, terms, limit=limit)
    # keep both target tests and regression tests, targets first
    return _rerank(rows, terms, limit)
