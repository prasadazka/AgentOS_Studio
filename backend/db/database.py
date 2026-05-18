"""SQLite database for AgentOS Studio - projects, files, sessions, messages."""

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_DB_PATH = Path(os.path.expanduser("~/.agent_os/studio.db"))
_local = threading.local()  # thread-local storage
_init_done = False
_init_lock = threading.Lock()


def generate_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db() -> sqlite3.Connection:
    """Get a per-thread database connection. Each thread gets its own connection.

    SQLite connections are NOT safe for concurrent use from multiple threads.
    Using thread-local storage ensures each thread (main, workflow background,
    HITL polling) gets its own connection — preventing SQLITE_MISUSE errors.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")  # wait up to 5s if DB is locked
    _local.conn = conn

    # Init tables once (first thread to arrive)
    global _init_done
    if not _init_done:
        with _init_lock:
            if not _init_done:
                _init_tables(conn)
                _init_done = True

    return conn


def _init_tables(conn: sqlite3.Connection):
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
