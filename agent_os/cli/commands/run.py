"""Direct agent execution command"""

from typing import Optional
from rich.console import Console

from agent_os.cli.core.execution_engine import ExecutionEngine, ExecutionStatus
from agent_os.cli.core.config_generator import ConfigGenerator
from agent_os.cli.ui.formatters import format_success, format_error, format_info_panel
from agent_os.cli.ui.streaming import StreamingOutput
from agent_os.agents.factory import AgentFactory
from agent_os.tools.registry import ToolRegistry

console = Console()


def run_agent_command(
    agent_name: str,
    query: str,
    tool_registry: Optional[ToolRegistry] = None,
    stream: bool = True
) -> Optional[str]:
    """
    Execute an agent with a query.

    Args:
        agent_name: Name of the agent to run
        query: Query to execute
        tool_registry: Tool registry instance
        stream: Enable streaming output

    Returns:
        Agent output, or None if execution failed
    """
    console.print(f"\n[bold cyan]Running agent: {agent_name}[/bold cyan]\n")

    generator = ConfigGenerator()

    try:
        config = generator.load_and_validate_config("agents", agent_name)
    except FileNotFoundError:
        console.print(format_error(
            f"Agent '{agent_name}' not found",
            suggestions=[
                "Run 'agent_os list agents' to see available agents",
                "Create a new agent with 'agent_os create agent'",
            ]
        ))
        return None
    except Exception as e:
        console.print(format_error(f"Failed to load agent config: {e}"))
        return None

    try:
        factory = AgentFactory(tool_registry=tool_registry)
        agent = factory.create(config)
    except Exception as e:
        console.print(format_error(
            f"Failed to initialize agent: {e}",
            suggestions=[
                "Check that all required tools are registered",
                "Verify the agent configuration file",
            ]
        ))
        return None

    engine = ExecutionEngine(enable_error_logging=True)

    if stream:
        with StreamingOutput(title=f"{agent_name}") as output:
            output.start()
            result = engine.execute(agent, query)
            if result.output:
                output.update(result.output)

        # Success - output already shown in panel
        if result.is_success():
            return result.output
    else:
        result = engine.execute(agent, query)

        # Show result in panel for non-streaming
        if result.is_success() and result.output:
            console.print(format_info_panel(
                {"Output": result.output},
                title="Result"
            ))
            return result.output

    # Handle errors
    if not result.is_success():
        console.print(format_error(
            f"Execution failed: {result.error}",
            suggestions=result.suggestions
        ))

        if result.has_partial_result():
            console.print("\n[yellow]Partial result:[/yellow]")
            console.print(result.partial_result)

        return None

    return result.output


def run_agent_batch(
    agent_name: str,
    queries: list[str],
    tool_registry: Optional[ToolRegistry] = None
) -> list[Optional[str]]:
    """
    Execute an agent with multiple queries in batch.

    Args:
        agent_name: Name of the agent to run
        queries: List of queries to execute
        tool_registry: Tool registry instance

    Returns:
        List of outputs (None for failed executions)
    """
    console.print(f"\n[bold cyan]Running agent '{agent_name}' in batch mode[/bold cyan]")
    console.print(f"[dim]Processing {len(queries)} queries...[/dim]\n")

    generator = ConfigGenerator()

    try:
        config = generator.load_and_validate_config("agents", agent_name)
        factory = AgentFactory(tool_registry=tool_registry)
        agent = factory.create(config)
    except Exception as e:
        console.print(format_error(f"Failed to initialize agent: {e}"))
        return [None] * len(queries)

    engine = ExecutionEngine(enable_error_logging=True)
    results = engine.execute_batch(agent, queries)

    outputs = []
    success_count = 0

    for i, result in enumerate(results, 1):
        console.print(f"\n[bold]Query {i}/{len(queries)}:[/bold] {queries[i-1][:80]}...")

        if result.is_success():
            console.print(f"[green]✓ Success[/green]")
            outputs.append(result.output)
            success_count += 1
        else:
            console.print(f"[red]✗ Failed: {result.error}[/red]")
            outputs.append(None)

    console.print(f"\n[bold]Batch execution complete:[/bold] {success_count}/{len(queries)} succeeded")

    return outputs