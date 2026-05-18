"""
Memory management for AgentOS.

Provides multi-tier memory system for agents:
- Short-term: Conversation context buffer
- Long-term: Semantic vector memory (ChromaDB)
- Episodic: Tool execution history (SQLite)
- Shared: Cross-agent memory pool for workflows
"""

from .base import (
    BaseMemory,
    ConversationMemory,
    SemanticMemory,
    EpisodicMemoryBase,
    Message,
    MemoryItem,
    ActionRecord
)
from .short_term import ShortTermMemory
from .episodic import EpisodicMemory
from .manager import (
    MemoryManager,
    create_memory_manager,
    create_lightweight_memory
)
from .shared import (
    SharedMemoryPool,
    SharedMessage,
    AgentOutput,
    get_shared_pool,
    cleanup_pools
)

# Long-term memory is optional (requires ChromaDB)
try:
    from .long_term import LongTermMemory, is_chromadb_available
    _LONGTERM_AVAILABLE = is_chromadb_available()
except ImportError:
    LongTermMemory = None
    _LONGTERM_AVAILABLE = False

    def is_chromadb_available():
        return False


__all__ = [
    # Base classes
    "BaseMemory",
    "ConversationMemory",
    "SemanticMemory",
    "EpisodicMemoryBase",
    # Data models
    "Message",
    "MemoryItem",
    "ActionRecord",
    # Memory implementations
    "ShortTermMemory",
    "LongTermMemory",
    "EpisodicMemory",
    # Manager
    "MemoryManager",
    "create_memory_manager",
    "create_lightweight_memory",
    # Shared memory
    "SharedMemoryPool",
    "SharedMessage",
    "AgentOutput",
    "get_shared_pool",
    "cleanup_pools",
    # Utilities
    "is_chromadb_available",
]
