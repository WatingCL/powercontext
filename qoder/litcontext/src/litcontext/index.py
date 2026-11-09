"""本地段落索引：SQLite 存论文元信息与段落，查询时按 BM25 打分。

这里有意不承担"记忆"职责：结论、否决理由、阅读进度全部放在 PowerContext。
本地库只是把论文正文变成可检索的段落，删库重建不会丢掉任何研究判断。
"""

from __future__ import annotations

import math
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .parser import Paper, parse_file
from .synonyms import expand as expand_query
from .text import tokenize

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id    TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    authors     TEXT,
    year        INTEGER,
    venue       TEXT,
    methods     TEXT,
    datasets    TEXT,
    path        TEXT,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS passages (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    section  TEXT,
    ordinal  INTEGER,
    text     TEXT NOT NULL,
    tokens   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_passages_paper ON passages(paper_id);
"""


@dataclass
class Hit:
    paper_id: str
    title: str
    year: Optional[int]
    section: str
    text: str
    score: float
    path: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "year": self.year,
            "section": self.section,
            "text": self.text,
            "score": round(self.score, 3),
            "path": self.path,
        }


class Index:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Web UI 用 ThreadingHTTPServer，每个请求一个线程，因此连接需要跨线程复用，
        # 并用一把锁串行化访问（本场景数据量小，锁开销可忽略）。
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- 写入 ---------------------------------------------------------------
    def import_file(self, path: Path) -> Dict[str, object]:
        paper: Paper = parse_file(path)
        self.import_paper(paper)
        return {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "year": paper.meta.get("year"),
            "passages": len(paper.passages),
        }

    def import_paper(self, paper: Paper) -> None:
        with self._lock:
            self._import_paper(paper)

    def _import_paper(self, paper: Paper) -> None:
        meta = paper.meta
        year: Optional[int] = None
        if meta.get("year", "").isdigit():
            year = int(meta["year"])
        self._conn.execute("DELETE FROM passages WHERE paper_id = ?", (paper.paper_id,))
        self._conn.execute(
            """INSERT INTO papers (paper_id, title, authors, year, venue, methods,
                                   datasets, path, imported_at)
               VALUES (?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(paper_id) DO UPDATE SET
                 title=excluded.title, authors=excluded.authors, year=excluded.year,
                 venue=excluded.venue, methods=excluded.methods,
                 datasets=excluded.datasets, path=excluded.path,
                 imported_at=excluded.imported_at""",
            (
                paper.paper_id,
                paper.title,
                meta.get("authors", ""),
                year,
                meta.get("venue", ""),
                meta.get("methods", ""),
                meta.get("datasets", ""),
                paper.path,
            ),
        )
        self._conn.executemany(
            "INSERT INTO passages (paper_id, section, ordinal, text, tokens) VALUES (?,?,?,?,?)",
            [(paper.paper_id, p.section, p.ordinal, p.text, p.tokens) for p in paper.passages],
        )
        self._conn.commit()

    # -- 查询 ---------------------------------------------------------------
    def papers(self) -> List[Dict[str, object]]:
        with self._lock:
            return self._papers()

    def _papers(self) -> List[Dict[str, object]]:
        rows = self._conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM passages WHERE paper_id = p.paper_id) AS passage_count "
            "FROM papers p ORDER BY year, title"
        ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> Dict[str, object]:
        with self._lock:
            return self._stats()

    def _stats(self) -> Dict[str, object]:
        papers = self._conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        passages = self._conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
        years = self._conn.execute(
            "SELECT MIN(year), MAX(year) FROM papers WHERE year IS NOT NULL"
        ).fetchone()
        return {
            "papers": papers,
            "passages": passages,
            "year_min": years[0],
            "year_max": years[1],
        }

    def search(
        self,
        query: str,
        top_k: int = 5,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        method: Optional[str] = None,
        dataset: Optional[str] = None,
        expand: bool = True,
    ) -> List[Hit]:
        with self._lock:
            return self._search(query, top_k, year_from, year_to, method, dataset, expand)

    def query_weights(self, query: str, expand: bool = True) -> Dict[str, float]:
        """查询会被展开成哪些 term、各自权重多少（供 `--explain` 与评测使用）。"""
        terms = list(dict.fromkeys(tokenize(query)))
        return expand_query(terms) if expand else {term: 1.0 for term in terms}

    def _search(
        self,
        query: str,
        top_k: int = 5,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        method: Optional[str] = None,
        dataset: Optional[str] = None,
        expand: bool = True,
    ) -> List[Hit]:
        terms = tokenize(query)
        if not terms:
            return []
        sql = "SELECT ps.*, p.title, p.year, p.methods, p.datasets, p.path FROM passages ps " \
              "JOIN papers p ON p.paper_id = ps.paper_id WHERE 1=1"
        params: List[object] = []
        if year_from is not None:
            sql += " AND (p.year IS NULL OR p.year >= ?)"
            params.append(year_from)
        if year_to is not None:
            sql += " AND (p.year IS NULL OR p.year <= ?)"
            params.append(year_to)
        if method:
            sql += " AND lower(p.methods) LIKE ?"
            params.append(f"%{method.lower()}%")
        if dataset:
            sql += " AND lower(p.datasets) LIKE ?"
            params.append(f"%{dataset.lower()}%")
        rows = self._conn.execute(sql, params).fetchall()
        if not rows:
            return []

        docs_tokens: List[Counter] = [Counter(r["tokens"].split()) for r in rows]
        doc_freq: Counter = Counter()
        for counter in docs_tokens:
            doc_freq.update(counter.keys())
        n_docs = len(docs_tokens)
        avg_len = sum(sum(c.values()) for c in docs_tokens) / max(1, n_docs)
        k1, b = 1.5, 0.75

        # 查询侧同义扩展：原词权重 1.0，领域词表扩出来的说法权重 0.4。
        # 展开只在查询侧做，索引里始终存原文 token，重建索引不会改变检索口径。
        query_terms = list(dict.fromkeys(terms))
        weights = expand_query(query_terms) if expand else {term: 1.0 for term in query_terms}
        scored: List[Hit] = []
        for row, counter in zip(rows, docs_tokens):
            length = sum(counter.values()) or 1
            score = 0.0
            for term, weight in weights.items():
                tf = counter.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
                score += weight * idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * length / avg_len))
            if score > 0:
                scored.append(
                    Hit(
                        paper_id=row["paper_id"],
                        title=row["title"],
                        year=row["year"],
                        section=row["section"] or "正文",
                        text=row["text"],
                        score=score,
                        path=row["path"] or "",
                    )
                )
        scored.sort(key=lambda hit: hit.score, reverse=True)

        # 同一篇论文最多保留 2 段，避免结果被单篇论文占满
        per_paper: Dict[str, int] = {}
        picked: List[Hit] = []
        for hit in scored:
            if per_paper.get(hit.paper_id, 0) >= 2:
                continue
            per_paper[hit.paper_id] = per_paper.get(hit.paper_id, 0) + 1
            picked.append(hit)
            if len(picked) >= top_k:
                break
        return picked

    def contexts_around(self, paper_id: str, limit: int = 3) -> Iterable[Dict[str, object]]:
        with self._lock:
            return self._contexts_around(paper_id, limit)

    def _contexts_around(self, paper_id: str, limit: int = 3) -> Iterable[Dict[str, object]]:
        rows = self._conn.execute(
            "SELECT section, ordinal, text FROM passages WHERE paper_id = ? "
            "ORDER BY ordinal LIMIT ?",
            (paper_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
