"""Per-project MemoryManager pool for AgentOS Studio."""

import os
from pathlib import Path
from typing import Dict

from agent_os.memory.manager import MemoryManager

_pool: Dict[str, MemoryManager] = {}


def get_project_memory(project_id: str) -> MemoryManager:
    """Get or create a MemoryManager for a project (cached)."""
    if project_id in _pool:
        return _pool[project_id]

    persist_path = Path(os.path.expanduser(f"~/.agent_os/projects/{project_id}/memory"))
    persist_path.mkdir(parents=True, exist_ok=True)

    memory = MemoryManager(
        namespace=f"project_{project_id}",
        persist_path=str(persist_path),
        enable_long_term=True,
        enable_episodic=True,
    )
    _pool[project_id] = memory
    return memory


def evict_project_memory(project_id: str):
    """Remove a project's memory from the pool (e.g. on project delete)."""
    mem = _pool.pop(project_id, None)
    if mem:
        try:
            mem.clear_all()
        except Exception:
            pass
