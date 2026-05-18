"""
Input validation helpers for CLI

Provides reusable validation functions with clear error messages.
"""

import re
from typing import Optional, List


def validate_agent_name(name: str) -> tuple[bool, Optional[str]]:
    """
    Validate agent name.

    Args:
        name: Agent name to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Agent name cannot be empty"

    if len(name) > 100:
        return False, "Agent name must be 100 characters or less"

    # Allow alphanumeric, spaces, hyphens, underscores
    if not re.match(r'^[a-zA-Z0-9\s\-_]+$', name):
        return False, "Agent name can only contain letters, numbers, spaces, hyphens, and underscores"

    return True, None


def validate_model_name(model: str) -> tuple[bool, Optional[str]]:
    """
    Validate LLM model name.

    Args:
        model: Model name to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not model or not model.strip():
        return False, "Model name cannot be empty"

    # Common model patterns
    valid_models = [
        "gpt-4o", "gpt-4o-mini", "gpt-4", "gpt-4-turbo", "gpt-3.5-turbo",
        "claude-3-opus", "claude-3-sonnet", "claude-3-haiku",
        "claude-3-5-sonnet", "claude-3-5-haiku",
        "gemini-pro", "gemini-1.5-pro", "gemini-1.5-flash",
    ]

    if model not in valid_models:
        return False, f"Unknown model '{model}'. Supported: {', '.join(valid_models[:5])}..."

    return True, None


def validate_temperature(temperature: float) -> tuple[bool, Optional[str]]:
    """
    Validate temperature parameter.

    Args:
        temperature: Temperature value

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not 0.0 <= temperature <= 2.0:
        return False, "Temperature must be between 0.0 and 2.0"

    return True, None


def validate_tool_names(tools: List[str], available_tools: List[str]) -> tuple[bool, Optional[str], List[str]]:
    """
    Validate list of tool names.

    Args:
        tools: Tool names to validate
        available_tools: List of available tool names

    Returns:
        Tuple of (is_valid, error_message, invalid_tools)
    """
    if not tools:
        return False, "At least one tool must be specified", []

    invalid_tools = [t for t in tools if t not in available_tools]

    if invalid_tools:
        return False, f"Invalid tools: {', '.join(invalid_tools)}", invalid_tools

    return True, None, []


def validate_workflow_type(workflow_type: str) -> tuple[bool, Optional[str]]:
    """
    Validate workflow type.

    Args:
        workflow_type: Workflow type to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    valid_types = ["chain", "conditional", "parallel"]

    if workflow_type not in valid_types:
        return False, f"Invalid workflow type. Must be one of: {', '.join(valid_types)}"

    return True, None


def validate_max_iterations(max_iterations: int) -> tuple[bool, Optional[str]]:
    """
    Validate max iterations parameter.

    Args:
        max_iterations: Max iterations value

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not 1 <= max_iterations <= 50:
        return False, "Max iterations must be between 1 and 50"

    return True, None


def sanitize_name(name: str) -> str:
    """
    Sanitize a name for use in file paths.

    Args:
        name: Name to sanitize

    Returns:
        Sanitized name
    """
    # Replace spaces with underscores
    name = name.strip().replace(" ", "_")

    # Remove invalid characters
    name = re.sub(r'[^a-zA-Z0-9_\-]', '', name)

    return name
