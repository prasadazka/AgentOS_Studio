"""
Rich formatting helpers for CLI output

Provides consistent, beautiful terminal output using Rich library.
"""

from typing import List, Dict, Any, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown

console = Console()


def format_agent_table(agents: List[Dict[str, Any]]) -> Table:
    """
    Format list of agents as a Rich table.

    Args:
        agents: List of agent dictionaries with name, model, tools, etc.

    Returns:
        Rich Table object
    """
    table = Table(title="Agents", show_header=True, header_style="bold magenta")

    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Model", style="green")
    table.add_column("Tools", style="yellow")
    table.add_column("Status", justify="center")

    for agent in agents:
        name = agent.get("name", "Unknown")
        model = agent.get("model", "gpt-4o-mini")
        tools = agent.get("tools", [])
        is_default = agent.get("is_default", False)

        tools_str = ", ".join(tools[:3])
        if len(tools) > 3:
            tools_str += f" (+{len(tools) - 3} more)"

        # Format status - DEFAULT for built-in agents, custom for user agents
        status = "[bold blue]DEFAULT[/bold blue]" if is_default else "[dim]custom[/dim]"

        table.add_row(name, model, tools_str, status)

    return table


def format_tool_table(tools: List[Dict[str, Any]]) -> Table:
    """
    Format list of tools as a Rich table.

    Args:
        tools: List of tool dictionaries

    Returns:
        Rich Table object
    """
    table = Table(title="Tools", show_header=True, header_style="bold magenta")

    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Category", style="green")
    table.add_column("Description", style="white")

    for tool in tools:
        name = tool.get("name", "Unknown")
        category = tool.get("category", "general")
        description = tool.get("description", "No description")

        # Truncate long descriptions
        if len(description) > 60:
            description = description[:57] + "..."

        table.add_row(name, category, description)

    return table


def format_workflow_table(workflows: List[Dict[str, Any]]) -> Table:
    """
    Format list of workflows as a Rich table.

    Args:
        workflows: List of workflow dictionaries

    Returns:
        Rich Table object
    """
    table = Table(title="Workflows", show_header=True, header_style="bold magenta")

    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Type", style="green")
    table.add_column("Agents", style="yellow")

    for workflow in workflows:
        name = workflow.get("name", "Unknown")
        wf_type = workflow.get("type", "chain")
        agents = workflow.get("agents", [])

        agents_str = ", ".join(agents[:3])
        if len(agents) > 3:
            agents_str += f" (+{len(agents) - 3} more)"

        table.add_row(name, wf_type, agents_str)

    return table


def format_error(message: str, suggestions: Optional[List[str]] = None) -> Panel:
    """
    Format error message with optional suggestions.

    Args:
        message: Error message
        suggestions: Optional list of recovery suggestions

    Returns:
        Rich Panel object
    """
    content = f"[red bold]Error:[/red bold] {message}"

    if suggestions:
        content += "\n\n[yellow]Suggestions:[/yellow]"
        for i, suggestion in enumerate(suggestions, 1):
            content += f"\n  {i}. {suggestion}"

    return Panel(
        content,
        title="[red]Error[/red]",
        border_style="red",
        expand=False,
    )


def format_success(message: str, details: Optional[Dict[str, Any]] = None) -> Panel:
    """
    Format success message with optional details.

    Args:
        message: Success message
        details: Optional details dictionary

    Returns:
        Rich Panel object
    """
    content = f"[green bold]✓[/green bold] {message}"

    if details:
        content += "\n\n[cyan]Details:[/cyan]"
        for key, value in details.items():
            content += f"\n  • {key}: {value}"

    return Panel(
        content,
        title="[green]Success[/green]",
        border_style="green",
        expand=False,
    )


def format_info_panel(
    title: str,
    data: Dict[str, Any],
    highlight_yaml: bool = False,
) -> Panel:
    """
    Format information panel with structured data.

    Args:
        title: Panel title
        data: Data dictionary to display
        highlight_yaml: Whether to syntax highlight as YAML

    Returns:
        Rich Panel object
    """
    if highlight_yaml:
        import yaml
        yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False)
        content = Syntax(yaml_str, "yaml", theme="monokai", line_numbers=False)
    else:
        lines = []
        for key, value in data.items():
            if isinstance(value, list):
                value_str = ", ".join(str(v) for v in value[:5])
                if len(value) > 5:
                    value_str += f" (+{len(value) - 5} more)"
            elif isinstance(value, dict):
                value_str = f"{len(value)} items"
            else:
                value_str = str(value)

            lines.append(f"[cyan]{key}:[/cyan] {value_str}")

        content = "\n".join(lines)

    return Panel(
        content,
        title=f"[bold]{title}[/bold]",
        border_style="blue",
        expand=False,
    )


def print_error(message: str, suggestions: Optional[List[str]] = None):
    """Print formatted error to console"""
    console.print(format_error(message, suggestions))


def print_success(message: str, details: Optional[Dict[str, Any]] = None):
    """Print formatted success to console"""
    console.print(format_success(message, details))


def print_info(title: str, data: Dict[str, Any], highlight_yaml: bool = False):
    """Print formatted info panel to console"""
    console.print(format_info_panel(title, data, highlight_yaml))


def print_table(table: Table):
    """Print Rich table to console"""
    console.print(table)


def print_markdown(text: str):
    """Print markdown-formatted text to console"""
    console.print(Markdown(text))
