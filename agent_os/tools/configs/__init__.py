"""
Config-Driven Tools

Industry-standard approach for scalable tool management:
- Define tools in YAML
- LLM picks from catalog
- Generic executor runs commands

Usage:
    from agent_os.tools.configs import execute_tool, list_tools

    # List available tools
    tools = list_tools()

    # Execute a tool
    result = execute_tool("cloud_sql",
        action="create",
        instance_name="mydb",
        project_id="my-project"
    )
"""

from agent_os.tools.configs.executor import (
    ConfigExecutor,
    get_executor,
    execute_tool,
    list_tools,
    get_tool_schema
)

from agent_os.tools.configs.schema import (
    ToolConfig,
    ToolParameter,
    ParamType,
    ToolConfigRegistry
)

__all__ = [
    # Executor
    "ConfigExecutor",
    "get_executor",
    "execute_tool",
    "list_tools",
    "get_tool_schema",
    # Schema
    "ToolConfig",
    "ToolParameter",
    "ParamType",
    "ToolConfigRegistry"
]
