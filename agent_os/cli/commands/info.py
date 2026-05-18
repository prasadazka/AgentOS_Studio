"""Show detailed information about resources command"""

from typing import Optional
from rich.console import Console

from agent_os.cli.core.config_generator import ConfigGenerator
from agent_os.cli.ui.formatters import format_info_panel, format_error
from agent_os.tools.registry import ToolRegistry
from agent_os.tools.global_registry import get_global_registry

console = Console()


def show_resource_info(
    resource_type: str,
    resource_name: str,
    tool_registry: Optional[ToolRegistry] = None
) -> Optional[dict]:
    """
    Show detailed information about a resource.

    Args:
        resource_type: Type of resource ('agent', 'tool', 'workflow')
        resource_name: Name of the resource
        tool_registry: Tool registry instance (for tool info)

    Returns:
        Resource details dictionary, or None if not found
    """
    console.print(f"\n[bold cyan]═══ {resource_type.title()} Info: {resource_name} ═══[/bold cyan]\n")

    if resource_type == "agent":
        return _show_agent_info(resource_name)
    elif resource_type == "tool":
        return _show_tool_info(resource_name, tool_registry)
    elif resource_type == "workflow":
        return _show_workflow_info(resource_name)
    else:
        console.print(format_error(
            f"Unknown resource type: {resource_type}",
            suggestions=["Valid types: agent, tool, workflow"]
        ))
        return None


def _show_agent_info(agent_name: str) -> Optional[dict]:
    """Show detailed agent information"""
    generator = ConfigGenerator()

    try:
        config = generator.load_and_validate_config("agents", agent_name)
    except FileNotFoundError:
        console.print(format_error(
            f"Agent '{agent_name}' not found",
            suggestions=["Run 'agent_os list agents' to see available agents"]
        ))
        return None
    except Exception as e:
        console.print(format_error(f"Failed to load agent: {e}"))
        return None

    info = {
        "Name": config["name"],
        "Model": config["model"],
        "Temperature": config.get("temperature", 0.0),
        "Tools": ", ".join(config["tools"]),
    }

    if "system_prompt" in config:
        prompt_preview = config["system_prompt"][:100]
        if len(config["system_prompt"]) > 100:
            prompt_preview += "..."
        info["System Prompt"] = prompt_preview

    if "max_iterations" in config:
        info["Max Iterations"] = config["max_iterations"]

    if "max_execution_time" in config:
        info["Max Execution Time"] = f"{config['max_execution_time']}s"

    if "memory" in config:
        info["Memory Config"] = str(config["memory"])

    panel = format_info_panel(info, title=f"Agent: {agent_name}", show_yaml=True)
    console.print(panel)

    return config


def _show_tool_info(tool_name: str, tool_registry: Optional[ToolRegistry]) -> Optional[dict]:
    """Show detailed tool information"""
    if not tool_registry:
        tool_registry = get_global_registry()

    tool = tool_registry.get(tool_name)

    if not tool:
        console.print(format_error(
            f"Tool '{tool_name}' not found",
            suggestions=["Run 'agent_os list tools' to see available tools"]
        ))
        return None

    info = {
        "Name": tool.metadata.name,
        "Category": tool.metadata.category,
        "Description": tool.metadata.description,
        "Version": tool.metadata.version,
        "Requires Auth": "Yes" if tool.metadata.requires_auth else "No",
    }

    generator = ConfigGenerator()
    try:
        config = generator.load_and_validate_config("tools", tool_name)
        if "module" in config:
            info["Module"] = config["module"]
        if "class_name" in config:
            info["Class"] = config["class_name"]
        if "allowed_roles" in config:
            info["Allowed Roles"] = ", ".join(config["allowed_roles"])
    except:
        pass

    panel = format_info_panel(info, title=f"Tool: {tool_name}")
    console.print(panel)

    return {
        "name": tool.metadata.name,
        "category": tool.metadata.category,
        "description": tool.metadata.description,
        "version": tool.metadata.version,
        "requires_auth": tool.metadata.requires_auth,
    }


def _show_workflow_info(workflow_name: str) -> Optional[dict]:
    """Show detailed workflow information"""
    generator = ConfigGenerator()

    try:
        config = generator.load_and_validate_config("workflows", workflow_name)
    except FileNotFoundError:
        console.print(format_error(
            f"Workflow '{workflow_name}' not found",
            suggestions=["Run 'agent_os list workflows' to see available workflows"]
        ))
        return None
    except Exception as e:
        console.print(format_error(f"Failed to load workflow: {e}"))
        return None

    info = {
        "Name": config["name"],
        "Type": config.get("type", "chain"),
        "Agents": ", ".join(config["agents"]),
    }

    if "routing" in config:
        info["Routing"] = str(config["routing"])

    if "memory" in config:
        info["Memory Config"] = str(config["memory"])

    panel = format_info_panel(info, title=f"Workflow: {workflow_name}", show_yaml=True)
    console.print(panel)

    return config
