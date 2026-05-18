"""Database for AgentOS Studio.

Two backends:
- Postgres (production): if DATABASE_URL is set, use psycopg with a thin wrapper
  that mimics the sqlite3.Connection / sqlite3.Row interface so the manager
  modules keep working unchanged.
- SQLite (local dev): default fallback when DATABASE_URL is unset.

Schema is identical (TEXT/INTEGER, ON DELETE CASCADE, CREATE INDEX IF NOT EXISTS)
and supported by both engines.
"""

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_USE_POSTGRES = _DATABASE_URL.startswith(("postgres://", "postgresql://"))

_DB_PATH = Path(os.path.expanduser("~/.agent_os/studio.db"))
_local = threading.local()
_init_done = False
_init_lock = threading.Lock()


def generate_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Postgres compatibility shim — exposes the sqlite3 API the managers expect
# ---------------------------------------------------------------------------

class _PgCursor:
    """Cursor wrapper: returns dict-like rows so row['name'] works."""

    def __init__(self, real_cur):
        self._cur = real_cur

    def _row_to_dict(self, row):
        if row is None:
            return None
        cols = [d[0] for d in self._cur.description]
        return dict(zip(cols, row))

    def fetchone(self):
        return self._row_to_dict(self._cur.fetchone())

    def fetchall(self):
        cols = [d[0] for d in self._cur.description] if self._cur.description else []
        return [dict(zip(cols, r)) for r in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return None  # unused — this codebase generates UUIDs manually

    def close(self):
        self._cur.close()


class _PgConnection:
    """sqlite3.Connection-compatible wrapper around psycopg.

    Translates `?` placeholders to `%s` so existing SQL works as-is.
    The codebase contains no `?` characters inside string literals, so the
    naive replace is safe (verified by audit).
    """

    def __init__(self, real_conn):
        self._conn = real_conn

    @staticmethod
    def _adapt(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: Sequence[Any] = ()):
        cur = self._conn.cursor()
        cur.execute(self._adapt(sql), params)
        return _PgCursor(cur)

    def executescript(self, script: str):
        # psycopg can execute multi-statement strings directly
        with self._conn.cursor() as cur:
            cur.execute(self._adapt(script))

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def _connect_postgres():
    """Open a psycopg connection. Uses DATABASE_URL.

    For Cloud Run + Cloud SQL via Unix socket, the URL looks like:
      postgresql://USER:PASS@/DBNAME?host=/cloudsql/PROJECT:REGION:INSTANCE
    """
    import psycopg  # imported lazily so SQLite-only local dev doesn't need it

    conn = psycopg.connect(_DATABASE_URL, autocommit=False)
    return _PgConnection(conn)


def _connect_sqlite():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_db():
    """Get a per-thread database connection.

    Manager modules use the returned object as if it were a sqlite3.Connection.
    With Postgres, the _PgConnection wrapper provides the same interface.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn

    conn = _connect_postgres() if _USE_POSTGRES else _connect_sqlite()
    _local.conn = conn

    global _init_done
    if not _init_done:
        with _init_lock:
            if not _init_done:
                _init_tables(conn)
                _init_done = True

    return conn


def _init_tables(conn):
    """Schema works on both SQLite and Postgres."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            agent_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS project_files (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            file_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            status TEXT DEFAULT 'processing',
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT DEFAULT 'New Chat',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT DEFAULT '',
            tool_calls_json TEXT DEFAULT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            graph_json TEXT NOT NULL DEFAULT '{"nodes":[],"edges":[]}',
            status TEXT DEFAULT 'draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            input_text TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            node_states_json TEXT DEFAULT '{}',
            hitl_node_id TEXT DEFAULT NULL,
            hitl_request_json TEXT DEFAULT NULL,
            hitl_response_json TEXT DEFAULT NULL,
            output TEXT DEFAULT '',
            error TEXT DEFAULT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT DEFAULT NULL,
            FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_files_project ON project_files(project_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_project ON chat_sessions(project_id);
        CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_runs_workflow ON workflow_runs(workflow_id);
    """)
    conn.commit()
