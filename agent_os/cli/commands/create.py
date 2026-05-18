"""Interactive agent/tool/workflow creation commands"""

from typing import Optional, List, Dict, Any
from rich.console import Console

from agent_os.cli.core.config_generator import ConfigGenerator, ConfigValidationError, ProtectedResourceError
from agent_os.cli.ui.prompts import ask_text, ask_list, ask_float, ask_int, ask_confirm
from agent_os.cli.ui.formatters import format_success, format_error
from agent_os.cli.utils.validation import (
    validate_agent_name,
    validate_model_name,
    validate_temperature,
    validate_tool_names,
    validate_workflow_type,
    validate_max_iterations,
    sanitize_name,
)
from agent_os.tools.registry import ToolRegistry
from agent_os.tools.global_registry import get_global_registry

console = Console()


def create_agent_interactive(
    tool_registry: Optional[ToolRegistry] = None,
    suggested_name: Optional[str] = None,
    suggested_tools: Optional[List[str]] = None,
    description: Optional[str] = None
) -> Optional[str]:
    """
    Interactive agent creation flow with validation.

    Args:
        tool_registry: Optional tool registry
        suggested_name: Pre-filled agent name
        suggested_tools: Pre-filled tools list (can be empty for no tools)
        description: User's description of the agent's purpose (for smart prompt generation)

    Returns:
        Path to created config file, or None if cancelled
    """
    console.print("\n[bold cyan]═══ Create New Agent ═══[/bold cyan]\n")

    generator = ConfigGenerator()
    registry = tool_registry or get_global_registry()
    available_tools = registry.list_all()

    if not available_tools:
        console.print(format_error("No tools available. Please register tools first."))
        return None

    # Use suggested name or ask for it
    name = None
    if suggested_name:
        console.print(f"[dim]Suggested name:[/dim] [cyan]{suggested_name}[/cyan]")
        use_suggested = ask_confirm("Use this name?", default=True)
        if use_suggested:
            name = suggested_name

    if not name:
        while not name:
            name_input = ask_text("Agent name")
            is_valid, error_msg = validate_agent_name(name_input)
            if not is_valid:
                console.print(format_error(error_msg))
                continue
            name = name_input

    # Handle tools - use suggested or ask
    tools_input = None
    if suggested_tools is not None:
        if suggested_tools:
            # VALIDATE suggested tools against registry before showing
            valid_suggested = [t for t in suggested_tools if t in available_tools]
            invalid_suggested = [t for t in suggested_tools if t not in available_tools]

            if invalid_suggested:
                console.print(f"[yellow]Invalid tools filtered out: {', '.join(invalid_suggested)}[/yellow]")

            if valid_suggested:
                console.print(f"[dim]Suggested tools:[/dim] [cyan]{', '.join(valid_suggested)}[/cyan]")
                use_suggested = ask_confirm("Use these tools?", default=True)
                if use_suggested:
                    tools_input = ','.join(valid_suggested)
            else:
                console.print("[yellow]No valid tools in suggestions. Please select manually.[/yellow]")
        else:
            # No tools suggested (general conversational agent)
            console.print("[dim]No specific tools needed for this agent (general conversational)[/dim]")
            add_tools = ask_confirm("Add tools anyway?", default=False)
            if not add_tools:
                tools_input = ""

    if tools_input is None:
        console.print(f"\n[dim]Available tools: {', '.join(available_tools[:10])}{'...' if len(available_tools) > 10 else ''}[/dim]")
        tools = None
        while not tools:
            tools_input = ask_list("Tools to use (comma-separated)", min_items=1)
            is_valid, error_msg, invalid = validate_tool_names(tools_input, available_tools)
            if not is_valid:
                console.print(format_error(error_msg))
                continue
            tools = tools_input
    else:
        # Use pre-filled tools_input (already validated)
        if tools_input:
            tools = tools_input.split(',')
        else:
            tools = []

    # Smart defaults - only ask if user wants to customize
    model = "gpt-4o-mini"
    temperature = 0.0
    max_iterations = 15
    max_execution_time = None
    system_prompt = None

    # Generate smart system prompt, temperature, AND max_iterations based on description
    if description:
        from agent_os.cli.core.prompt_generator import generate_system_prompt_and_config

        generated_prompt, optimal_temp, optimal_iterations = generate_system_prompt_and_config(
            description,
            tools=tools if isinstance(tools, list) else []
        )

        if generated_prompt:
            system_prompt = generated_prompt
            temperature = optimal_temp  # Use AI-suggested temperature
            max_iterations = optimal_iterations  # Use AI-suggested max_iterations
            console.print(f"[dim]  ✓ AI-determined: temperature={temperature}, max_iterations={max_iterations}[/dim]")

    # Single customization question instead of 5 separate questions
    if ask_confirm("\nCustomize advanced settings?", default=False):
        # Model
        if ask_confirm("  Change model? (default: gpt-4o-mini)", default=False):
            while True:
                model_input = ask_text("    Model name", default="gpt-4o-mini")
                is_valid, error_msg = validate_model_name(model_input)
                if not is_valid:
                    console.print(format_error(error_msg))
                    continue
                model = model_input
                break

        # Temperature
        if ask_confirm("  Change temperature? (default: 0.0)", default=False):
            while True:
                temp_input = ask_float("    Temperature (0.0-2.0)", default=0.0, min_value=0.0, max_value=2.0)
                is_valid, error_msg = validate_temperature(temp_input)
                if not is_valid:
                    console.print(format_error(error_msg))
                    continue
                temperature = temp_input
                break

        # System prompt
        if ask_confirm("  Add custom system prompt?", default=False):
            system_prompt = ask_text("    System prompt")

        # Max iterations
        if ask_confirm("  Set max iterations? (default: 15)", default=False):
            while True:
                iter_input = ask_int("    Max iterations (1-50)", default=15, min_value=1, max_value=50)
                is_valid, error_msg = validate_max_iterations(iter_input)
                if not is_valid:
                    console.print(format_error(error_msg))
                    continue
                max_iterations = iter_input
                break

        # Execution timeout
        if ask_confirm("  Set execution timeout?", default=False):
            max_execution_time = ask_float("    Max execution time (seconds)", default=300.0, min_value=1.0)

    console.print("\n[bold]Configuration Summary:[/bold]")
    console.print(f"  Name: {name}")
    console.print(f"  Tools: {', '.join(tools) if tools else '(none)'}")
    console.print(f"  Model: {model}")
    console.print(f"  Temperature: {temperature} {'✓ smart' if description and system_prompt else ''}")
    if system_prompt:
        console.print(f"  System Prompt: {system_prompt[:50]}... {'✓ auto-generated' if description else ''}")
    console.print(f"  Max Iterations: {max_iterations}")

    if not ask_confirm("\nCreate this agent?", default=True):
        console.print("[yellow]Agent creation cancelled[/yellow]")
        return None

    try:
        yaml_content, file_path = generator.generate_agent_config(
            name=name,
            tools=tools,
            model=model,
            temperature=temperature,
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            max_execution_time=max_execution_time,
            dry_run=False,
        )

        # Auto-export to Python file for immediate reusability
        from agent_os.cli.commands.export import export_agent_to_python
        from pathlib import Path

        python_file = export_agent_to_python(
            agent_name=name,
            output_path=None,  # Creates folder in current directory
            tool_registry=tool_registry,
            silent=True  # Don't show separate export success message
        )

        details_dict = {
            "YAML Config": file_path,
        }

        if python_file:
            agent_folder = Path(python_file).parent
            details_dict["Project Folder"] = str(agent_folder.absolute())
            details_dict["Files"] = f"{name}.py, README.md, requirements.txt, .env.example"
            details_dict["Setup"] = f"cd {name} && cp .env.example .env"
            details_dict["Run"] = f"python {name}/{name}.py 'your query'"

        console.print(format_success(
            f"Agent '{name}' created successfully",
            details=details_dict
        ))

        return file_path

    except ProtectedResourceError as e:
        console.print(format_error(e.message))
        return None
    except ConfigValidationError as e:
        field_errors = e.get_field_errors()
        console.print(format_error("Configuration validation failed", suggestions=field_errors))
        return None
    except Exception as e:
        console.print(format_error(f"Failed to create agent: {e}"))
        return None


def create_tool_interactive() -> Optional[str]:
    """
    Interactive tool creation flow.

    Returns:
        Path to created config file, or None if cancelled
    """
    console.print("\n[bold cyan]═══ Create New Tool ═══[/bold cyan]\n")

    generator = ConfigGenerator()

    name = ask_text("Tool name (lowercase, underscores allowed)")
    name = sanitize_name(name).lower()

    module = ask_text("Python module path (e.g., agent_os.tools.library.my_tool)")
    class_name = ask_text("Tool class name (e.g., MyTool)")

    allowed_roles = None
    if ask_confirm("Restrict to specific roles?", default=False):
        allowed_roles = ask_list("Allowed roles (comma-separated)")

    console.print("\n[bold]Configuration Summary:[/bold]")
    console.print(f"  Name: {name}")
    console.print(f"  Module: {module}")
    console.print(f"  Class: {class_name}")
    if allowed_roles:
        console.print(f"  Allowed Roles: {', '.join(allowed_roles)}")

    if not ask_confirm("\nCreate this tool?", default=True):
        console.print("[yellow]Tool creation cancelled[/yellow]")
        return None

    try:
        yaml_content, file_path = generator.generate_tool_config(
            name=name,
            module=module,
            class_name=class_name,
            allowed_roles=allowed_roles,
            dry_run=False,
        )

        console.print(format_success(
            f"Tool '{name}' created successfully",
            details={"Config file": file_path}
        ))

        return file_path

    except ConfigValidationError as e:
        field_errors = e.get_field_errors()
        console.print(format_error("Configuration validation failed", suggestions=field_errors))
        return None
    except Exception as e:
        console.print(format_error(f"Failed to create tool: {e}"))
        return None


def create_workflow_interactive(available_agents: Optional[List[str]] = None) -> Optional[str]:
    """
    Interactive workflow creation flow.

    Args:
        available_agents: List of available agent names

    Returns:
        Path to created config file, or None if cancelled
    """
    console.print("\n[bold cyan]═══ Create New Workflow ═══[/bold cyan]\n")

    generator = ConfigGenerator()

    if available_agents:
        console.print(f"\n[dim]Available agents: {', '.join(available_agents)}[/dim]")

    name = None
    while not name:
        name_input = ask_text("Workflow name")
        is_valid, error_msg = validate_agent_name(name_input)
        if not is_valid:
            console.print(format_error(error_msg))
            continue
        name = name_input

    agents = ask_list("Agent names to include (comma-separated)", min_items=1)

    workflow_type = "chain"
    if ask_confirm("Customize workflow type? (default: chain)", default=False):
        while True:
            type_input = ask_text("Workflow type (chain/conditional/parallel)", default="chain")
            is_valid, error_msg = validate_workflow_type(type_input)
            if not is_valid:
                console.print(format_error(error_msg))
                continue
            workflow_type = type_input
            break

    console.print("\n[bold]Configuration Summary:[/bold]")
    console.print(f"  Name: {name}")
    console.print(f"  Agents: {', '.join(agents)}")
    console.print(f"  Type: {workflow_type}")

    if not ask_confirm("\nCreate this workflow?", default=True):
        console.print("[yellow]Workflow creation cancelled[/yellow]")
        return None

    try:
        yaml_content, file_path = generator.generate_workflow_config(
            name=name,
            agents=agents,
            workflow_type=workflow_type,
            dry_run=False,
        )

        console.print(format_success(
            f"Workflow '{name}' created successfully",
            details={"Config file": file_path}
        ))

        return file_path

    except ConfigValidationError as e:
        field_errors = e.get_field_errors()
        console.print(format_error("Configuration validation failed", suggestions=field_errors))
        return None
    except Exception as e:
        console.print(format_error(f"Failed to create workflow: {e}"))
        return None
