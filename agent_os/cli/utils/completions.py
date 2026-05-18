"""Shell completion utilities for CLI"""

from pathlib import Path
from typing import List


def complete_agent_name(incomplete: str) -> List[str]:
    """
    Autocomplete agent names from ~/.agent_os/configs/agents/

    Args:
        incomplete: Partial agent name typed by user

    Returns:
        List of matching agent names
    """
    try:
        from agent_os.cli.core.config_generator import ConfigGenerator
        generator = ConfigGenerator()
        config_dir = generator.config_dir / "agents"

        if not config_dir.exists():
            return []

        # Get all .yaml files in agents directory
        agent_files = list(config_dir.glob("*.yaml")) + list(config_dir.glob("*.yml"))
        agent_names = [f.stem for f in agent_files]

        # Filter by incomplete input
        if incomplete:
            return [name for name in agent_names if name.startswith(incomplete)]
        return agent_names
    except Exception:
        return []


def complete_tool_name(incomplete: str) -> List[str]:
    """
    Autocomplete tool names from registry

    Args:
        incomplete: Partial tool name typed by user

    Returns:
        List of matching tool names
    """
    try:
        from agent_os.tools.global_registry import get_global_registry
        registry = get_global_registry()
        tool_names = registry.list_all()

        # Filter by incomplete input
        if incomplete:
            return [name for name in tool_names if name.startswith(incomplete)]
        return tool_names
    except Exception:
        return []


def complete_workflow_name(incomplete: str) -> List[str]:
    """
    Autocomplete workflow names from ~/.agent_os/configs/workflows/

    Args:
        incomplete: Partial workflow name typed by user

    Returns:
        List of matching workflow names
    """
    try:
        from agent_os.cli.core.config_generator import ConfigGenerator
        generator = ConfigGenerator()
        config_dir = generator.config_dir / "workflows"

        if not config_dir.exists():
            return []

        # Get all .yaml files in workflows directory
        workflow_files = list(config_dir.glob("*.yaml")) + list(config_dir.glob("*.yml"))
        workflow_names = [f.stem for f in workflow_files]

        # Filter by incomplete input
        if incomplete:
            return [name for name in workflow_names if name.startswith(incomplete)]
        return workflow_names
    except Exception:
        return []


def complete_resource_type(incomplete: str) -> List[str]:
    """
    Autocomplete resource types (agents, tools, workflows)

    Args:
        incomplete: Partial type typed by user

    Returns:
        List of matching resource types
    """
    resource_types = ["agents", "tools", "workflows"]

    if incomplete:
        return [t for t in resource_types if t.startswith(incomplete)]
    return resource_types


def complete_model_name(incomplete: str) -> List[str]:
    """
    Autocomplete LLM model names

    Args:
        incomplete: Partial model name typed by user

    Returns:
        List of matching model names
    """
    models = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
        "claude-3-5-sonnet-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "gemini-1.5-pro",
        "gemini-1.5-flash"
    ]

    if incomplete:
        return [m for m in models if m.startswith(incomplete)]
    return models
