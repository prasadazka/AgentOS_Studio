"""Session and directory management for AgentOS CLI"""

import os
from pathlib import Path
from typing import Dict


def get_agent_os_home() -> Path:
    """Get the AgentOS home directory (~/.agent_os/)"""
    return Path.home() / ".agent_os"


def ensure_agent_os_directories() -> Dict[str, Path]:
    """
    Ensure all required AgentOS directories exist.

    Returns:
        Dictionary mapping directory names to their paths
    """
    home = get_agent_os_home()

    directories = {
        "home": home,
        "sessions": home / "sessions",
        "configs": home / "configs",
        "agents": home / "configs" / "agents",
        "tools": home / "configs" / "tools",
        "workflows": home / "configs" / "workflows",
        "credentials": home / "credentials",
        "exports": home / "exports",
    }

    # Create all directories
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=True)

    # Create .gitignore if it doesn't exist
    gitignore_path = home / ".gitignore"
    if not gitignore_path.exists():
        gitignore_content = """# Sensitive files
.env
credentials/
*.enc

# Session data
sessions/

# Logs
errors.log
audit.log

# History
history
"""
        gitignore_path.write_text(gitignore_content)

    return directories


def get_session_path(session_id: str) -> Path:
    """Get path to a session file"""
    return get_agent_os_home() / "sessions" / f"{session_id}.json"


def get_config_path(config_type: str, name: str) -> Path:
    """
    Get path to a config file.

    Args:
        config_type: Type of config ('agents', 'tools', 'workflows')
        name: Name of the config

    Returns:
        Path to the config YAML file
    """
    return get_agent_os_home() / "configs" / config_type / f"{name}.yaml"
