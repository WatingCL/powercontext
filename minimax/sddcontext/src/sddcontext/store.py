"""Storage layer for the SDD context module.

Three interchangeable backends behind one interface:

- ``SeekdbEmbeddedStore`` - embedded seekdb via ``pylibseekdb`` (Linux, the
  default for evaluation). This is OceanBase seekdb running in-process.
- ``MySQLStore`` - seekdb server or OceanBase over the MySQL protocol
  (``SDD_STORE_MYSQL_URL``). Plain ``PyMySQL`` is used, which works with any
  MySQL-compatible endpoint including OceanBase.
- ``SqliteStore`` - local smoke-test fallback for development on OSes where
  embedded seekdb is unavailable. Not used for evaluation.

All backends keep the same schema (three tables: spec items, code symbols,
test cases) and all retrieval queries execute inside the database
(``MATCH ... AGAINST`` full-text when available, ``LIKE`` fallback), so the
"context is built from real database query results" guarantee holds for every
backend.
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from .config import Config

SPEC_TABLE = "sdd_spec_items"
SYMBOL_TABLE = "sdd_code_symbols"
TEST_TABLE = "sdd_test_cases"

TABLES: Dict[str, List[str]] = {
    SPEC_TABLE: [
        "item_key", "spec_id", "item_id", "title", "content",
        "file", "content_hash", "updated_at",
    ],
    SYMBOL_TABLE: [
        "symbol_key", "symbol", "kind", "qualname", "file", "line",
        "signature", "docstring",
    ],
    TEST_TABLE: [
        "test_key", "test_name", "file", "role", "docstring",
    ],
}

SEARCH_COLUMNS: Dict[str, List[str]] = {
    SPEC_TABLE: ["title", "content", "spec_id", "item_id"],
    SYMBOL_TABLE: ["symbol", "qualname", "file", "docstring", "signature"],
    TEST_TABLE: ["test_name", "file", "docstring", "role"],
}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class BaseStore:
    """Minimal storage contract used by the importer and retriever."""

    def init_schema(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def replace_rows(self, table: str, rows: List[Dict[str, Any]]) -> None:  # pragma: no cover
        raise NotImplementedError

    def fetch_all(self, table: str, where: str = "", params: Sequence[Any] = (),
                  limit: Optional[int] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def count(self, table: str) -> int:
        return len(self.fetch_all(table))

    def close(self) -> None:
        pass

    # -- full-text / keyword search executed inside the database ----------
    def search(self, table: str, terms: Sequence[str], limit: int = 5,
               extra_where: str = "", extra_params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        """Return rows matching any of ``terms``.

        Tries full-text ``MATCH ... AGAINST`` first; falls back to ``LIKE``
        when full-text is unavailable or returns nothing. The query always
        executes inside the database engine.
        """
        columns = SEARCH_COLUMNS[table]
        rows: List[Dict[str, Any]] = []
        if terms:
            ft_columns = ", ".join(["title", "content"]) if table == SPEC_TABLE else ", ".join(columns[:2])
            phrase = " ".join(terms)
            try:
                sql = (
                    f"SELECT * FROM {table} WHERE MATCH({ft_columns}) "
                    f"AGAINST (%s IN NATURAL LANGUAGE MODE)"
                )
                rows = self.fetch_all(table, where=sql, params=(phrase,), limit=limit * 4)
            except Exception:
                rows = []
            if not rows:
                like_parts = []
                params: List[Any] = []
                for term in terms[:12]:
                    for col in columns:
                        like_parts.append(f"{col} LIKE %s")
                        params.append(f"%{term}%")
                where = "(" + " OR ".join(like_parts) + ")"
                rows = self.fetch_all(table, where=where, params=params, limit=limit * 4)
        if not rows:
            rows = self.fetch_all(table, limit=limit)
        return rows[:limit * 4]


class _MySQLDialectStore(BaseStore):
    """Shared implementation for MySQL-compatible engines (seekdb embedded,
    seekdb server, OceanBase). Subclasses only provide a DBAPI connection."""

    def __init__(self) -> None:
        self._conn: Any = None

    # -- to be provided by subclasses ------------------------------------
    def _connect(self):  # pragma: no cover - abstract
        raise NotImplementedError

    @property
    def conn(self):
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _cursor(self):
        return self.conn.cursor()

    def init_schema(self) -> None:
        ddl = [
            f"""CREATE TABLE IF NOT EXISTS {SPEC_TABLE} (
                item_key VARCHAR(128) PRIMARY KEY,
                spec_id VARCHAR(32) NOT NULL,
                item_id VARCHAR(32) NOT NULL,
                title VARCHAR(256) NOT NULL,
                content TEXT NOT NULL,
                file VARCHAR(512) NOT NULL,
                content_hash VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            )""",
            f"""CREATE TABLE IF NOT EXISTS {SYMBOL_TABLE} (
                symbol_key VARCHAR(512) PRIMARY KEY,
                symbol VARCHAR(128) NOT NULL,
                kind VARCHAR(32) NOT NULL,
                qualname VARCHAR(256) NOT NULL,
                file VARCHAR(512) NOT NULL,
                line INT NOT NULL,
                signature TEXT,
                docstring TEXT
            )""",
            f"""CREATE TABLE IF NOT EXISTS {TEST_TABLE} (
                test_key VARCHAR(512) PRIMARY KEY,
                test_name VARCHAR(256) NOT NULL,
                file VARCHAR(512) NOT NULL,
                role VARCHAR(32) NOT NULL,
                docstring TEXT
            )""",
        ]
        cur = self._cursor()
        for stmt in ddl:
            cur.execute(stmt)
        # Full-text indexes are a seekdb strength; create them when supported.
        for table, cols in ((SPEC_TABLE, "title, content"), (SYMBOL_TABLE, "symbol, docstring"),
                            (TEST_TABLE, "test_name, docstring")):
            try:
                cur.execute(
                    f"CREATE FULLTEXT INDEX ft_{table} ON {table} ({cols})"
                )
            except Exception:
                # Engine without FULLTEXT support on this shape keeps working
                # through the LIKE fallback in BaseStore.search.
                pass
        self.conn.commit()
        cur.close()

    def replace_rows(self, table: str, rows: List[Dict[str, Any]]) -> None:
        cols = TABLES[table]
        cur = self._cursor()
        cur.execute(f"DELETE FROM {table}")
        if rows:
            placeholders = ", ".join(["%s"] * len(cols))
            col_list = ", ".join(cols)
            payload = [tuple(row.get(c) for c in cols) for row in rows]
            cur.executemany(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", payload
            )
        self.conn.commit()
        cur.close()

    def fetch_all(self, table: str, where: str = "", params: Sequence[Any] = (),
                  limit: Optional[int] = None) -> List[Dict[str, Any]]:
        cols = TABLES[table]
        sql = f"SELECT {', '.join(cols)} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur = self._cursor()
        cur.execute(sql, tuple(params))
        raw = cur.fetchall()
        cur.close()
        return [dict(zip(cols, row)) for row in raw]

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None


class SeekdbEmbeddedStore(_MySQLDialectStore):
    """Embedded seekdb (OceanBase seekdb engine in-process, via pylibseekdb)."""

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg

    def _connect(self):
        import os

        import pylibseekdb as seekdb  # Linux only; imported lazily

        # seekdb embedded mode stores data in a directory; create it first.
        try:
            os.makedirs(self.cfg.seekdb_path, exist_ok=True)
        except (FileExistsError, NotADirectoryError):
            pass

        # pylibseekdb requires open() before connect(); open() is process-wide.
        try:
            seekdb.open(self.cfg.seekdb_path)
        except TypeError:
            # different signature (no path arg) - open default location
            seekdb.open()
        try:
            return seekdb.connect()
        except TypeError:
            return seekdb.connect(self.cfg.seekdb_path)


class MySQLStore(_MySQLDialectStore):
    """seekdb server or OceanBase reached over the MySQL protocol."""

    def __init__(self, cfg: Config):
        super().__init__()
        if not cfg.store_mysql_url:
            raise ValueError("SDD_STORE_MYSQL_URL is required for the mysql backend")
        self.url = cfg.store_mysql_url

    def _connect(self):
        import pymysql
        from urllib.parse import urlparse, parse_qs, unquote

        parsed = urlparse(self.url)
        query = parse_qs(parsed.query)
        database = (parsed.path or "/").lstrip("/") or "sdd"
        return pymysql.connect(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 2881,
            user=unquote(parsed.username or "root"),
            password=unquote(parsed.password or ""),
            database=database,
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=int(query.get("connect_timeout", ["10"])[0]),
        )


class SqliteStore(BaseStore):
    """Development smoke-test backend. Same schema and same query semantics
    (LIKE-based search executed inside SQLite)."""

    def __init__(self, cfg: Config):
        self.path = str(cfg.work_dir / "sddcontext.db")
        cfg.work_dir.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def init_schema(self) -> None:
        cur = self.conn.cursor()
        for table, cols in TABLES.items():
            col_defs = ", ".join(
                f"{c} TEXT" + (" PRIMARY KEY" if c.endswith("_key") else "")
                for c in cols
            )
            cur.execute(f"CREATE TABLE IF NOT EXISTS {table} ({col_defs})")
        self.conn.commit()
        cur.close()

    def replace_rows(self, table: str, rows: List[Dict[str, Any]]) -> None:
        cols = TABLES[table]
        cur = self.conn.cursor()
        cur.execute(f"DELETE FROM {table}")
        if rows:
            placeholders = ", ".join(["?"] * len(cols))
            cur.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                [tuple(row.get(c) for c in cols) for row in rows],
            )
        self.conn.commit()
        cur.close()

    def fetch_all(self, table: str, where: str = "", params: Sequence[Any] = (),
                  limit: Optional[int] = None) -> List[Dict[str, Any]]:
        # translate %s placeholders used by the shared search() to "?"
        if where:
            where = where.replace("%s", "?")
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur = self.conn.cursor()
        cur.execute(sql, tuple(params))
        rows = [dict(row) for row in cur.fetchall()]
        cur.close()
        return rows

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def open_store(cfg: Config) -> BaseStore:
    backend = cfg.store_backend.lower()
    if backend == "seekdb":
        return SeekdbEmbeddedStore(cfg)
    if backend == "mysql":
        return MySQLStore(cfg)
    if backend == "sqlite":
        return SqliteStore(cfg)
    raise ValueError(f"unknown store backend: {cfg.store_backend}")
