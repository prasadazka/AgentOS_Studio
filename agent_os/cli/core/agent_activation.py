"""
Agent Activation Manager

Handles persistent agent mode with folder-scoped file discovery.
Enables agents to work within a specific directory context.
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from functools import lru_cache

from pydantic import BaseModel, Field

from agent_os.cli.core.config_generator import ConfigGenerator
from agent_os.agents.defaults import is_default_agent, load_default_agent
from agent_os.utils.logging import get_logger

logger = get_logger("cli.core.agent_activation")


# Session file name stored in working directory
SESSION_FILE_NAME = ".agent_session.json"


class AgentSessionMemory(BaseModel):
    """
    Persistent session memory stored in working directory.

    Tracks file usage across queries so agent remembers context.
    """
    last_agent: Optional[str] = None
    last_used_file: Optional[str] = None  # Full path of last file accessed
    last_used_file_type: Optional[str] = None  # csv, json, txt, etc.
    file_history: List[str] = Field(default_factory=list)  # Last 5 files accessed
    last_query: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def add_file_to_history(self, file_path: str):
        """Add file to history, keeping last 5"""
        if file_path in self.file_history:
            self.file_history.remove(file_path)
        self.file_history.insert(0, file_path)
        self.file_history = self.file_history[:5]
        self.last_used_file = file_path
        self.last_used_file_type = Path(file_path).suffix.lower().lstrip('.')
        self.updated_at = datetime.now()

    def to_context_string(self) -> str:
        """Generate context string for prompt injection"""
        if not self.last_used_file:
            return ""

        file_name = Path(self.last_used_file).name
        file_type = self.last_used_file_type or "file"

        context_parts = [
            f"\n*** SESSION MEMORY (CRITICAL - READ THIS) ***",
            f"  CURRENT WORKING FILE: {self.last_used_file}",
            f"  FILE TYPE: {file_type}",
        ]

        if len(self.file_history) > 1:
            recent = ", ".join(Path(f).name for f in self.file_history[1:4])
            context_parts.append(f"  RECENT FILES: {recent}")

        context_parts.extend([
            f"",
            f"*** AUTO-USE RULE (MANDATORY) ***",
            f"If user asks ANY question about data/analysis WITHOUT specifying a file:",
            f"  → AUTOMATICALLY use '{file_name}' at path: {self.last_used_file}",
            f"  → DO NOT ask 'which file?' or 'please confirm'",
            f"  → DO NOT say 'I need a file path'",
            f"  → JUST READ THE FILE AND ANSWER",
            f"",
            f"Examples of queries that should AUTO-USE the current file:",
            f"  - 'who purchased twice?' → use {file_name}",
            f"  - 'give discount to...' → use {file_name}",
            f"  - 'total revenue?' → use {file_name}",
            f"  - 'show customers' → use {file_name}",
            f"***",
        ])

        return "\n".join(context_parts)


def load_session(working_directory: Path) -> Optional[AgentSessionMemory]:
    """Load session from working directory"""
    session_path = working_directory / SESSION_FILE_NAME

    if not session_path.exists():
        return None

    try:
        with open(session_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Parse datetime fields
        if data.get('created_at'):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('updated_at'):
            data['updated_at'] = datetime.fromisoformat(data['updated_at'])

        return AgentSessionMemory(**data)
    except Exception as e:
        logger.warning(f"Failed to load session from {session_path}: {e}")
        return None


def save_session(working_directory: Path, session: AgentSessionMemory) -> bool:
    """Save session to working directory"""
    session_path = working_directory / SESSION_FILE_NAME

    try:
        data = session.model_dump()

        # Convert datetime to string
        if data.get('created_at'):
            data['created_at'] = data['created_at'].isoformat()
        if data.get('updated_at'):
            data['updated_at'] = data['updated_at'].isoformat()

        with open(session_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        logger.debug(f"Session saved to {session_path}")
        return True
    except Exception as e:
        logger.warning(f"Failed to save session to {session_path}: {e}")
        return False


class DiscoveredFile(BaseModel):
    """Compact file metadata for context injection"""
    path: str
    name: str
    extension: str
    size_bytes: int
    size_human: str
    modified: datetime
    is_recent: bool = False  # Modified in last 24h

    class Config:
        frozen = True


class AgentActivationState(BaseModel):
    """Persisted activation state"""
    is_activated: bool = False
    agent_name: Optional[str] = None
    working_directory: str = ""
    discovered_files: List[DiscoveredFile] = Field(default_factory=list)
    activated_at: Optional[datetime] = None
    safety_mode: bool = True
    file_extensions: List[str] = Field(default_factory=list)


class ActivationResult(BaseModel):
    """Result of activation attempt"""
    success: bool
    agent_name: Optional[str] = None
    files_count: int = 0
    total_size_human: str = "0 B"
    discovered_files: List[DiscoveredFile] = Field(default_factory=list)
    error: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)
    session: Optional[AgentSessionMemory] = None  # Loaded session from previous activation


class AgentActivationManager:
    """
    Manages agent activation lifecycle.

    Features:
    - Auto-discovers relevant files on activation
    - Builds context prompt with discovered files
    - Manages activation state for session persistence
    - Provides safety controls for destructive operations
    """

    # Agent type → file extensions to discover
    AGENT_FILE_PATTERNS: Dict[str, List[str]] = {
        "DataAnalyst": [".csv", ".json", ".xlsx", ".xls", ".txt", ".parquet", ".tsv"],
        "Developer": [".py", ".js", ".ts", ".jsx", ".tsx", ".yaml", ".yml", ".json", ".toml", ".md"],
        "Researcher": [".pdf", ".txt", ".md", ".bib", ".tex"],
        "CodeReviewer": [".py", ".js", ".ts", ".java", ".go", ".rs", ".c", ".cpp", ".h"],
        "SupportAgent": [".log", ".txt", ".json", ".md", ".yaml"],
    }

    # Directories to always ignore
    IGNORE_DIRS = {
        ".git", ".svn", ".hg",
        "node_modules", "__pycache__", ".venv", "venv", "env",
        ".idea", ".vscode", ".vs",
        "dist", "build", "target", "out",
        ".pytest_cache", ".mypy_cache", ".tox",
        "egg-info", ".eggs",
    }

    # Files to always ignore
    IGNORE_FILES = {
        ".DS_Store", "Thumbs.db", ".gitignore", ".gitattributes",
        "package-lock.json", "yarn.lock", "poetry.lock",
    }

    MAX_DISCOVERED_FILES = 50
    MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB per file
    MAX_SCAN_DEPTH = 4

    def __init__(
        self,
        working_directory: Path,
        tool_registry=None,
    ):
        self.working_directory = Path(working_directory).resolve()
        self.tool_registry = tool_registry
        self.state: Optional[AgentActivationState] = None
        self._config_generator = ConfigGenerator()
        self.session: Optional[AgentSessionMemory] = None

    def activate(self, agent_name: str) -> ActivationResult:
        """
        Activate an agent with file discovery.

        Args:
            agent_name: Name of the agent to activate

        Returns:
            ActivationResult with success status and discovered files
        """
        # Validate agent exists
        agent_config = self._load_agent_config(agent_name)
        if not agent_config:
            return ActivationResult(
                success=False,
                error=f"Agent '{agent_name}' not found",
                suggestions=[
                    "Use /list agents to see available agents",
                    "Create a new agent with /create agent",
                ]
            )

        # Get file extensions for this agent type
        extensions = self._get_extensions_for_agent(agent_name)

        # Discover files
        discovered_files = self.discover_files(extensions)

        # Calculate total size
        total_size = sum(f.size_bytes for f in discovered_files)
        total_size_human = self._humanize_bytes(total_size)

        # Load previous session from working directory
        self.session = load_session(self.working_directory)
        if self.session:
            logger.info(
                f"Loaded previous session: last_file={self.session.last_used_file}, "
                f"history={len(self.session.file_history)} files"
            )
            # Update session with new agent name
            self.session.last_agent = agent_name
            self.session.updated_at = datetime.now()
        else:
            # Create new session
            self.session = AgentSessionMemory(
                last_agent=agent_name,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            logger.info("Created new session")

        # Create activation state
        self.state = AgentActivationState(
            is_activated=True,
            agent_name=agent_name,
            working_directory=str(self.working_directory),
            discovered_files=discovered_files,
            activated_at=datetime.now(),
            safety_mode=True,
            file_extensions=extensions,
        )

        return ActivationResult(
            success=True,
            agent_name=agent_name,
            files_count=len(discovered_files),
            total_size_human=total_size_human,
            discovered_files=discovered_files,
            session=self.session,
        )

    def deactivate(self) -> None:
        """Deactivate current agent and clear state, saving session"""
        # Save session before deactivating
        if self.session:
            save_session(self.working_directory, self.session)
            logger.info(f"Session saved to {self.working_directory / SESSION_FILE_NAME}")
        self.state = None

    def update_session_file(self, file_path: str):
        """Update session with a file that was accessed"""
        if self.session:
            self.session.add_file_to_history(file_path)
            # Auto-save session after file access
            save_session(self.working_directory, self.session)

    def is_activated(self) -> bool:
        """Check if an agent is currently activated"""
        return self.state is not None and self.state.is_activated

    def get_active_agent_name(self) -> Optional[str]:
        """Get the name of the currently activated agent"""
        if self.state and self.state.is_activated:
            return self.state.agent_name
        return None

    def get_prompt_prefix(self) -> str:
        """Get prompt prefix for activated agent"""
        if self.state and self.state.is_activated:
            return f"[{self.state.agent_name}]"
        return "[You]"

    def discover_files(
        self,
        extensions: List[str],
        max_files: Optional[int] = None,
        max_depth: Optional[int] = None,
    ) -> List[DiscoveredFile]:
        """
        Discover files matching extensions in working directory.

        Args:
            extensions: List of file extensions to match (e.g., [".csv", ".json"])
            max_files: Maximum files to return (default: MAX_DISCOVERED_FILES)
            max_depth: Maximum directory depth to scan (default: MAX_SCAN_DEPTH)

        Returns:
            List of DiscoveredFile sorted by modification time (newest first)
        """
        max_files = max_files or self.MAX_DISCOVERED_FILES
        max_depth = max_depth or self.MAX_SCAN_DEPTH

        discovered = []
        extensions_lower = {ext.lower() for ext in extensions}

        try:
            for file_path in self._walk_directory(self.working_directory, max_depth):
                # Check extension
                if file_path.suffix.lower() not in extensions_lower:
                    continue

                # Check if file is ignorable
                if file_path.name in self.IGNORE_FILES:
                    continue

                # Get file stats
                try:
                    stat = file_path.stat()
                    size = stat.st_size

                    # Skip files too large
                    if size > self.MAX_FILE_SIZE_BYTES:
                        continue

                    modified = datetime.fromtimestamp(stat.st_mtime)
                    is_recent = (datetime.now() - modified).days < 1

                    discovered.append(DiscoveredFile(
                        path=str(file_path),
                        name=file_path.name,
                        extension=file_path.suffix.lower(),
                        size_bytes=size,
                        size_human=self._humanize_bytes(size),
                        modified=modified,
                        is_recent=is_recent,
                    ))

                except (OSError, PermissionError):
                    continue

                # Stop if we have enough files
                if len(discovered) >= max_files * 2:  # Collect extra for sorting
                    break

        except (OSError, PermissionError) as e:
            # Log but don't crash
            pass

        # Sort by modification time (newest first) and limit
        discovered.sort(key=lambda f: f.modified, reverse=True)
        return discovered[:max_files]

    def _walk_directory(self, root: Path, max_depth: int) -> List[Path]:
        """Walk directory up to max_depth, respecting ignore patterns"""
        files = []

        def _walk(current: Path, depth: int):
            if depth > max_depth:
                return

            try:
                for entry in current.iterdir():
                    # Skip ignored directories
                    if entry.is_dir():
                        if entry.name in self.IGNORE_DIRS:
                            continue
                        if entry.name.startswith('.'):
                            continue
                        _walk(entry, depth + 1)
                    elif entry.is_file():
                        files.append(entry)
            except (OSError, PermissionError):
                pass

        _walk(root, 0)
        return files

    def build_context_prompt(self) -> str:
        """
        Build context string for system prompt injection.

        Returns:
            Formatted context string with discovered files
        """
        if not self.state or not self.state.is_activated:
            return ""

        files = self.state.discovered_files
        if not files:
            return f"""
=== ACTIVE MODE: {self.state.agent_name} ===
Working Directory: {self.state.working_directory}

No matching files discovered in this directory.
Ask user to provide specific file paths if needed.
===
"""

        # Calculate totals
        total_size = sum(f.size_bytes for f in files)
        total_size_human = self._humanize_bytes(total_size)

        # Build file list (compact format) - show relative paths
        file_lines = []
        for f in files[:30]:  # Show top 30 in prompt
            age = self._get_file_age(f.modified)
            recent_marker = " *" if f.is_recent else ""
            # Show relative path from working directory
            try:
                rel_path = Path(f.path).relative_to(self.working_directory)
                display_path = str(rel_path)
            except ValueError:
                display_path = f.name
            file_lines.append(f"  - {display_path} ({f.size_human}, {age}){recent_marker}")

        if len(files) > 30:
            file_lines.append(f"  ... and {len(files) - 30} more files")

        file_list = "\n".join(file_lines)

        return f"""
=== ACTIVE MODE: {self.state.agent_name} ===
Working Directory: {self.state.working_directory}

DISCOVERED FILES ({len(files)} files, {total_size_human} total):
{file_list}

INSTRUCTIONS:
- Reference files above by path when user asks about data
- Use file tools to read actual content - NEVER guess or assume data
- If user asks about a file not listed, ask them for the specific path
- Files marked with * were modified in the last 24 hours

SAFETY RULES:
- NO file deletions without explicit user confirmation
- Ask before overwriting existing files
- Report any errors encountered when reading files
===
"""

    def get_enhanced_system_prompt(self, base_prompt: str) -> str:
        """
        Inject discovered files context into agent's system prompt.

        Args:
            base_prompt: Original system prompt from agent config

        Returns:
            Enhanced system prompt with file context prepended
        """
        context = self.build_context_prompt()
        if not context:
            return base_prompt

        return f"{context}\n\n{base_prompt}"

    def get_state_dict(self) -> Optional[Dict[str, Any]]:
        """Get state as dictionary for persistence"""
        if not self.state:
            return None

        return {
            "is_activated": self.state.is_activated,
            "agent_name": self.state.agent_name,
            "working_directory": self.state.working_directory,
            "activated_at": self.state.activated_at.isoformat() if self.state.activated_at else None,
            "safety_mode": self.state.safety_mode,
            "file_extensions": self.state.file_extensions,
            "files_count": len(self.state.discovered_files),
        }

    def restore_state(self, state_dict: Dict[str, Any]) -> bool:
        """
        Restore activation state from dictionary.

        Args:
            state_dict: Previously saved state dictionary

        Returns:
            True if restoration successful
        """
        if not state_dict or not state_dict.get("is_activated"):
            return False

        agent_name = state_dict.get("agent_name")
        if not agent_name:
            return False

        # Re-activate with fresh file discovery
        result = self.activate(agent_name)
        return result.success

    def _load_agent_config(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """Load agent configuration"""
        try:
            # Check default agents first
            if is_default_agent(agent_name):
                return load_default_agent(agent_name)

            # Load from user configs
            return self._config_generator.load_and_validate_config("agents", agent_name)
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def _get_extensions_for_agent(self, agent_name: str) -> List[str]:
        """Get file extensions to discover for an agent type"""
        # Check if we have specific patterns for this agent
        for pattern_name, extensions in self.AGENT_FILE_PATTERNS.items():
            if pattern_name.lower() in agent_name.lower():
                return extensions

        # Fall back to default patterns
        return self.AGENT_FILE_PATTERNS.get("DataAnalyst", [".csv", ".json", ".txt"])

    @staticmethod
    def _humanize_bytes(size_bytes: int) -> str:
        """Convert bytes to human-readable string"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def _get_file_age(modified: datetime) -> str:
        """Get human-readable file age"""
        delta = datetime.now() - modified
        seconds = delta.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            mins = int(seconds / 60)
            return f"{mins}m ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h ago"
        elif seconds < 86400 * 7:
            days = int(seconds / 86400)
            return f"{days}d ago"
        elif seconds < 86400 * 30:
            weeks = int(seconds / (86400 * 7))
            return f"{weeks}w ago"
        else:
            return modified.strftime("%Y-%m-%d")
