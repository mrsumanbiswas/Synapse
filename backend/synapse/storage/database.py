"""Thin sqlite3 helper: one connection per thread, WAL journaling, explicit transactions."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path: Path, schema: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._connections: list[sqlite3.Connection] = []
        self._registry_lock = threading.Lock()
        self.connection().executescript(schema)

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
            with self._registry_lock:
                self._connections.append(conn)
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialise writers inside the process and wrap the block in BEGIN/COMMIT."""
        conn = self.connection()
        with self._write_lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def execute(self, sql: str, params: Sequence | dict = ()) -> sqlite3.Cursor:
        with self._write_lock:
            return self.connection().execute(sql, params)

    def executemany(self, sql: str, rows: Iterable[Sequence]) -> None:
        with self.transaction() as conn:
            conn.executemany(sql, rows)

    def query(self, sql: str, params: Sequence | dict = ()) -> list[sqlite3.Row]:
        return self.connection().execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence | dict = ()) -> sqlite3.Row | None:
        return self.connection().execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence | dict = ()):
        row = self.query_one(sql, params)
        return row[0] if row else None

    def close(self) -> None:
        with self._registry_lock:
            for conn in self._connections:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            self._connections.clear()
        self._local = threading.local()


def placeholders(n: int) -> str:
    return ",".join("?" * n)


def chunked(items: Sequence, size: int = 500) -> Iterator[Sequence]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
