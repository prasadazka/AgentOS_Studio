"""
Episodic memory for tool execution history.
SQLite-backed storage for tracking agent actions and outcomes.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import EpisodicMemoryBase, ActionRecord, MemoryItem


class EpisodicMemory(EpisodicMemoryBase):
    """SQLite-backed episodic memory for action history."""

    def __init__(
        self,
        db_path: str = "~/.agent_os/memory/episodic.db",
        retention_days: int = 90
    ):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._init_db()
        if retention_days > 0:
            self._cleanup_old_records()

    @contextmanager
    def _connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    params TEXT,
                    result TEXT,
                    success INTEGER NOT NULL DEFAULT 1,
                    error TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    workflow_id TEXT,
                    timestamp TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_agent ON actions(agent)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_tool ON actions(tool)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_timestamp ON actions(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_workflow ON actions(workflow_id)")
            conn.commit()

    def _cleanup_old_records(self) -> None:
        if self.retention_days <= 0:
            return
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM actions WHERE timestamp < ?", (cutoff.isoformat(),))
            conn.commit()

    def _get_stats(self, field: str, value: str, is_agent: bool = False) -> Dict[str, Any]:
        """Shared stats query for both tool and agent."""
        with self._lock, self._connection() as conn:
            if is_agent:
                cursor = conn.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
                           COUNT(DISTINCT tool) as unique_tools,
                           AVG(duration_ms) as avg_duration
                    FROM actions WHERE agent = ?
                """, (value,))
            else:
                cursor = conn.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
                           SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failure_count,
                           AVG(duration_ms) as avg_duration,
                           MIN(duration_ms) as min_duration,
                           MAX(duration_ms) as max_duration
                    FROM actions WHERE tool = ?
                """, (value,))

            row = cursor.fetchone()
            if not row or row['total'] == 0:
                return {field: value, "total_calls" if not is_agent else "total_actions": 0, "success_rate": 0.0}

            result = {
                field: value,
                "total_calls" if not is_agent else "total_actions": row['total'],
                "success_count": row['success_count'],
                "success_rate": row['success_count'] / row['total'] if row['total'] else 0.0,
                "avg_duration_ms": row['avg_duration']
            }
            if is_agent:
                result["unique_tools"] = row['unique_tools']
            else:
                result["failure_count"] = row['failure_count']
                result["min_duration_ms"] = row['min_duration']
                result["max_duration_ms"] = row['max_duration']
            return result

    def _row_to_action(self, row: sqlite3.Row) -> ActionRecord:
        return ActionRecord(
            id=row['id'],
            agent=row['agent'],
            tool=row['tool'],
            params=json.loads(row['params']) if row['params'] else {},
            result=json.loads(row['result']) if row['result'] else None,
            success=bool(row['success']),
            error=row['error'],
            duration_ms=row['duration_ms'] or 0,
            workflow_id=row['workflow_id'],
            timestamp=datetime.fromisoformat(row['timestamp'])
        )

    def log_action(self, action: ActionRecord) -> str:
        with self._lock, self._connection() as conn:
            conn.execute("""
                INSERT INTO actions (id, agent, tool, params, result, success,
                                    error, duration_ms, workflow_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                action.id, action.agent, action.tool,
                json.dumps(action.params),
                json.dumps(action.result) if action.result else None,
                1 if action.success else 0,
                action.error, action.duration_ms, action.workflow_id,
                action.timestamp.isoformat()
            ))
            conn.commit()
            return action.id

    def get_actions(
        self,
        agent: Optional[str] = None,
        tool: Optional[str] = None,
        limit: int = 20
    ) -> List[ActionRecord]:
        query = "SELECT * FROM actions WHERE 1=1"
        params = []
        if agent:
            query += " AND agent = ?"
            params.append(agent)
        if tool:
            query += " AND tool = ?"
            params.append(tool)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._connection() as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_action(row) for row in cursor.fetchall()]

    def get_tool_stats(self, tool: str) -> Dict[str, Any]:
        return self._get_stats("tool", tool, is_agent=False)

    def get_agent_stats(self, agent: str) -> Dict[str, Any]:
        return self._get_stats("agent", agent, is_agent=True)

    def store(self, key: str, value: Any, metadata: Optional[Dict] = None) -> str:
        metadata = metadata or {}
        action = ActionRecord(
            id=key,
            agent=metadata.get("agent", "unknown"),
            tool=metadata.get("tool", "unknown"),
            params=metadata.get("params", {}),
            result=value,
            success=metadata.get("success", True),
            duration_ms=metadata.get("duration_ms", 0)
        )
        return self.log_action(action)

    def retrieve(self, key: str) -> Optional[ActionRecord]:
        with self._lock, self._connection() as conn:
            cursor = conn.execute("SELECT * FROM actions WHERE id = ?", (key,))
            row = cursor.fetchone()
            return self._row_to_action(row) if row else None

    def search(self, query: str, limit: int = 10) -> List[MemoryItem]:
        pattern = f"%{query}%"
        with self._lock, self._connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM actions
                WHERE tool LIKE ? OR error LIKE ? OR agent LIKE ?
                ORDER BY timestamp DESC LIMIT ?
            """, (pattern, pattern, pattern, limit))

            return [
                MemoryItem(
                    id=row['id'],
                    content={"agent": row['agent'], "tool": row['tool'],
                             "success": bool(row['success']), "error": row['error']},
                    content_type="action",
                    metadata={"params": json.loads(row['params']) if row['params'] else {},
                              "result": json.loads(row['result']) if row['result'] else None},
                    timestamp=datetime.fromisoformat(row['timestamp'])
                )
                for row in cursor.fetchall()
            ]

    def delete(self, key: str) -> bool:
        with self._lock, self._connection() as conn:
            cursor = conn.execute("DELETE FROM actions WHERE id = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0

    def clear(self, older_than: Optional[datetime] = None) -> int:
        with self._lock, self._connection() as conn:
            if older_than is None:
                cursor = conn.execute("DELETE FROM actions")
            else:
                cursor = conn.execute("DELETE FROM actions WHERE timestamp < ?", (older_than.isoformat(),))
            conn.commit()
            return cursor.rowcount

    def count(self) -> int:
        with self._lock, self._connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]

    def get_failed_actions(self, limit: int = 20) -> List[ActionRecord]:
        return self.get_actions_by_success(success=False, limit=limit)

    def get_actions_by_success(self, success: bool, limit: int = 20) -> List[ActionRecord]:
        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM actions WHERE success = ? ORDER BY timestamp DESC LIMIT ?",
                (1 if success else 0, limit)
            )
            return [self._row_to_action(row) for row in cursor.fetchall()]

    def get_actions_for_workflow(self, workflow_id: str, limit: int = 100) -> List[ActionRecord]:
        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM actions WHERE workflow_id = ? ORDER BY timestamp ASC LIMIT ?",
                (workflow_id, limit)
            )
            return [self._row_to_action(row) for row in cursor.fetchall()]

    def close(self) -> None:
        pass
