"""Wraps agent_os Tool/ToolRegistry for the web API."""

from typing import Any

_registry = None


def _get_registry():
    """Get global tool registry (lazy singleton)."""
    global _registry
    if _registry is None:
        from agent_os.tools.global_registry import get_global_registry
        _registry = get_global_registry()
    return _registry


def list_tools() -> list[dict[str, Any]]:
    """List all tools with metadata."""
    registry = _get_registry()
    tools = []

    for name in registry.list_all():
        tool = registry.get(name)
        if tool and hasattr(tool, "metadata"):
            meta = tool.metadata
            tools.append({
                "name": meta.name,
                "description": meta.description,
                "category": meta.category,
                "version": getattr(meta, "version", "1.0.0"),
                "requires_auth": getattr(meta, "requires_auth", False),
                "tags": getattr(meta, "tags", []),
            })

    return sorted(tools, key=lambda t: (t["category"], t["name"]))


def list_categories() -> list[str]:
    """List all tool categories."""
    registry = _get_registry()
    return sorted(registry.list_categories())


def search_tools(query: str) -> list[dict[str, Any]]:
    """Search tools by query string."""
    registry = _get_registry()
    results = registry.search(query)
    tools = []

    for tool in results:
        if hasattr(tool, "metadata"):
            meta = tool.metadata
            tools.append({
                "name": meta.name,
                "description": meta.description,
                "category": meta.category,
                "version": getattr(meta, "version", "1.0.0"),
                "tags": getattr(meta, "tags", []),
            })

    return tools


def get_tool_count() -> int:
    """Get total number of tools."""
    registry = _get_registry()
    return len(registry)


def get_tool_schema(name: str) -> dict[str, Any] | None:
    """Get tool parameter schema (extracted from _execute signature)."""
    registry = _get_registry()
    tool = registry.get(name)
    if not tool:
        return None

    from agent_os.tools.schemas import SchemaBuilder
    params = SchemaBuilder._extract_parameters(tool)
    meta = tool.metadata

    return {
        "name": meta.name,
        "description": meta.description,
        "category": meta.category,
        "version": getattr(meta, "version", "1.0.0"),
        "parameters": params,  # {type, properties, required}
    }
