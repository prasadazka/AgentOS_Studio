"""Schema export utilities for cross-framework tool compatibility

Supports exporting tool schemas to:
- OpenAI Function Calling format
- Anthropic Claude Tool Use format
- MCP (Model Context Protocol) format
- JSON Schema
"""

import inspect
from typing import Any, Dict, List, Optional, get_type_hints, get_origin, get_args
from pydantic import BaseModel

from agent_os.tools.base import BaseTool


# =============================================================================
# Type Mapping Tables
# =============================================================================

PYTHON_TO_JSON_SCHEMA_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    List: "array",
    Dict: "object",
    Any: "string",  # Fallback
}


# =============================================================================
# Schema Builders
# =============================================================================

class SchemaBuilder:
    """Build tool schemas from BaseTool instances"""

    @staticmethod
    def _get_parameter_schema(param_name: str, param_type: type, param_default: Any) -> Dict[str, Any]:
        """Convert Python type to JSON Schema type"""

        # Handle Optional types
        origin = get_origin(param_type)
        if origin is type(None) or str(param_type).startswith('typing.Union'):
            # Optional type - extract inner type
            args = get_args(param_type)
            if args:
                # Get first non-None type
                inner_type = next((arg for arg in args if arg is not type(None)), str)
                param_type = inner_type

        # Handle List[T] and Dict[K, V]
        if origin in (list, List):
            args = get_args(param_type)
            item_type = args[0] if args else str
            return {
                "type": "array",
                "items": {"type": PYTHON_TO_JSON_SCHEMA_TYPES.get(item_type, "string")}
            }

        if origin in (dict, Dict):
            return {"type": "object"}

        # Simple type mapping
        json_type = PYTHON_TO_JSON_SCHEMA_TYPES.get(param_type, "string")
        return {"type": json_type}

    @staticmethod
    def _extract_parameters(tool: BaseTool) -> Dict[str, Any]:
        """Extract parameters from tool's _execute method"""
        sig = inspect.signature(tool._execute)
        type_hints = get_type_hints(tool._execute)

        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue

            param_type = type_hints.get(param_name, str)
            param_schema = SchemaBuilder._get_parameter_schema(
                param_name,
                param_type,
                param.default
            )

            # Add description if available from docstring
            properties[param_name] = param_schema

            # Mark as required if no default value
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        return {
            "type": "object",
            "properties": properties,
            "required": required
        }

    @staticmethod
    def to_openai_schema(tool: BaseTool) -> Dict[str, Any]:
        """
        Export tool schema in OpenAI Function Calling format

        Returns:
            Dict compatible with OpenAI's function calling API
        """
        parameters = SchemaBuilder._extract_parameters(tool)

        return {
            "type": "function",
            "function": {
                "name": tool.metadata.name,
                "description": tool.metadata.description,
                "parameters": parameters
            }
        }

    @staticmethod
    def to_anthropic_schema(tool: BaseTool) -> Dict[str, Any]:
        """
        Export tool schema in Anthropic Claude Tool Use format

        Returns:
            Dict compatible with Anthropic's tool use API
        """
        parameters = SchemaBuilder._extract_parameters(tool)

        return {
            "name": tool.metadata.name,
            "description": tool.metadata.description,
            "input_schema": parameters
        }

    @staticmethod
    def to_mcp_schema(tool: BaseTool) -> Dict[str, Any]:
        """
        Export tool schema in MCP (Model Context Protocol) format

        Returns:
            Dict compatible with MCP tool registration
        """
        parameters = SchemaBuilder._extract_parameters(tool)

        return {
            "name": tool.metadata.name,
            "description": tool.metadata.description,
            "inputSchema": parameters,
            "metadata": {
                "version": tool.metadata.version,
                "category": tool.metadata.category,
                "tags": tool.metadata.tags,
                "requiresAuth": tool.metadata.requires_auth,
                "supportsAsync": tool.metadata.supports_async
            }
        }

    @staticmethod
    def to_json_schema(tool: BaseTool) -> Dict[str, Any]:
        """
        Export tool schema as pure JSON Schema

        Returns:
            JSON Schema document
        """
        parameters = SchemaBuilder._extract_parameters(tool)

        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": tool.metadata.name,
            "description": tool.metadata.description,
            "type": "object",
            "properties": {
                "input": parameters
            },
            "required": ["input"],
            "additionalProperties": False,
            "metadata": {
                "version": tool.metadata.version,
                "category": tool.metadata.category,
                "tags": tool.metadata.tags
            }
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def export_tool_schema(
    tool: BaseTool,
    format: str = "openai"
) -> Dict[str, Any]:
    """
    Export tool schema in specified format

    Args:
        tool: BaseTool instance
        format: Schema format - 'openai', 'anthropic', 'mcp', 'json_schema'

    Returns:
        Schema dict in requested format

    Raises:
        ValueError: If format is not supported
    """
    format_lower = format.lower()

    if format_lower == "openai":
        return SchemaBuilder.to_openai_schema(tool)
    elif format_lower == "anthropic":
        return SchemaBuilder.to_anthropic_schema(tool)
    elif format_lower == "mcp":
        return SchemaBuilder.to_mcp_schema(tool)
    elif format_lower == "json_schema":
        return SchemaBuilder.to_json_schema(tool)
    else:
        raise ValueError(
            f"Unsupported schema format: {format}. "
            f"Supported formats: openai, anthropic, mcp, json_schema"
        )


def export_tools_schemas(
    tools: List[BaseTool],
    format: str = "openai"
) -> List[Dict[str, Any]]:
    """
    Export multiple tool schemas in specified format

    Args:
        tools: List of BaseTool instances
        format: Schema format - 'openai', 'anthropic', 'mcp', 'json_schema'

    Returns:
        List of schema dicts in requested format
    """
    return [export_tool_schema(tool, format) for tool in tools]


def export_tool_schema_json(
    tool: BaseTool,
    format: str = "openai",
    indent: int = 2
) -> str:
    """
    Export tool schema as JSON string

    Args:
        tool: BaseTool instance
        format: Schema format - 'openai', 'anthropic', 'mcp', 'json_schema'
        indent: JSON indentation (default: 2)

    Returns:
        JSON string of schema
    """
    import json
    schema = export_tool_schema(tool, format)
    return json.dumps(schema, indent=indent)
