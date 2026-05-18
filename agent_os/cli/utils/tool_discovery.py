"""
Tool Discovery with Fuzzy Search

Provides typo-tolerant tool name matching using similarity scoring.
"""

from difflib import SequenceMatcher
from typing import List, Tuple, Optional


def calculate_similarity(query: str, target: str) -> float:
    """
    Calculate similarity score between two strings.

    Args:
        query: Search query (user input)
        target: Target string to match against

    Returns:
        Similarity score between 0.0 and 1.0
    """
    query_lower = query.lower()
    target_lower = target.lower()

    # Base similarity using SequenceMatcher (Levenshtein-like)
    base_score = SequenceMatcher(None, query_lower, target_lower).ratio()

    # Boost for substring matches
    if query_lower in target_lower:
        substring_boost = 0.2
        base_score = min(1.0, base_score + substring_boost)

    # Boost for prefix matches (user typed start of tool name)
    if target_lower.startswith(query_lower):
        prefix_boost = 0.15
        base_score = min(1.0, base_score + prefix_boost)

    return base_score


def fuzzy_search_tools(
    query: str,
    available_tools: List[str],
    threshold: float = 0.6,
    max_results: int = 5
) -> List[Tuple[str, float]]:
    """
    Search for tools using fuzzy matching.

    Args:
        query: Tool name query (potentially with typos)
        available_tools: List of available tool names
        threshold: Minimum similarity score (0.0-1.0)
        max_results: Maximum number of results to return

    Returns:
        List of (tool_name, similarity_score) tuples, sorted by score descending
    """
    if not query or not available_tools:
        return []

    # Calculate similarity scores for all tools
    scored_tools = [
        (tool, calculate_similarity(query, tool))
        for tool in available_tools
    ]

    # Filter by threshold and sort by score
    matches = [
        (tool, score)
        for tool, score in scored_tools
        if score >= threshold
    ]

    matches.sort(key=lambda x: x[1], reverse=True)

    return matches[:max_results]


def suggest_similar_tools(
    invalid_tool: str,
    tool_registry,
    threshold: float = 0.6,
    max_suggestions: int = 5
) -> List[str]:
    """
    Suggest similar tool names for an invalid tool.

    Args:
        invalid_tool: The tool name that wasn't found
        tool_registry: ToolRegistry instance
        threshold: Minimum similarity score
        max_suggestions: Maximum suggestions to return

    Returns:
        List of suggested tool names
    """
    available_tools = tool_registry.list_all()

    if not available_tools:
        return []

    matches = fuzzy_search_tools(
        invalid_tool,
        available_tools,
        threshold=threshold,
        max_results=max_suggestions
    )

    return [tool for tool, _ in matches]


def format_tool_suggestions(invalid_tool: str, suggestions: List[str]) -> str:
    """
    Format tool suggestions into a user-friendly message.

    Args:
        invalid_tool: The tool that wasn't found
        suggestions: List of suggested tool names

    Returns:
        Formatted error message with suggestions
    """
    if not suggestions:
        return f"Tool '{invalid_tool}' not found. Use 'agent_os list tools' to see available tools."

    suggestion_list = "\n".join(f"  - {tool}" for tool in suggestions)

    return f"""Tool '{invalid_tool}' not found. Did you mean one of these?

{suggestion_list}

Use 'agent_os list tools' to see all available tools."""
