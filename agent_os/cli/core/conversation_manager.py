"""
Conversation Manager for AgentOS CLI

Manages multi-turn conversation state with automatic persistence.
Zero data loss through auto-save after every message.
"""

import json
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from agent_os.cli.utils.session import get_session_path, ensure_agent_os_directories


class Message(BaseModel):
    """Single message in a conversation"""

    role: str = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=datetime.now, description="When message was created")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ConversationContext(BaseModel):
    """Current conversation context"""

    current_agent: Optional[str] = Field(None, description="Currently active agent name")
    current_workflow: Optional[str] = Field(None, description="Currently active workflow name")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Context variables")
    activation_state: Optional[Dict[str, Any]] = Field(None, description="Agent activation state for persistence")


class ConversationSession(BaseModel):
    """Complete conversation session"""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique session ID")
    messages: List[Message] = Field(default_factory=list, description="Conversation messages")
    context: ConversationContext = Field(default_factory=ConversationContext, description="Session context")
    created_at: datetime = Field(default_factory=datetime.now, description="Session creation time")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last update time")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ConversationManager:
    """
    Manages conversation state with automatic persistence.

    Features:
    - Auto-save after every message (zero data loss)
    - Context window trimming (keeps last 20 messages)
    - Session recovery after crashes
    - Thread-safe file operations
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        max_context_messages: int = 20,
    ):
        """
        Initialize conversation manager.

        Args:
            session_id: Existing session ID to load, or None for new session
            max_context_messages: Maximum messages to keep in context window
        """
        ensure_agent_os_directories()

        self.max_context_messages = max_context_messages
        self._lock = threading.Lock()

        if session_id:
            self.session = self._load_session(session_id)
        else:
            self.session = ConversationSession()
            self._save_session()

    def _load_session(self, session_id: str) -> ConversationSession:
        """Load session from disk"""
        session_path = get_session_path(session_id)

        if not session_path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        try:
            with open(session_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ConversationSession(**data)
        except Exception as e:
            raise RuntimeError(f"Failed to load session {session_id}: {e}")

    def _save_session(self):
        """Save session to disk (thread-safe)"""
        with self._lock:
            self.session.updated_at = datetime.now()
            session_path = get_session_path(self.session.session_id)

            try:
                # Write to temp file first, then atomic rename
                temp_path = session_path.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        self.session.model_dump(),
                        f,
                        indent=2,
                        default=str  # Handle datetime serialization
                    )

                # Atomic rename (prevents corruption on crash)
                temp_path.replace(session_path)

            except Exception as e:
                raise RuntimeError(f"Failed to save session: {e}")

    def _trim_context(self):
        """Trim context window to last N messages"""
        if len(self.session.messages) > self.max_context_messages:
            self.session.messages = self.session.messages[-self.max_context_messages:]

    def add_message(self, role: str, content: str) -> Message:
        """
        Add message to conversation and auto-save.

        Args:
            role: 'user' or 'assistant'
            content: Message content

        Returns:
            The created message
        """
        message = Message(role=role, content=content)
        self.session.messages.append(message)

        self._trim_context()
        self._save_session()

        return message

    def add_user_message(self, content: str) -> Message:
        """Add user message"""
        return self.add_message("user", content)

    def add_assistant_message(self, content: str) -> Message:
        """Add assistant message"""
        return self.add_message("assistant", content)

    def get_messages(self, limit: Optional[int] = None) -> List[Message]:
        """
        Get conversation messages.

        Args:
            limit: Maximum number of recent messages to return (None = all)

        Returns:
            List of messages
        """
        if limit is None:
            return self.session.messages.copy()
        return self.session.messages[-limit:]

    def get_recent_messages(self, limit: int = 10) -> List[Message]:
        """
        Get the most recent messages.

        Args:
            limit: Maximum number of recent messages to return

        Returns:
            List of recent messages
        """
        return self.session.messages[-limit:]

    def get_context(self) -> ConversationContext:
        """Get current conversation context"""
        return self.session.context

    def update_context(self, **kwargs):
        """
        Update conversation context.

        Args:
            **kwargs: Context fields to update (current_agent, current_workflow, variables)
        """
        if "current_agent" in kwargs:
            self.session.context.current_agent = kwargs["current_agent"]
        if "current_workflow" in kwargs:
            self.session.context.current_workflow = kwargs["current_workflow"]
        if "variables" in kwargs:
            self.session.context.variables.update(kwargs["variables"])

        self._save_session()

    def clear_messages(self):
        """Clear all messages (keeps session context)"""
        self.session.messages = []
        self._save_session()

    def save_activation_state(self, state: Dict[str, Any]):
        """
        Save agent activation state for persistence.

        Args:
            state: Activation state dictionary from AgentActivationManager
        """
        self.session.context.activation_state = state
        self._save_session()

    def load_activation_state(self) -> Optional[Dict[str, Any]]:
        """
        Load previously saved activation state.

        Returns:
            Activation state dictionary or None if not set
        """
        return self.session.context.activation_state

    def clear_activation_state(self):
        """Clear saved activation state"""
        self.session.context.activation_state = None
        self._save_session()

    def get_session_id(self) -> str:
        """Get current session ID"""
        return self.session.session_id

    def get_message_count(self) -> int:
        """Get total message count"""
        return len(self.session.messages)

    @staticmethod
    def list_sessions() -> List[str]:
        """List all saved session IDs"""
        ensure_agent_os_directories()
        sessions_dir = Path.home() / ".agent_os" / "sessions"

        return [
            p.stem for p in sessions_dir.glob("*.json")
            if not p.name.endswith('.tmp')
        ]

    @staticmethod
    def load_latest_session() -> Optional["ConversationManager"]:
        """Load the most recently updated session"""
        sessions = ConversationManager.list_sessions()
        if not sessions:
            return None

        # Find most recent session by modification time
        sessions_dir = Path.home() / ".agent_os" / "sessions"
        latest = max(
            sessions_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            default=None
        )

        if latest:
            return ConversationManager(session_id=latest.stem)
        return None
