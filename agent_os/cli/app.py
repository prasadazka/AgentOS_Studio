"""Main CLI application using Typer"""

import sys
import os

# Fix Windows console encoding before any output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import typer
from typing import Optional, List
from pathlib import Path
from rich.console import Console
from dotenv import load_dotenv

# Load .env file from current directory or parent directories
load_dotenv()

# Lazy imports for fast startup - modules imported only when command is called
# from agent_os.cli.commands.create import ...
# from agent_os.cli.commands.run import ...
# from agent_os.cli.commands.list import ...
# from agent_os.cli.commands.info import ...
# from agent_os.cli.commands.chat import ...

from agent_os.cli.utils.session import ensure_agent_os_directories
from agent_os.cli.utils.error_handlers import graceful_error_handler
from agent_os.cli.utils.completions import (
    complete_agent_name,
    complete_tool_name,
    complete_workflow_name,
    complete_resource_type,
)

app = typer.Typer(
    name="agent_os",
    help="AgentOS - Production-grade AI agent framework with conversational interface",
    add_completion=True,  # Enable shell completion
)

console = Console()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """AgentOS CLI - Build and run AI agents with minimal code"""
    ensure_agent_os_directories()

    if ctx.invoked_subcommand is None:
        from agent_os.cli.commands.chat import start_chat_repl
        start_chat_repl(session_id=None)


@app.command()
@graceful_error_handler(log_file=Path.home() / ".agent_os" / "errors.log")
def create(
    resource_type: str = typer.Argument(
        ...,
        help="Type of resource to create (agent/tool/workflow)",
        autocompletion=lambda: ["agent", "tool", "workflow"]
    ),
):
    """
    Create a new agent, tool, or workflow interactively.

    Examples:
        agent_os create agent
        agent_os create tool
        agent_os create workflow
    """
    from agent_os.cli.commands.create import (
        create_agent_interactive,
        create_tool_interactive,
        create_workflow_interactive,
    )

    resource_type = resource_type.lower()

    if resource_type == "agent":
        create_agent_interactive()
    elif resource_type == "tool":
        create_tool_interactive()
    elif resource_type == "workflow":
        create_workflow_interactive()
    else:
        console.print(f"[red]Unknown resource type: {resource_type}[/red]")
        console.print("Valid types: agent, tool, workflow")
        raise typer.Exit(1)


@app.command()
@graceful_error_handler(log_file=Path.home() / ".agent_os" / "errors.log")
def run(
    agent_name: str = typer.Argument(..., help="Name of the agent to run", autocompletion=complete_agent_name),
    query: str = typer.Argument(..., help="Query to execute"),
    stream: bool = typer.Option(True, "--stream/--no-stream", help="Enable streaming output"),
):
    """
    Run an agent with a query.

    Examples:
        agent_os run researcher "Find papers on RAG"
        agent_os run sql_agent "Show top 10 products" --no-stream
    """
    from agent_os.cli.commands.run import run_agent_command
    from agent_os.tools.global_registry import get_global_registry

    registry = get_global_registry()
    run_agent_command(agent_name, query, tool_registry=registry, stream=stream)


@app.command()
@graceful_error_handler(log_file=Path.home() / ".agent_os" / "errors.log")
def batch(
    agent_name: str = typer.Argument(..., help="Name of the agent to run", autocompletion=complete_agent_name),
    queries: List[str] = typer.Argument(..., help="Queries to execute (space-separated)"),
):
    """
    Run an agent with multiple queries in batch mode.

    Examples:
        agent_os batch researcher "Query 1" "Query 2" "Query 3"
    """
    from agent_os.cli.commands.run import run_agent_batch
    from agent_os.tools.global_registry import get_global_registry

    registry = get_global_registry()
    run_agent_batch(agent_name, queries, tool_registry=registry)


@app.command(name="list")
@graceful_error_handler(log_file=Path.home() / ".agent_os" / "errors.log")
def list_cmd(
    resource_type: Optional[str] = typer.Argument(
        None,
        help="Type of resource (agents/tools/workflows/sessions)",
        autocompletion=lambda: ["agents", "tools", "workflows", "sessions"]
    ),
):
    """
    List resources. If no type specified, lists all.

    Examples:
        agent_os list
        agent_os list agents
        agent_os list tools
        agent_os list workflows
        agent_os list sessions
    """
    from agent_os.cli.commands.list import list_resources, list_all_resources
    from agent_os.tools.global_registry import get_global_registry

    registry = get_global_registry()

    if resource_type:
        list_resources(resource_type.lower(), tool_registry=registry)
    else:
        list_all_resources(tool_registry=registry)


@app.command()
@graceful_error_handler(log_file=Path.home() / ".agent_os" / "errors.log")
def info(
    resource_type: str = typer.Argument(
        ...,
        help="Type of resource (agent/tool/workflow)",
        autocompletion=lambda: ["agent", "tool", "workflow"]
    ),
    resource_name: str = typer.Argument(..., help="Name of the resource"),
):
    """
    Show detailed information about a resource.

    Examples:
        agent_os info agent researcher
        agent_os info tool wikipedia_search
        agent_os info workflow data_pipeline
    """
    from agent_os.cli.commands.info import show_resource_info
    from agent_os.tools.global_registry import get_global_registry

    registry = get_global_registry()
    show_resource_info(resource_type.lower(), resource_name, tool_registry=registry)


@app.command()
@graceful_error_handler(log_file=Path.home() / ".agent_os" / "errors.log")
def delete(
    resource_type: str = typer.Argument(
        ...,
        help="Type of resource (agent/tool/workflow)",
        autocompletion=lambda: ["agent", "tool", "workflow"]
    ),
    resource_name: str = typer.Argument(..., help="Name of the resource to delete"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """
    Delete a resource.

    Examples:
        agent_os delete agent old_agent
        agent_os delete tool unused_tool --yes
    """
    from agent_os.cli.core.config_generator import ConfigGenerator
    from agent_os.cli.ui.prompts import ask_confirm

    resource_type = resource_type.lower()
    config_type_map = {
        "agent": "agents",
        "tool": "tools",
        "workflow": "workflows",
    }

    if resource_type not in config_type_map:
        console.print(f"[red]Unknown resource type: {resource_type}[/red]")
        console.print("Valid types: agent, tool, workflow")
        raise typer.Exit(1)

    config_type = config_type_map[resource_type]

    if not confirm:
        confirm = ask_confirm(
            f"Are you sure you want to delete {resource_type} '{resource_name}'?",
            default=False
        )

    if not confirm:
        console.print("[yellow]Delete cancelled[/yellow]")
        return

    from agent_os.cli.core.config_generator import ProtectedResourceError

    generator = ConfigGenerator()

    try:
        success = generator.delete_config(config_type, resource_name)

        if success:
            console.print(f"[green]✓ {resource_type.title()} '{resource_name}' deleted successfully[/green]")
        else:
            console.print(f"[red]✗ {resource_type.title()} '{resource_name}' not found[/red]")
            raise typer.Exit(1)

    except ProtectedResourceError as e:
        console.print(f"[red]✗ {e.message}[/red]")
        raise typer.Exit(1)


@app.command()
@graceful_error_handler(log_file=Path.home() / ".agent_os" / "errors.log")
def export(
    agent_name: str = typer.Argument(..., help="Name of the agent to export", autocompletion=complete_agent_name),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
    as_class: bool = typer.Option(False, "--class", "-c", help="Export as reusable class"),
):
    """
    Export agent to Python code.

    Examples:
        agent_os export ChatAgent
        agent_os export ChatAgent --output my_agent.py
        agent_os export ChatAgent --class
    """
    from agent_os.cli.commands.export import export_agent_to_python, export_agent_as_class
    from agent_os.tools.global_registry import get_global_registry

    registry = get_global_registry()

    if as_class:
        export_agent_as_class(agent_name, output_path=output, tool_registry=registry)
    else:
        export_agent_to_python(agent_name, output_path=output, tool_registry=registry)


@app.command()
@graceful_error_handler(log_file=Path.home() / ".agent_os" / "errors.log")
def chat(
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Resume existing session by ID"),
):
    """
    Start interactive chat REPL for conversational agent management.

    Examples:
        agent_os chat
        agent_os chat --session abc123
    """
    from agent_os.cli.commands.chat import start_chat_repl
    start_chat_repl(session_id=session_id)


@app.command()
def install_completion(
    shell: Optional[str] = typer.Option(
        None,
        help="Shell type (bash/zsh/fish/powershell). Auto-detected if not specified."
    ),
):
    """
    Install shell completion for AgentOS CLI.

    After running this, restart your shell or source your shell config file.

    Examples:
        agent_os install-completion
        agent_os install-completion --shell bash
        agent_os install-completion --shell zsh
    """
    import subprocess
    import sys

    # Auto-detect shell if not specified
    if shell is None:
        shell_env = Path.home() / ".bashrc"
        if (Path.home() / ".zshrc").exists():
            shell = "zsh"
        elif shell_env.exists():
            shell = "bash"
        elif sys.platform == "win32":
            shell = "powershell"
        else:
            shell = "bash"

    console.print(f"[cyan]Installing tab completion for {shell}...[/cyan]")

    try:
        # Generate completion script
        result = subprocess.run(
            [sys.executable, "-m", "agent_os.cli.app", "--show-completion", shell],
            capture_output=True,
            text=True,
            check=True
        )

        completion_script = result.stdout

        # Determine config file
        config_files = {
            "bash": Path.home() / ".bashrc",
            "zsh": Path.home() / ".zshrc",
            "fish": Path.home() / ".config" / "fish" / "completions" / "agent_os.fish",
            "powershell": Path.home() / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
        }

        config_file = config_files.get(shell)

        if config_file and shell != "fish":
            # For bash/zsh, append to config file
            with open(config_file, "a") as f:
                f.write(f"\n# AgentOS completion\n")
                f.write(completion_script)

            console.print(f"[green]✓ Completion installed to {config_file}[/green]")
            console.print(f"\n[yellow]Please restart your shell or run:[/yellow]")
            console.print(f"  source {config_file}")
        elif shell == "fish":
            # For fish, write to completions directory
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(completion_script)
            console.print(f"[green]✓ Completion installed to {config_file}[/green]")
            console.print(f"[yellow]Completion will be available in new fish sessions[/yellow]")
        else:
            console.print("[yellow]Completion script:[/yellow]")
            console.print(completion_script)
            console.print("\n[yellow]Please add the above to your shell config manually[/yellow]")

    except Exception as e:
        console.print(f"[red]✗ Failed to install completion: {e}[/red]")
        console.print("\n[yellow]Alternative: Run the following command manually:[/yellow]")
        console.print(f"  agent_os --show-completion {shell}")
        raise typer.Exit(1)


@app.command()
def version():
    """Show AgentOS version"""
    console.print("[bold cyan]AgentOS v0.1.0[/bold cyan]")
    console.print("Production-grade AI agent framework")


def cli():
    """Entry point for CLI"""
    app()


if __name__ == "__main__":
    cli()
