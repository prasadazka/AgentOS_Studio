"""
Unified memory manager for AgentOS.
Coordinates short-term, long-term, and episodic memory systems.
"""

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import Message, MemoryItem, ActionRecord
from .short_term import ShortTermMemory
from .episodic import EpisodicMemory

try:
    from .long_term import LongTermMemory, is_chromadb_available
    LONGTERM_AVAILABLE = is_chromadb_available()
except ImportError:
    LONGTERM_AVAILABLE = False
    LongTermMemory = None


class MemoryManager:
    """Unified memory interface coordinating short-term, long-term, and episodic memory."""

    def __init__(
        self,
        namespace: str = "default",
        persist_path: Optional[str] = None,
        short_term_max_messages: int = 50,
        enable_long_term: bool = True,
        enable_episodic: bool = True,
        episodic_retention_days: int = 90,
        embedding_function: Optional[Any] = None
    ):
        self.namespace = namespace
        self._lock = threading.Lock()

        base_path = Path(persist_path).expanduser() if persist_path else Path.home() / ".agent_os" / "memory"
        base_path.mkdir(parents=True, exist_ok=True)

        self.short_term = ShortTermMemory(
            max_messages=short_term_max_messages,
            persist_path=str(base_path),
            namespace=namespace,
            auto_save=True
        )

        self.long_term: Optional[LongTermMemory] = None
        if enable_long_term and LONGTERM_AVAILABLE:
            try:
                self.long_term = LongTermMemory(
                    collection_name=f"{namespace}_semantic",
                    persist_directory=str(base_path / "chroma"),
                    embedding_function=embedding_function
                )
            except Exception:
                self.long_term = None

        self.episodic: Optional[EpisodicMemory] = None
        if enable_episodic:
            self.episodic = EpisodicMemory(
                db_path=str(base_path / f"{namespace}_episodic.db"),
                retention_days=episodic_retention_days
            )

    def add_message(
        self,
        role: str,
        content: str,
        agent: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        message = Message(
            role=role,
            content=content,
            agent=agent or self.namespace,
            metadata=metadata or {}
        )
        msg_id = self.short_term.add_message(message)

        if self.long_term and content.strip():
            try:
                self.long_term.store_with_embedding(
                    content=content,
                    metadata={
                        "role": role,
                        "agent": agent or self.namespace,
                        "message_id": msg_id,
                        "namespace": self.namespace,
                        **(metadata or {})
                    }
                )
            except Exception:
                pass
        return msg_id

    def get_messages(self, limit: Optional[int] = None) -> List[Message]:
        return self.short_term.get_messages(limit)

    def get_context(self, limit: int = 10) -> List[Message]:
        return self.get_messages(limit)

    def get_context_string(self, limit: int = 10) -> str:
        return self.short_term.get_context_string(limit)

    def search_semantic(self, query: str, limit: int = 5, threshold: float = 0.0) -> List[MemoryItem]:
        if not self.long_term:
            return []
        return self.long_term.search_similar(query=query, limit=limit, threshold=threshold)

    def store_knowledge(self, content: str, metadata: Optional[Dict] = None) -> Optional[str]:
        if not self.long_term:
            return None
        return self.long_term.store_with_embedding(
            content=content,
            metadata={"namespace": self.namespace, "type": "knowledge", **(metadata or {})}
        )

    def log_action(
        self,
        agent: str,
        tool: str,
        params: Dict[str, Any],
        result: Any,
        success: bool = True,
        error: Optional[str] = None,
        duration_ms: int = 0,
        workflow_id: Optional[str] = None
    ) -> Optional[str]:
        if not self.episodic:
            return None
        action = ActionRecord(
            agent=agent, tool=tool, params=params, result=result,
            success=success, error=error, duration_ms=duration_ms, workflow_id=workflow_id
        )
        return self.episodic.log_action(action)

    def get_action_history(
        self,
        agent: Optional[str] = None,
        tool: Optional[str] = None,
        limit: int = 20
    ) -> List[ActionRecord]:
        if not self.episodic:
            return []
        return self.episodic.get_actions(agent=agent, tool=tool, limit=limit)

    def get_failed_actions(self, limit: int = 20) -> List[ActionRecord]:
        return self.episodic.get_failed_actions(limit) if self.episodic else []

    def get_tool_stats(self, tool: str) -> Dict[str, Any]:
        return self.episodic.get_tool_stats(tool) if self.episodic else {"tool": tool, "total_calls": 0}

    def get_agent_stats(self, agent: str) -> Dict[str, Any]:
        return self.episodic.get_agent_stats(agent) if self.episodic else {"agent": agent, "total_actions": 0}

    def clear_conversation(self) -> int:
        return self.short_term.clear()

    def clear_all(self, older_than: Optional[datetime] = None) -> Dict[str, int]:
        result = {"short_term": self.short_term.clear(older_than), "long_term": 0, "episodic": 0}
        if self.long_term:
            result["long_term"] = self.long_term.clear(older_than)
        if self.episodic:
            result["episodic"] = self.episodic.clear(older_than)
        return result

    def get_stats(self) -> Dict[str, Any]:
        return {
            "namespace": self.namespace,
            "short_term": {
                "message_count": self.short_term.count(),
                "has_overflow": self.short_term.get_overflow_summary() is not None
            },
            "long_term": {
                "enabled": self.long_term is not None,
                "document_count": self.long_term.count() if self.long_term else 0
            },
            "episodic": {
                "enabled": self.episodic is not None,
                "action_count": self.episodic.count() if self.episodic else 0
            }
        }

    def close(self) -> None:
        errors = []
        try:
            self.short_term.close()
        except Exception as e:
            errors.append(f"short_term: {e}")
        if self.long_term:
            try:
                self.long_term.close()
            except Exception as e:
                errors.append(f"long_term: {e}")
        if self.episodic:
            try:
                self.episodic.close()
            except Exception as e:
                errors.append(f"episodic: {e}")
        if errors:
            raise RuntimeError(f"Memory cleanup errors: {', '.join(errors)}")


def create_memory_manager(namespace: str = "default", config: Optional[Dict[str, Any]] = None) -> MemoryManager:
    config = config or {}
    return MemoryManager(
        namespace=namespace,
        persist_path=config.get("persist_path"),
        short_term_max_messages=config.get("short_term_max_messages", 50),
        enable_long_term=config.get("enable_long_term", True),
        enable_episodic=config.get("enable_episodic", True),
        episodic_retention_days=config.get("episodic_retention_days", 90)
    )


def create_lightweight_memory(namespace: str = "default") -> MemoryManager:
    return MemoryManager(namespace=namespace, enable_long_term=False, enable_episodic=False)
