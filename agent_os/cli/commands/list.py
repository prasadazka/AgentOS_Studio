"""List resources (agents, tools, workflows, sessions) command"""

from typing import Optional, List, Dict, Any
from pathlib import Path
from rich.console import Console

from agent_os.cli.core.config_generator import ConfigGenerator
from agent_os.cli.ui.formatters import format_agent_table, format_tool_table, format_error
from agent_os.cli.utils.session import ensure_agent_os_directories, get_session_path
from agent_os.tools.registry import ToolRegistry
from agent_os.tools.global_registry import get_global_registry

console = Console()


def list_resources(
    resource_type: str,
    tool_registry: Optional[ToolRegistry] = None
) -> List[Dict[str, Any]]:
    """
    List resources of a specific type.

    Args:
        resource_type: Type of resource ('agents', 'tools', 'workflows', 'sessions')
        tool_registry: Tool registry instance (for listing tools)

    Returns:
        List of resource dictionaries
    """
    console.print(f"\n[bold cyan]═══ {resource_type.title()} ═══[/bold cyan]\n")

    if resource_type == "agents":
        return _list_agents()
    elif resource_type == "tools":
        return _list_tools(tool_registry)
    elif resource_type == "workflows":
        return _list_workflows()
    elif resource_type == "sessions":
        return _list_sessions()
    else:
        console.print(format_error(
            f"Unknown resource type: {resource_type}",
            suggestions=["Valid types: agents, tools, workflows, sessions"]
        ))
        return []


def _list_agents() -> List[Dict[str, Any]]:
    """List all agent configurations (including defaults)"""
    generator = ConfigGenerator()

    # Use list_configs_with_metadata to get is_default info
    agents = generator.list_configs_with_metadata("agents")

    if not agents:
        console.print("[yellow]No agents found. Create one with 'agent_os create agent'[/yellow]")
        return []

    if agents:
        table = format_agent_table(agents)
        console.print(table)

        # Count defaults vs custom
        default_count = sum(1 for a in agents if a.get("is_default"))
        custom_count = len(agents) - default_count
        console.print(f"\n[dim]Total: {len(agents)} agent(s) ({default_count} default, {custom_count} custom)[/dim]")

    return agents


def _list_tools(tool_registry: Optional[ToolRegistry]) -> List[Dict[str, Any]]:
    """List all registered tools"""
    if not tool_registry:
        tool_registry = get_global_registry()

    tool_names = tool_registry.list_all()

    if not tool_names:
        console.print("[yellow]No tools registered[/yellow]")
        return []

    tools = []
    for name in tool_names:
        tool = tool_registry.get(name)
        if tool:
            tools.append({
                "name": tool.metadata.name,
                "category": tool.metadata.category,
                "description": tool.metadata.description,
                "version": tool.metadata.version,
                "requires_auth": tool.metadata.requires_auth,
            })

    if tools:
        table = format_tool_table(tools)
        console.print(table)
        console.print(f"\n[dim]Total: {len(tools)} tool(s)[/dim]")

    return tools


def _list_workflows() -> List[Dict[str, Any]]:
    """List all workflow configurations"""
    generator = ConfigGenerator()
    workflow_names = generator.list_configs("workflows")

    if not workflow_names:
        console.print("[yellow]No workflows found. Create one with 'agent_os create workflow'[/yellow]")
        return []

    workflows = []
    for name in workflow_names:
        try:
            config = generator.load_and_validate_config("workflows", name)
            workflows.append(config)
        except Exception as e:
            console.print(f"[dim red]Warning: Failed to load workflow '{name}': {e}[/dim red]")

    if workflows:
        from rich.table import Table

        table = Table(title="Workflows", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Type", style="green")
        table.add_column("Agents", style="yellow")

        for workflow in workflows:
            agents_str = ", ".join(workflow.get("agents", [])[:3])
            if len(workflow.get("agents", [])) > 3:
                agents_str += f" (+{len(workflow['agents']) - 3} more)"

            table.add_row(
                workflow["name"],
                workflow.get("type", "chain"),
                agents_str
            )

        console.print(table)
        console.print(f"\n[dim]Total: {len(workflows)} workflow(s)[/dim]")

    return workflows


def _list_sessions() -> List[Dict[str, Any]]:
    """List all conversation sessions"""
    directories = ensure_agent_os_directories()
    sessions_dir = directories["sessions"]

    session_files = list(sessions_dir.glob("*.json"))

    if not session_files:
        console.print("[yellow]No conversation sessions found[/yellow]")
        return []

    from rich.table import Table
    import json
    from datetime import datetime

    table = Table(title="Sessions", show_header=True, header_style="bold magenta")
    table.add_column("Session ID", style="cyan")
    table.add_column("Messages", justify="right", style="green")
    table.add_column("Created", style="yellow")
    table.add_column("Updated", style="yellow")

    sessions = []
    for session_file in sorted(session_files, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                session_data = json.load(f)

            session_id = session_data.get("session_id", session_file.stem)
            message_count = len(session_data.get("messages", []))
            created = session_data.get("created_at", "Unknown")
            updated = session_data.get("updated_at", "Unknown")

            if isinstance(created, str) and created != "Unknown":
                created = datetime.fromisoformat(created).strftime("%Y-%m-%d %H:%M")
            if isinstance(updated, str) and updated != "Unknown":
                updated = datetime.fromisoformat(updated).strftime("%Y-%m-%d %H:%M")

            table.add_row(session_id, str(message_count), created, updated)

            sessions.append({
                "session_id": session_id,
                "message_count": message_count,
                "created_at": created,
                "updated_at": updated,
            })

        except Exception as e:
            console.print(f"[dim red]Warning: Failed to read session '{session_file.name}': {e}[/dim red]")

    console.print(table)
    console.print(f"\n[dim]Total: {len(sessions)} session(s)[/dim]")

    return sessions


def list_all_resources(tool_registry: Optional[ToolRegistry] = None):
    """List all resources (agents, tools, workflows)"""
    list_resources("agents", tool_registry)
    console.print()
    list_resources("tools", tool_registry)
    console.print()
    list_resources("workflows", tool_registry)
