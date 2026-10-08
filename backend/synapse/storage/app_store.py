"""Node-local application data: users, subscriptions, alerts, history, bookmarks, jobs."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .database import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'viewer',
    created_at    REAL NOT NULL,
    last_login    REAL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id               INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query            TEXT NOT NULL,
    mode             TEXT NOT NULL DEFAULT 'hybrid',
    min_score        REAL NOT NULL DEFAULT 0.35,
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       REAL NOT NULL,
    last_notified_at REAL,
    matches          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE SET NULL,
    query           TEXT,
    documents       TEXT NOT NULL,
    status          TEXT NOT NULL,
    error           TEXT,
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS search_history (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    query   TEXT NOT NULL,
    mode    TEXT NOT NULL,
    results INTEGER NOT NULL,
    took_ms REAL NOT NULL,
    ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_ts ON search_history(ts);
CREATE INDEX IF NOT EXISTS idx_history_user ON search_history(user_id, ts);

CREATE TABLE IF NOT EXISTS bookmarks (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    doc_id     TEXT NOT NULL,
    title      TEXT NOT NULL,
    note       TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (user_id, doc_id)
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind        TEXT NOT NULL,
    label       TEXT NOT NULL,
    status      TEXT NOT NULL,
    data        TEXT NOT NULL,
    created_at  REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON ingest_jobs(created_at);
"""

USER_COLUMNS = "id, email, name, role, created_at, last_login"


class AppStore:
    def __init__(self, path: Path):
        self.db = Database(path, SCHEMA)

    # ------------------------------------------------------------------ users

    def create_user(self, email: str, name: str, password_hash: str, role: str) -> dict:
        cursor = self.db.execute(
            "INSERT INTO users (email, name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (email.strip().lower(), name.strip(), password_hash, role, time.time()))
        return self.user(cursor.lastrowid)

    def user(self, user_id: int) -> dict | None:
        row = self.db.query_one(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (user_id,))
        return dict(row) if row else None

    def user_with_secret(self, email: str) -> dict | None:
        row = self.db.query_one(f"SELECT {USER_COLUMNS}, password_hash FROM users WHERE email = ?", (email.strip(),))
        return dict(row) if row else None

    def users(self) -> list[dict]:
        return [dict(r) for r in self.db.query(f"SELECT {USER_COLUMNS} FROM users ORDER BY created_at")]

    def user_count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM users") or 0)

    def admin_exists(self) -> bool:
        return bool(self.db.scalar("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"))

    def set_role(self, user_id: int, role: str) -> dict | None:
        self.db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        return self.user(user_id)

    def set_password(self, user_id: int, password_hash: str) -> None:
        self.db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))

    def update_profile(self, user_id: int, name: str) -> dict | None:
        self.db.execute("UPDATE users SET name = ? WHERE id = ?", (name.strip(), user_id))
        return self.user(user_id)

    def touch_login(self, user_id: int) -> None:
        self.db.execute("UPDATE users SET last_login = ? WHERE id = ?", (time.time(), user_id))

    def delete_user(self, user_id: int) -> None:
        self.db.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # ------------------------------------------------------------------ subscriptions

    def add_subscription(self, user_id: int, query: str, mode: str, min_score: float) -> dict:
        cursor = self.db.execute(
            "INSERT INTO subscriptions (user_id, query, mode, min_score, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, query.strip(), mode, min_score, time.time()))
        return dict(self.db.query_one("SELECT * FROM subscriptions WHERE id = ?", (cursor.lastrowid,)))

    def subscriptions(self, user_id: int | None = None, active_only: bool = False) -> list[dict]:
        sql = "SELECT s.*, u.email, u.name AS user_name FROM subscriptions s JOIN users u ON u.id = s.user_id WHERE 1=1"
        params: list = []
        if user_id is not None:
            sql += " AND s.user_id = ?"
            params.append(user_id)
        if active_only:
            sql += " AND s.active = 1"
        return [dict(r) for r in self.db.query(sql + " ORDER BY s.created_at DESC", params)]

    def update_subscription(self, user_id: int, sub_id: int, active: bool | None = None,
                            min_score: float | None = None) -> dict | None:
        if active is not None:
            self.db.execute("UPDATE subscriptions SET active = ? WHERE id = ? AND user_id = ?", (int(active), sub_id, user_id))
        if min_score is not None:
            self.db.execute("UPDATE subscriptions SET min_score = ? WHERE id = ? AND user_id = ?", (min_score, sub_id, user_id))
        row = self.db.query_one("SELECT * FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, user_id))
        return dict(row) if row else None

    def delete_subscription(self, user_id: int, sub_id: int) -> bool:
        return self.db.execute("DELETE FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, user_id)).rowcount > 0

    def record_notification(self, user_id: int, subscription_id: int | None, query: str | None,
                            documents: list[dict], status: str, error: str | None = None) -> None:
        now = time.time()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO notifications (user_id, subscription_id, query, documents, status, error, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, subscription_id, query, json.dumps(documents), status, error, now))
            if subscription_id is not None and status == "sent":
                conn.execute("UPDATE subscriptions SET last_notified_at = ?, matches = matches + ? WHERE id = ?",
                             (now, len(documents), subscription_id))

    def notifications(self, user_id: int, limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                             (user_id, limit))
        return [{**dict(r), "documents": json.loads(r["documents"])} for r in rows]

    # ------------------------------------------------------------------ history

    def log_search(self, user_id: int | None, query: str, mode: str, results: int, took_ms: float) -> None:
        self.db.execute("INSERT INTO search_history (user_id, query, mode, results, took_ms, ts) VALUES (?, ?, ?, ?, ?, ?)",
                        (user_id, query.strip(), mode, results, took_ms, time.time()))

    def history(self, user_id: int, limit: int = 50) -> list[dict]:
        rows = self.db.query("SELECT query, mode, results, took_ms, ts FROM search_history WHERE user_id = ?"
                             " ORDER BY ts DESC LIMIT ?", (user_id, limit))
        return [dict(r) for r in rows]

    def clear_history(self, user_id: int) -> None:
        self.db.execute("DELETE FROM search_history WHERE user_id = ?", (user_id,))

    def popular_queries(self, limit: int = 10, since: float | None = None) -> list[dict]:
        rows = self.db.query(
            "SELECT lower(query) AS query, COUNT(*) AS count, MAX(ts) AS last FROM search_history"
            " WHERE results > 0 AND ts >= ? GROUP BY lower(query) ORDER BY count DESC, last DESC LIMIT ?",
            (since or 0, limit))
        return [dict(r) for r in rows]

    def recent_queries(self, limit: int = 10) -> list[dict]:
        rows = self.db.query(
            "SELECT query, mode, MAX(ts) AS ts FROM search_history WHERE results > 0"
            " GROUP BY lower(query) ORDER BY ts DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def search_stats(self) -> dict:
        row = self.db.query_one("SELECT COUNT(*) AS searches, AVG(took_ms) AS avg_ms FROM search_history")
        return {"searches": row["searches"], "avg_ms": round(row["avg_ms"] or 0.0, 1)}

    # ------------------------------------------------------------------ bookmarks

    def add_bookmark(self, user_id: int, doc_id: str, title: str, note: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO bookmarks VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, doc_id) DO UPDATE SET note = excluded.note",
            (user_id, doc_id, title, note, time.time()))

    def remove_bookmark(self, user_id: int, doc_id: str) -> None:
        self.db.execute("DELETE FROM bookmarks WHERE user_id = ? AND doc_id = ?", (user_id, doc_id))

    def bookmarks(self, user_id: int) -> list[dict]:
        rows = self.db.query("SELECT doc_id, title, note, created_at FROM bookmarks WHERE user_id = ?"
                             " ORDER BY created_at DESC", (user_id,))
        return [dict(r) for r in rows]

    def bookmarked_ids(self, user_id: int) -> set[str]:
        return {r[0] for r in self.db.query("SELECT doc_id FROM bookmarks WHERE user_id = ?", (user_id,))}

    # ------------------------------------------------------------------ ingest jobs

    def save_job(self, job: dict) -> None:
        self.db.execute(
            "INSERT INTO ingest_jobs (id, user_id, kind, label, status, data, created_at, finished_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET status = excluded.status,"
            " data = excluded.data, finished_at = excluded.finished_at",
            (job["id"], job.get("user_id"), job["kind"], job["label"], job["status"], json.dumps(job),
             job["created_at"], job.get("finished_at")))

    def jobs(self, limit: int = 100) -> list[dict]:
        rows = self.db.query("SELECT data FROM ingest_jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [json.loads(r[0]) for r in rows]

    def job(self, job_id: str) -> dict | None:
        value = self.db.scalar("SELECT data FROM ingest_jobs WHERE id = ?", (job_id,))
        return json.loads(value) if value else None

    def mark_interrupted_jobs(self) -> None:
        for job in self.jobs(500):
            if job["status"] in ("queued", "running"):
                job["status"] = "failed"
                job["error"] = "Interrupted by a node restart"
                job["finished_at"] = time.time()
                self.save_job(job)
