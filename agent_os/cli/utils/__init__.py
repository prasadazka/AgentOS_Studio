"""Utility functions for CLI"""

from agent_os.cli.utils.tool_discovery import fuzzy_search_tools, suggest_similar_tools
from agent_os.cli.utils.session import ensure_agent_os_directories, get_agent_os_home
from agent_os.cli.utils.completions import (
    complete_agent_name,
    complete_tool_name,
    complete_workflow_name,
    complete_resource_type,
    complete_model_name,
)

__all__ = [
    "fuzzy_search_tools",
    "suggest_similar_tools",
    "ensure_agent_os_directories",
    "get_agent_os_home",
    "complete_agent_name",
    "complete_tool_name",
    "complete_workflow_name",
    "complete_resource_type",
    "complete_model_name",
]
