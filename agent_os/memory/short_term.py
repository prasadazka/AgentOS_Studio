"""
Short-term memory for conversation context.

Provides in-memory conversation buffer with optional disk persistence.
Supports context window management and prompt formatting.
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import ConversationMemory, Message, MemoryItem


class ShortTermMemory(ConversationMemory):
    """
    In-memory conversation buffer with overflow management.

    Features:
    - Thread-safe message storage
    - Configurable max messages
    - Auto-persist to disk (optional)
    - Context window formatting for prompts
    - Message summarization for overflow

    Example:
        memory = ShortTermMemory(max_messages=50, persist_path="~/.agent_os/memory/")
        memory.add_message(Message(role="user", content="Hello"))
        context = memory.get_context_string(limit=10)
    """

    def __init__(
        self,
        max_messages: int = 50,
        persist_path: Optional[str] = None,
        namespace: str = "default",
        auto_save: bool = True
    ):
        """
        Initialize short-term memory.

        Args:
            max_messages: Maximum messages to keep in memory
            persist_path: Path for disk persistence (None = memory only)
            namespace: Memory namespace for isolation
            auto_save: Auto-save after each message
        """
        self.max_messages = max_messages
        self.namespace = namespace
        self.auto_save = auto_save
        self._messages: List[Message] = []
        self._lock = threading.Lock()
        self._overflow_summary: Optional[str] = None

        # Setup persistence
        self._persist_path: Optional[Path] = None
        if persist_path:
            self._persist_path = Path(persist_path).expanduser() / f"{namespace}_short_term.json"
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load messages from disk if file exists"""
        if self._persist_path and self._persist_path.exists():
            try:
                with open(self._persist_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._messages = [Message(**m) for m in data.get("messages", [])]
                    self._overflow_summary = data.get("overflow_summary")
            except (json.JSONDecodeError, IOError):
                self._messages = []

    def _save_to_disk(self) -> None:
        """Save messages to disk"""
        if not self._persist_path:
            return

        try:
            data = {
                "messages": [m.model_dump(mode='json') for m in self._messages],
                "overflow_summary": self._overflow_summary,
                "updated_at": datetime.now().isoformat()
            }
            # Atomic write
            temp_path = self._persist_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            temp_path.replace(self._persist_path)
        except IOError:
            pass

    def add_message(self, message: Message) -> str:
        """
        Add a message to conversation history.

        Args:
            message: Message to add

        Returns:
            Message ID
        """
        with self._lock:
            self._messages.append(message)

            # Handle overflow
            if len(self._messages) > self.max_messages:
                self._handle_overflow()

            if self.auto_save:
                self._save_to_disk()

            return message.id

    def get_messages(self, limit: Optional[int] = None) -> List[Message]:
        """
        Get conversation messages.

        Args:
            limit: Max messages to return (None = all)

        Returns:
            List of messages (most recent last)
        """
        with self._lock:
            if limit is None:
                return list(self._messages)
            return list(self._messages[-limit:])

    def get_context_string(self, limit: int = 10) -> str:
        """
        Format conversation for prompt injection.

        Args:
            limit: Max messages to include

        Returns:
            Formatted conversation string
        """
        with self._lock:
            lines = []

            # Include overflow summary if exists
            if self._overflow_summary:
                lines.append(f"[Previous conversation summary: {self._overflow_summary}]")
                lines.append("")

            # Format recent messages
            messages = self._messages[-limit:] if limit else self._messages
            for msg in messages:
                role_prefix = "User" if msg.role == "user" else "Assistant"
                if msg.role == "system":
                    role_prefix = "System"
                lines.append(f"{role_prefix}: {msg.content}")

            return "\n".join(lines)

    def store(self, key: str, value: Any, metadata: Optional[Dict] = None) -> str:
        """Store a value (creates a message)"""
        msg = Message(
            id=key,
            role="assistant",
            content=str(value),
            metadata=metadata or {}
        )
        return self.add_message(msg)

    def retrieve(self, key: str) -> Optional[Any]:
        """Retrieve a message by ID"""
        with self._lock:
            for msg in self._messages:
                if msg.id == key:
                    return msg
            return None

    def search(self, query: str, limit: int = 10) -> List[MemoryItem]:
        """
        Simple keyword search over messages.

        Args:
            query: Search term
            limit: Max results

        Returns:
            Matching messages as MemoryItems
        """
        query_lower = query.lower()
        results = []

        with self._lock:
            for msg in reversed(self._messages):
                if query_lower in msg.content.lower():
                    results.append(MemoryItem(
                        id=msg.id,
                        content=msg.content,
                        content_type="message",
                        metadata={"role": msg.role, "agent": msg.agent},
                        timestamp=msg.timestamp
                    ))
                    if len(results) >= limit:
                        break

        return results

    def delete(self, key: str) -> bool:
        """Delete a message by ID"""
        with self._lock:
            for i, msg in enumerate(self._messages):
                if msg.id == key:
                    del self._messages[i]
                    if self.auto_save:
                        self._save_to_disk()
                    return True
            return False

    def clear(self, older_than: Optional[datetime] = None) -> int:
        """
        Clear messages.

        Args:
            older_than: If provided, only clear messages before this time

        Returns:
            Number of messages cleared
        """
        with self._lock:
            if older_than is None:
                count = len(self._messages)
                self._messages.clear()
                self._overflow_summary = None
            else:
                original_count = len(self._messages)
                self._messages = [m for m in self._messages if m.timestamp >= older_than]
                count = original_count - len(self._messages)

            if self.auto_save:
                self._save_to_disk()

            return count

    def count(self) -> int:
        """Get number of messages"""
        with self._lock:
            return len(self._messages)

    def _handle_overflow(self) -> None:
        """Handle message overflow by summarizing old messages"""
        # Keep the most recent messages
        overflow_count = len(self._messages) - self.max_messages
        if overflow_count <= 0:
            return

        # Extract messages to summarize
        overflow_messages = self._messages[:overflow_count]

        # Create simple summary (could be LLM-powered in future)
        summary_parts = []
        for msg in overflow_messages:
            if msg.role == "user":
                summary_parts.append(f"User asked about: {msg.content[:100]}...")
            elif msg.role == "assistant":
                summary_parts.append(f"Assistant discussed: {msg.content[:100]}...")

        if summary_parts:
            new_summary = "; ".join(summary_parts[:5])  # Keep last 5 topics
            if self._overflow_summary:
                self._overflow_summary = f"{self._overflow_summary}; {new_summary}"
            else:
                self._overflow_summary = new_summary

            # Trim overflow summary if too long
            if len(self._overflow_summary) > 500:
                self._overflow_summary = self._overflow_summary[-500:]

        # Remove overflow messages
        self._messages = self._messages[overflow_count:]

    def get_overflow_summary(self) -> Optional[str]:
        """Get summary of overflowed messages"""
        return self._overflow_summary

    def close(self) -> None:
        """Save and cleanup"""
        if self._persist_path:
            self._save_to_disk()
