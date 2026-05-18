"""
Base memory interfaces for AgentOS

Provides abstract base classes for memory implementations:
- BaseMemory: Core interface all memory backends must implement
- MemoryItem: Standard memory storage unit
- Message: Conversation message model
- ActionRecord: Tool execution history model
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict
import uuid


class Message(BaseModel):
    """A single conversation message."""
    model_config = ConfigDict(frozen=False)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant", "system"] = "user"
    content: str
    agent: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryItem(BaseModel):
    """Generic memory storage item with metadata."""
    model_config = ConfigDict(frozen=False)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: Any
    content_type: str = "text"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)
    relevance_score: Optional[float] = None
    source: Optional[str] = None


class ActionRecord(BaseModel):
    """Record of a tool execution."""
    model_config = ConfigDict(frozen=False)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent: str
    tool: str
    params: Dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    success: bool = True
    error: Optional[str] = None
    duration_ms: int = 0
    timestamp: datetime = Field(default_factory=datetime.now)
    workflow_id: Optional[str] = None


class BaseMemory(ABC):
    """
    Abstract base class for all memory backends.

    All memory implementations (short-term, long-term, episodic)
    must implement this interface.
    """

    @abstractmethod
    def store(self, key: str, value: Any, metadata: Optional[Dict] = None) -> str:
        """
        Store a value with optional metadata.

        Args:
            key: Unique identifier for the item
            value: Data to store
            metadata: Optional metadata dict

        Returns:
            The key/id of stored item
        """
        pass

    @abstractmethod
    def retrieve(self, key: str) -> Optional[Any]:
        """
        Retrieve a value by key.

        Args:
            key: Item identifier

        Returns:
            Stored value or None if not found
        """
        pass

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> List[MemoryItem]:
        """
        Search memory for relevant items.

        Args:
            query: Search query (semantic or keyword)
            limit: Max results to return

        Returns:
            List of matching MemoryItems
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Delete an item by key.

        Args:
            key: Item identifier

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def clear(self, older_than: Optional[datetime] = None) -> int:
        """
        Clear memory, optionally only items older than timestamp.

        Args:
            older_than: If provided, only clear items before this time

        Returns:
            Number of items cleared
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """
        Get total number of items in memory.

        Returns:
            Item count
        """
        pass

    def close(self) -> None:
        """Clean up resources (override if needed)"""
        pass


class ConversationMemory(BaseMemory):
    """
    Abstract base for conversation-specific memory.

    Extends BaseMemory with conversation-aware methods.
    """

    @abstractmethod
    def add_message(self, message: Message) -> str:
        """Add a message to conversation history"""
        pass

    @abstractmethod
    def get_messages(self, limit: Optional[int] = None) -> List[Message]:
        """Get conversation messages, optionally limited"""
        pass

    @abstractmethod
    def get_context_string(self, limit: int = 10) -> str:
        """Get conversation as formatted string for prompt injection"""
        pass


class SemanticMemory(BaseMemory):
    """
    Abstract base for semantic/vector memory.

    Extends BaseMemory with embedding-aware methods.
    """

    @abstractmethod
    def store_with_embedding(
        self,
        content: str,
        metadata: Optional[Dict] = None,
        embedding: Optional[List[float]] = None
    ) -> str:
        """Store content with its embedding vector"""
        pass

    @abstractmethod
    def search_similar(
        self,
        query: str,
        limit: int = 5,
        threshold: float = 0.7
    ) -> List[MemoryItem]:
        """Search for semantically similar items"""
        pass


class EpisodicMemoryBase(BaseMemory):
    """
    Abstract base for episodic/action history memory.

    Extends BaseMemory with action tracking methods.
    """

    @abstractmethod
    def log_action(self, action: ActionRecord) -> str:
        """Log a tool execution"""
        pass

    @abstractmethod
    def get_actions(
        self,
        agent: Optional[str] = None,
        tool: Optional[str] = None,
        limit: int = 20
    ) -> List[ActionRecord]:
        """Get action history with optional filters"""
        pass

    @abstractmethod
    def get_tool_stats(self, tool: str) -> Dict[str, Any]:
        """Get statistics for a specific tool (success rate, avg duration, etc.)"""
        pass
