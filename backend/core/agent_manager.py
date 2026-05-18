"""Wraps agent_os Agent/BaseAgent for the web API."""

import os
import yaml
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# Agent config directories
USER_CONFIG_DIR = Path(os.path.expanduser("~/.agent_os/configs/agents"))
DEFAULT_AGENTS_DIR = None  # resolved lazily


def _get_defaults_dir() -> Path:
    """Get the default agents directory from agent_os package."""
    global DEFAULT_AGENTS_DIR
    if DEFAULT_AGENTS_DIR is None:
        from agent_os.agents.defaults import DEFAULTS_DIR
        DEFAULT_AGENTS_DIR = DEFAULTS_DIR
    return DEFAULT_AGENTS_DIR


def list_agents() -> list[dict[str, Any]]:
    """List all agents (defaults + user-created)."""
    agents = []

    # Default agents
    defaults_dir = _get_defaults_dir()
    for f in sorted(defaults_dir.glob("*.yaml")):
        try:
            config = yaml.safe_load(f.read_text(encoding="utf-8"))
            if config and isinstance(config, dict):
                agents.append({
                    "name": config.get("name", f.stem),
                    "model": config.get("model", "gpt-4o-mini"),
                    "temperature": config.get("temperature", 0),
                    "tools": config.get("tools", []),
                    "system_prompt": config.get("system_prompt", ""),
                    "is_default": True,
                })
        except Exception:
            continue

    # User-created agents
    if USER_CONFIG_DIR.exists():
        for f in sorted(USER_CONFIG_DIR.glob("*.yaml")):
            try:
                config = yaml.safe_load(f.read_text(encoding="utf-8"))
                if config and isinstance(config, dict):
                    agents.append({
                        "name": config.get("name", f.stem),
                        "model": config.get("model", "gpt-4o-mini"),
                        "temperature": config.get("temperature", 0),
                        "tools": config.get("tools", []),
                        "system_prompt": config.get("system_prompt", ""),
                        "is_default": False,
                    })
            except Exception:
                continue

    return agents


def get_agent(name: str) -> dict[str, Any] | None:
    """Get a single agent config by name."""
    # Check user configs first
    user_file = USER_CONFIG_DIR / f"{name}.yaml"
    if user_file.exists():
        config = yaml.safe_load(user_file.read_text(encoding="utf-8"))
        if config:
            config["is_default"] = False
            return config

    # Check defaults
    defaults_dir = _get_defaults_dir()
    for f in defaults_dir.glob("*.yaml"):
        try:
            config = yaml.safe_load(f.read_text(encoding="utf-8"))
            if config and config.get("name", "").lower() == name.lower():
                config["is_default"] = True
                return config
        except Exception:
            continue

    return None


def get_agent_config_path(name: str) -> Path | None:
    """Get the file path for an agent config."""
    user_file = USER_CONFIG_DIR / f"{name}.yaml"
    if user_file.exists():
        return user_file

    defaults_dir = _get_defaults_dir()
    for f in defaults_dir.glob("*.yaml"):
        try:
            config = yaml.safe_load(f.read_text(encoding="utf-8"))
            if config and config.get("name", "").lower() == name.lower():
                return f
        except Exception:
            continue

    return None


def create_agent(config: dict[str, Any]) -> dict[str, Any]:
    """Create a new agent by saving YAML config."""
    name = config["name"]

    # Ensure directory exists
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Save YAML
    file_path = USER_CONFIG_DIR / f"{name}.yaml"
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    config["is_default"] = False
    return config


def update_agent(name: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update an existing agent config. For default agents, copies to user dir first."""
    config = get_agent(name)
    if config is None:
        raise ValueError(f"Agent '{name}' not found")

    was_default = config.get("is_default", False)

    # Remove meta fields before merging
    config.pop("is_default", None)

    # Apply updates
    for key in ("model", "temperature", "system_prompt", "tools", "max_iterations", "enable_memory"):
        if key in updates:
            config[key] = updates[key]

    # Always save to user config dir (even if originally a default)
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    file_path = USER_CONFIG_DIR / f"{name}.yaml"
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    config["is_default"] = False
    return config


def delete_agent(name: str) -> bool:
    """Delete a user-created agent. Cannot delete defaults."""
    file_path = USER_CONFIG_DIR / f"{name}.yaml"
    if file_path.exists():
        file_path.unlink()
        return True
    return False


def instantiate_agent(name: str):
    """Create a live BaseAgent instance from stored config."""
    from agent_os import Agent

    config_path = get_agent_config_path(name)
    if config_path is None:
        raise ValueError(f"Agent '{name}' not found")

    return Agent.from_file(str(config_path))


def instantiate_agent_with_memory(name: str, memory, project_files_dir: str = None):
    """Create a live BaseAgent with injected MemoryManager (for project chat)."""
    from agent_os.agents.base import BaseAgent
    from agent_os.tools.global_registry import get_global_registry
    from agent_os.config.loader import ConfigLoader

    config_path = get_agent_config_path(name)
    if config_path is None:
        raise ValueError(f"Agent '{name}' not found")

    config = ConfigLoader.load_yaml(str(config_path))
    global_registry = get_global_registry()

    # Create a copy of registry with visualization tool replaced by a stub
    # Studio renders charts inline via ```chart JSON blocks, not file-saving tools
    from agent_os.tools.registry import ToolRegistry
    from agent_os.tools.base import BaseTool, ToolMetadata
    registry = ToolRegistry(enable_telemetry=False)
    for tool_name in global_registry.list_all():
        tool = global_registry.get(tool_name)
        if tool:
            registry.register(tool, replace=True)

    # Replace dataframe_visualize with a stub that redirects to inline chart format
    class _ChartStub(BaseTool):
        def __init__(self):
            super().__init__(ToolMetadata(
                name="dataframe_visualize",
                description="DISABLED in Studio UI. Instead, output a ```chart JSON code block.",
                category="data_visualization",
                tags=["dataframe", "visualization"]
            ))
        def _execute(self, **kwargs) -> str:
            return (
                "STOP: dataframe_visualize is disabled in Studio. "
                "Instead, output chart data as a ```chart fenced code block with JSON. "
                "Example: ```chart\\n{\"type\":\"bar\",\"title\":\"My Chart\","
                "\"data\":[{\"name\":\"$0-$500\",\"count\":10}]}\\n``` "
                "Use REAL values from the data you already analyzed."
            )
    registry.register(_ChartStub(), replace=True)

    # Override directory_list to default to project files dir instead of "."
    if project_files_dir:
        _pfd = project_files_dir
        class _ScopedDirectoryList(BaseTool):
            def __init__(self):
                super().__init__(ToolMetadata(
                    name="directory_list",
                    description=f"List files in a directory. Default path: {_pfd}. Params: directory_path, pattern (glob), recursive (bool).",
                    category="data",
                    tags=["directory", "file", "list"]
                ))
            def _execute(self, directory_path: str = None, pattern: str = "*", recursive: bool = False, **kwargs) -> str:
                import glob as _glob
                from pathlib import Path as _Path
                target = _Path(directory_path) if directory_path else _Path(_pfd)
                if not target.exists():
                    return f"Directory not found: {target}"
                if recursive:
                    matches = sorted(target.rglob(pattern))
                else:
                    matches = sorted(target.glob(pattern))
                items = []
                for p in matches[:100]:
                    kind = "DIR" if p.is_dir() else f"{p.stat().st_size} bytes"
                    items.append(f"  {p.name} ({kind}) → {p}")
                if not items:
                    return f"No files matching '{pattern}' in {target}"
                return f"Contents of {target}:\n" + "\n".join(items)
        registry.register(_ScopedDirectoryList(), replace=True)

    return BaseAgent.from_config(config, tool_registry=registry, memory=memory)
