"""Interactive chat REPL for conversational agent management"""

import os
import time
from typing import Optional, List
from pathlib import Path
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.live import Live
from rich.spinner import Spinner
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML

from agent_os.cli.core.conversation_manager import ConversationManager
from agent_os.cli.core.intent_parser import IntentParser, IntentAction, create_intent_parser
from agent_os.cli.core.config_generator import ConfigGenerator
from agent_os.cli.core.execution_engine import ExecutionEngine
from agent_os.cli.core.agent_activation import AgentActivationManager
from agent_os.cli.agents.activated_agent import ActivatedAgent, DestructiveOperationRequest
from agent_os.cli.commands.create import (
    create_agent_interactive,
    create_tool_interactive,
    create_workflow_interactive,
)
from agent_os.cli.commands.run import run_agent_command
from agent_os.cli.commands.list import list_all_resources, list_resources
from agent_os.cli.commands.info import show_resource_info
from agent_os.cli.commands.deploy import (
    deploy_command,
    analyze_project_command,
    get_conversational_deployer,
    handle_deployment_message,
)
from agent_os.cli.ui.formatters import format_success, format_error, format_info_panel
from agent_os.cli.utils.session import ensure_agent_os_directories
from agent_os.tools.global_registry import get_global_registry

console = Console()
logger = structlog.get_logger()


class ChatREPL:
    """Interactive chat REPL for AgentOS"""

    SPECIAL_COMMANDS = {
        "/help": "Show help message",
        "/list": "List all resources",
        "/agents": "List agents",
        "/tools": "List tools",
        "/workflows": "List workflows",
        "/sessions": "List conversation sessions",
        "/pwd": "Show current working directory",
        "/cd": "Change working directory (usage: /cd <path>)",
        "/activate": "Activate agent mode (usage: /activate DataAnalyst)",
        "/deactivate": "Exit agent mode and return to normal",
        "/status": "Show current activation status",
        "/refresh": "Refresh discovered files in activated mode",
        "/deploy": "Deploy application to cloud (usage: /deploy [target])",
        "/analyze": "Analyze project tech stack (usage: /analyze [path])",
        "/quit": "Exit chat",
        "/exit": "Exit chat",
        "/clear": "Clear screen",
        "/history": "Show conversation history",
    }

    def __init__(self, session_id: Optional[str] = None):
        """
        Initialize chat REPL.

        Args:
            session_id: Resume existing session (None creates new)
        """
        ensure_agent_os_directories()

        # Check for OpenAI API key
        if not os.getenv("OPENAI_API_KEY"):
            self._show_api_key_setup()
            raise SystemExit(0)

        # Capture current working directory
        self.working_directory = Path.cwd()

        self.conversation_manager = ConversationManager(session_id=session_id)
        self.intent_parser = create_intent_parser()
        self.config_generator = ConfigGenerator()
        self.execution_engine = ExecutionEngine(enable_error_logging=True)
        self.tool_registry = get_global_registry()

        history_file = Path.home() / ".agent_os" / "history"
        self.prompt_session = PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
        )

        self.running = False

        # Agent activation state
        self.activation_manager = AgentActivationManager(
            working_directory=self.working_directory,
            tool_registry=self.tool_registry,
        )
        self.activated_agent: Optional[ActivatedAgent] = None

        # Deployment conversation state
        self._deployment_conversation_active = False

        # Try to restore activation state from previous session
        self._restore_activation_state()

    def start(self):
        """Start the interactive chat loop"""
        self._show_welcome()

        if self.conversation_manager.session.messages:
            console.print(f"\n[dim]Resumed session: {self.conversation_manager.session.session_id}[/dim]")
            console.print(f"[dim]Message count: {len(self.conversation_manager.session.messages)}[/dim]\n")

        self.running = True

        while self.running:
            try:
                # Dynamic prompt based on activation state
                prompt_message = self._get_prompt_message()
                user_input = self.prompt_session.prompt(prompt_message)

                if not user_input.strip():
                    continue

                if user_input.startswith("/"):
                    self._handle_special_command(user_input)
                    continue

                self.conversation_manager.add_message("user", user_input)

                # Route through activated agent if active
                if self.activation_manager.is_activated() and self.activated_agent:
                    self._execute_with_activated_agent(user_input)
                else:
                    self._process_user_input(user_input)

            except KeyboardInterrupt:
                if self._confirm_exit():
                    break
            except EOFError:
                break
            except Exception as e:
                console.print(format_error(f"Error: {e}"))

        self._show_goodbye()

    def _show_welcome(self):
        """Show compact welcome message with border"""
        from rich.text import Text

        content = Text()
        content.append("/activate DataAnalyst", style="green")
        content.append("  ", style="dim")
        content.append("/activate Developer", style="green")
        content.append("  ", style="dim")
        content.append("/activate Researcher", style="green")
        content.append("\n")
        content.append("/help  /list  /agents  /tools  /quit", style="yellow")
        content.append("  or type naturally", style="dim")

        console.print()
        console.print(Panel(
            content,
            title="[bold cyan]AgentOS Chat[/bold cyan]",
            subtitle=Text(str(self.working_directory), style="dim"),
            border_style="cyan",
            padding=(0, 1)
        ))

    def _show_goodbye(self):
        """Show goodbye message"""
        console.print("\n[cyan]Thanks for using AgentOS! Your session has been saved.[/cyan]")
        console.print(f"[dim]Session ID: {self.conversation_manager.session.session_id}[/dim]\n")

    def _show_api_key_setup(self):
        """Show API key setup instructions"""
        setup_text = """
# OpenAI API Key Required

AgentOS needs an OpenAI API key to understand and process your natural language commands.

**How to Set Up:**

**Option 1: Set Environment Variable (Recommended)**
```bash
# Windows (PowerShell)
$env:OPENAI_API_KEY="sk-your-api-key-here"

# Windows (Command Prompt)
set OPENAI_API_KEY=sk-your-api-key-here

# Linux/Mac
export OPENAI_API_KEY=sk-your-api-key-here
```

**Option 2: Create .env File**
1. Create a file named `.env` in your current directory
2. Add this line: `OPENAI_API_KEY=sk-your-api-key-here`

**Get Your API Key:**
- Visit https://platform.openai.com/api-keys
- Sign in or create an account
- Click "Create new secret key"
- Copy the key and set it using one of the options above

**Then run `agent_os` again to start chatting!**
        """
        console.print(Panel(Markdown(setup_text), title="[bold yellow]Setup Required[/bold yellow]", border_style="yellow"))

    def _handle_special_command(self, command: str):
        """Handle special commands starting with /"""
        command_lower = command.lower().split()[0]

        if command_lower in ["/quit", "/exit"]:
            self.running = False

        elif command_lower == "/help":
            self._show_help()

        elif command_lower == "/list":
            list_all_resources(tool_registry=self.tool_registry)

        elif command_lower == "/agents":
            list_resources("agents", tool_registry=self.tool_registry)

        elif command_lower == "/tools":
            list_resources("tools", tool_registry=self.tool_registry)

        elif command_lower == "/workflows":
            list_resources("workflows", tool_registry=self.tool_registry)

        elif command_lower == "/sessions":
            list_resources("sessions", tool_registry=self.tool_registry)

        elif command_lower == "/clear":
            console.clear()
            self._show_welcome()

        elif command_lower == "/history":
            self._show_history()

        elif command_lower == "/pwd":
            console.print(f"\n[cyan]Current working directory:[/cyan] [bold]{self.working_directory}[/bold]\n")

        elif command_lower == "/cd":
            self._change_directory(command)

        elif command_lower == "/activate":
            self._handle_activate_command(command)

        elif command_lower == "/deactivate":
            self._handle_deactivate_command()

        elif command_lower == "/status":
            self._show_activation_status()

        elif command_lower == "/refresh":
            self._refresh_discovered_files()

        elif command_lower == "/deploy":
            self._handle_deploy_command(command)

        elif command_lower == "/analyze":
            self._handle_analyze_command(command)

        else:
            console.print(format_error(
                f"Unknown command: {command}",
                suggestions=[f"Type /help to see available commands"]
            ))

    def _show_help(self):
        """Show help message"""
        help_text = "**Available Commands:**\n\n"
        for cmd, desc in self.SPECIAL_COMMANDS.items():
            help_text += f"- `{cmd}` - {desc}\n"

        help_text += "\n**Agent Activation Mode:**\n\n"
        help_text += "Activate an agent to work with files in your current directory:\n"
        help_text += "- `/activate DataAnalyst` - Analyze CSV, JSON, Excel files\n"
        help_text += "- `/activate Developer` - Work with code and git operations\n"
        help_text += "- `/activate Researcher` - Search Wikipedia and ArXiv\n"
        help_text += "- `/deactivate` - Return to normal mode\n"

        help_text += "\n**Deployment Commands:**\n\n"
        help_text += "- `/deploy` - Deploy to Cloud Run (default)\n"
        help_text += "- `/deploy app_engine` - Deploy to App Engine\n"
        help_text += "- `/analyze` - Analyze project tech stack\n"
        help_text += "- \"Deploy my app to GCP\" - Natural language deployment\n"

        help_text += "\n**Natural Language Examples:**\n\n"
        help_text += "- \"Create a research agent with Wikipedia and ArXiv tools\"\n"
        help_text += "- \"Run my researcher agent to find papers on RAG systems\"\n"
        help_text += "- \"Deploy my app to Cloud Run\"\n"
        help_text += "- \"Analyze this project\"\n"
        help_text += "- \"List all my agents\"\n"

        console.print(Panel(Markdown(help_text), title="[bold cyan]Help[/bold cyan]", border_style="cyan"))

    def _show_history(self):
        """Show conversation history"""
        messages = self.conversation_manager.get_recent_messages(limit=10)

        if not messages:
            console.print("[yellow]No conversation history[/yellow]")
            return

        console.print("\n[bold cyan]Recent Conversation:[/bold cyan]\n")

        for msg in messages:
            role_color = "green" if msg.role == "user" else "blue"
            console.print(f"[{role_color}]{msg.role.upper()}:[/{role_color}] {msg.content[:100]}...")

        if len(self.conversation_manager.session.messages) > 10:
            console.print(f"\n[dim]Showing last 10 of {len(self.conversation_manager.session.messages)} messages[/dim]")

    def _change_directory(self, command: str):
        """Change working directory"""
        parts = command.split(maxsplit=1)

        if len(parts) < 2:
            console.print(format_error(
                "Usage: /cd <path>",
                suggestions=["Example: /cd C:\\Projects\\MyProject", "Example: /cd ../data"]
            ))
            return

        new_path = Path(parts[1]).expanduser()

        # Try relative path from current working directory first
        if not new_path.is_absolute():
            new_path = self.working_directory / new_path

        try:
            new_path = new_path.resolve()

            if not new_path.exists():
                console.print(format_error(
                    f"Directory does not exist: {new_path}",
                    suggestions=["Check the path and try again", "Use /pwd to see current directory"]
                ))
                return

            if not new_path.is_dir():
                console.print(format_error(
                    f"Not a directory: {new_path}",
                    suggestions=["Provide a directory path, not a file"]
                ))
                return

            # Change working directory
            os.chdir(new_path)
            self.working_directory = new_path

            console.print(format_success(
                f"Changed working directory to: {self.working_directory}",
                details={"Directory": str(self.working_directory)}
            ))

        except Exception as e:
            console.print(format_error(
                f"Failed to change directory: {e}",
                suggestions=["Check permissions", "Verify the path exists"]
            ))

    def _handle_deploy_command(self, command: str):
        """Handle /deploy command"""
        parts = command.split(maxsplit=1)
        target = parts[1] if len(parts) > 1 else "cloud_run"

        console.print(f"\n[bold cyan]🚀 Deploying to {target}...[/bold cyan]\n")

        try:
            result = deploy_command(
                project_path=str(self.working_directory),
                target=target,
                region="us-central1",
                push_to_git=True,
                env_file=".env",
            )

            if result.get("success"):
                console.print(format_success(
                    f"Deployment successful!",
                    details={"Endpoint": result.get("endpoint_url", "N/A")}
                ))
            else:
                console.print(format_error(f"Deployment failed: {result.get('error', 'Unknown error')}"))

        except Exception as e:
            console.print(format_error(f"Deployment failed: {e}"))

    def _handle_analyze_command(self, command: str):
        """Handle /analyze command"""
        parts = command.split(maxsplit=1)
        project_path = parts[1] if len(parts) > 1 else str(self.working_directory)

        console.print(f"\n[bold cyan]🔍 Analyzing project at {project_path}...[/bold cyan]\n")

        try:
            result = analyze_project_command(project_path=project_path)

            if result:
                console.print(format_success(
                    f"Analysis complete!",
                    details={
                        "Language": result.get("language", "Unknown"),
                        "Framework": result.get("framework", "Unknown"),
                        "Dependencies": str(result.get("dependencies_count", 0)),
                    }
                ))
            else:
                console.print("[yellow]Analysis complete. No specific tech stack detected.[/yellow]")

        except Exception as e:
            console.print(format_error(f"Analysis failed: {e}"))

    def _get_prompt_prefix(self) -> str:
        """Get dynamic prompt prefix based on activation state (plain text)"""
        if self.activation_manager.is_activated():
            agent_name = self.activation_manager.get_active_agent_name()
            return f"[{agent_name}]"
        return "[You]"

    def _get_prompt_message(self):
        """Get formatted prompt message for prompt_toolkit"""
        if self.activation_manager.is_activated():
            agent_name = self.activation_manager.get_active_agent_name()
            # Use prompt_toolkit HTML formatting for colors
            return HTML(f'\n<ansigreen><b>[{agent_name}]</b></ansigreen> &gt; ')
        return "\n[You] > "

    def _restore_activation_state(self):
        """Restore activation state from previous session"""
        try:
            saved_state = self.conversation_manager.load_activation_state()
            if saved_state and saved_state.get("is_activated"):
                agent_name = saved_state.get("agent_name")
                if agent_name:
                    # Check if working directory matches
                    saved_dir = saved_state.get("working_directory", "")
                    if str(self.working_directory) == saved_dir:
                        # Restore activation
                        if self.activation_manager.restore_state(saved_state):
                            # Recreate activated agent
                            self.activated_agent = ActivatedAgent(
                                agent_name=agent_name,
                                discovered_files=self.activation_manager.state.discovered_files,
                                working_directory=self.working_directory,
                                tool_registry=self.tool_registry,
                                safety_mode=True,
                                confirmation_callback=self._confirm_destructive_operation,
                            )
                            logger.info(f"Restored activation state for agent '{agent_name}'")
                    else:
                        # Different directory - clear stale state
                        self.conversation_manager.clear_activation_state()
        except Exception as e:
            logger.warning(f"Failed to restore activation state: {e}")
            self.conversation_manager.clear_activation_state()

    def _handle_activate_command(self, command: str):
        """Handle /activate command"""
        parts = command.split(maxsplit=1)

        if len(parts) < 2:
            console.print(format_error(
                "Usage: /activate <agent_name>",
                suggestions=[
                    "Example: /activate DataAnalyst",
                    "Example: /activate Developer",
                    "Use /agents to see available agents"
                ]
            ))
            return

        agent_name = parts[1].strip()

        # Check if already activated
        if self.activation_manager.is_activated():
            current = self.activation_manager.get_active_agent_name()
            console.print(format_error(
                f"Agent '{current}' is already activated",
                suggestions=["Use /deactivate first, then activate new agent"]
            ))
            return

        try:
            with Live(Spinner("dots", text=f"[cyan]Activating {agent_name}...", style="cyan"), refresh_per_second=10):
                # Activate through manager (discovers files)
                result = self.activation_manager.activate(agent_name)

            if not result.success:
                console.print(format_error(
                    result.error or f"Failed to activate '{agent_name}'",
                    suggestions=result.suggestions
                ))
                return

            # Debug: Show registry status
            all_tools = self.tool_registry.list_all()
            console.print(f"[dim]Registry has {len(all_tools)} tools: {all_tools[:5]}...[/dim]")

            # Create activated agent wrapper
            self.activated_agent = ActivatedAgent(
                agent_name=agent_name,
                discovered_files=result.discovered_files,
                working_directory=self.working_directory,
                tool_registry=self.tool_registry,
                safety_mode=True,
                confirmation_callback=self._confirm_destructive_operation,
            )

            # Save activation state for persistence
            state_dict = self.activation_manager.get_state_dict()
            if state_dict:
                self.conversation_manager.save_activation_state(state_dict)

            # Show activation success with file summary
            self._show_activation_success(result)

        except Exception as e:
            console.print(format_error(f"Activation failed: {e}"))
            self.activation_manager.deactivate()
            self.activated_agent = None

    def _handle_deactivate_command(self):
        """Handle /deactivate command"""
        if not self.activation_manager.is_activated():
            console.print("[yellow]No agent is currently activated[/yellow]")
            return

        agent_name = self.activation_manager.get_active_agent_name()

        # Cleanup activated agent
        if self.activated_agent:
            self.activated_agent.cleanup()
            self.activated_agent = None

        # Deactivate in manager
        self.activation_manager.deactivate()

        # Clear persisted activation state
        self.conversation_manager.clear_activation_state()

        console.print(format_success(
            f"Agent '{agent_name}' deactivated",
            details={"Status": "Returned to normal mode"}
        ))

    def _show_activation_status(self):
        """Show current activation status"""
        if not self.activation_manager.is_activated():
            console.print("\n[yellow]No agent is currently activated[/yellow]")
            console.print("[dim]Use /activate <agent_name> to activate an agent[/dim]\n")
            return

        state = self.activation_manager.state
        if not state:
            return

        # Build status panel
        status_lines = [
            f"**Agent:** {state.agent_name}",
            f"**Working Directory:** `{state.working_directory}`",
            f"**Files Discovered:** {len(state.discovered_files)}",
            f"**Safety Mode:** {'Enabled' if state.safety_mode else 'Disabled'}",
            f"**Activated At:** {state.activated_at.strftime('%Y-%m-%d %H:%M:%S') if state.activated_at else 'N/A'}",
        ]

        if self.activated_agent:
            summary = self.activated_agent.get_discovered_files_summary()
            status_lines.append(f"**Total Size:** {summary['total_size']}")
            status_lines.append(f"**Recent Files:** {summary['recent_count']}")
            status_lines.append(f"**Extensions:** {', '.join(summary['extensions'][:5])}")

        status_text = "\n".join(status_lines)
        console.print(Panel(
            Markdown(status_text),
            title=f"[bold green]Activation Status: {state.agent_name}[/bold green]",
            border_style="green"
        ))

    def _refresh_discovered_files(self):
        """Refresh discovered files in activated mode"""
        if not self.activation_manager.is_activated():
            console.print("[yellow]No agent is activated. Use /activate first.[/yellow]")
            return

        try:
            with Live(Spinner("dots", text="[cyan]Refreshing files...", style="cyan"), refresh_per_second=10):
                # Re-discover files
                extensions = self.activation_manager.state.file_extensions
                new_files = self.activation_manager.discover_files(extensions)

                # Update state
                self.activation_manager.state.discovered_files = new_files

                # Update activated agent
                if self.activated_agent:
                    self.activated_agent.refresh_files(new_files)

            console.print(format_success(
                f"Refreshed file discovery",
                details={"Files found": len(new_files)}
            ))

        except Exception as e:
            console.print(format_error(f"Failed to refresh files: {e}"))

    def _show_activation_success(self, result):
        """Show compact activation success message"""
        # Get tools info from the activated agent
        tools_info = ""
        if self.activated_agent:
            agent_info = self.activated_agent.get_info()
            tools = agent_info.get("tools", [])
            if tools:
                tools_info = f" | tools: {', '.join(tools)}"
            else:
                tools_info = " | [yellow]NO TOOLS LOADED[/yellow]"

        console.print(f"\n[bold green]✓[/bold green] [green]{result.agent_name}[/green] activated | {result.files_count} files ({result.total_size_human}){tools_info} | /deactivate to exit\n")

    def _handle_activate_intent(self, intent):
        """Handle activation via natural language intent"""
        params = intent.parameters
        agent_name = params.get("agent_name")

        if not agent_name:
            console.print(format_error(
                "No agent name specified",
                suggestions=[
                    "Try: activate DataAnalyst",
                    "Try: activate Developer",
                    "Use /agents to see available agents"
                ]
            ))
            return

        # Delegate to the command handler by constructing a fake command
        self._handle_activate_command(f"/activate {agent_name}")

    def _confirm_destructive_operation(self, request: DestructiveOperationRequest) -> bool:
        """Callback to confirm destructive operations"""
        console.print(f"\n[bold yellow]Destructive Operation Request[/bold yellow]")
        console.print(f"Operation: {request.operation}")
        console.print(f"Target: {request.target_path}")
        console.print(f"Description: {request.description}")

        try:
            response = self.prompt_session.prompt("\nAllow this operation? (y/n) > ")
            return response.lower() in ["y", "yes"]
        except (KeyboardInterrupt, EOFError):
            return False

    def _execute_with_activated_agent(self, user_input: str):
        """Execute query through activated agent"""
        if not self.activated_agent:
            console.print(format_error("Activated agent not initialized"))
            return

        try:
            start_time = time.time()

            with Live(Spinner("dots", text=f"[cyan]Processing with {self.activation_manager.get_active_agent_name()}...", style="cyan"), refresh_per_second=10):
                result = self.activated_agent.run(user_input)

            elapsed = time.time() - start_time

            if result["success"]:
                # Display response with latency
                console.print(f"\n[bold green][{result['agent']}]>[/bold green] {result['output']}")
                console.print(f"[dim]Files context: {result.get('files_context', 0)} files | Latency: {elapsed:.2f}s[/dim]\n")
                self.conversation_manager.add_message("assistant", result["output"])
            else:
                error_msg = result.get("output", "Unknown error")
                console.print(format_error(error_msg))
                console.print(f"[dim]Latency: {elapsed:.2f}s[/dim]")
                self.conversation_manager.add_message("assistant", f"Error: {error_msg}")

        except Exception as e:
            console.print(format_error(f"Execution failed: {e}"))
            self.conversation_manager.add_message("assistant", f"Execution failed: {e}")

    def _confirm_exit(self) -> bool:
        """Confirm exit on Ctrl+C"""
        try:
            response = self.prompt_session.prompt("\nAre you sure you want to quit? (y/n) > ")
            return response.lower() in ["y", "yes"]
        except (KeyboardInterrupt, EOFError):
            return True

    def _process_user_input(self, user_input: str):
        """Process user input and execute action"""
        # Check for active deployment conversation first
        # This enables iterative deploy-fix-retry workflow
        if self._handle_deployment_followup(user_input):
            return

        try:
            # Parse intent without spinner (fast operation)
            intent = self.intent_parser.parse(user_input)

        except Exception as e:
            console.print(format_error(f"Failed to parse intent: {e}"))
            self.conversation_manager.add_message("assistant", f"I couldn't understand that. Error: {e}")
            return

        logger.debug(
            "intent_parsed",
            action=intent.action.value if hasattr(intent.action, 'value') else str(intent.action),
            confidence=intent.confidence,
            clarification_needed=intent.clarification_needed
        )

        if intent.clarification_needed:
            console.print(f"\n[yellow]{intent.clarification_question}[/yellow]")
            self.conversation_manager.add_message("assistant", intent.clarification_question)
            return

        # For general queries, skip the "analyzing" message - just answer directly
        if intent.action != IntentAction.GENERAL_QUERY:
            console.print(f"\n[dim]Action: {intent.action.value} (confidence: {intent.confidence:.0%})[/dim]\n")

        self._execute_intent(intent)

    def _execute_intent(self, intent):
        """Execute parsed intent"""
        try:
            if intent.action == IntentAction.CREATE_AGENT:
                self._handle_create_agent(intent)

            elif intent.action == IntentAction.CREATE_TOOL:
                self._handle_create_tool(intent)

            elif intent.action == IntentAction.CREATE_WORKFLOW:
                self._handle_create_workflow(intent)

            elif intent.action == IntentAction.RUN_AGENT:
                self._handle_run_agent(intent)

            elif intent.action == IntentAction.EXPORT_AGENT:
                self._handle_export_agent(intent)

            elif intent.action == IntentAction.LIST_AGENTS:
                list_resources("agents", tool_registry=self.tool_registry)
                self.conversation_manager.add_message("assistant", "Listed all agents")

            elif intent.action == IntentAction.LIST_TOOLS:
                list_resources("tools", tool_registry=self.tool_registry)
                self.conversation_manager.add_message("assistant", "Listed all tools")

            elif intent.action == IntentAction.SHOW_INFO:
                self._handle_show_info(intent)

            elif intent.action == IntentAction.DELETE_AGENT:
                self._handle_delete(intent)

            elif intent.action == IntentAction.HELP:
                self._show_help()
                self.conversation_manager.add_message("assistant", "Showed help information")

            elif intent.action == IntentAction.GENERAL_QUERY:
                self._handle_general_query(intent)

            elif intent.action == IntentAction.ACTIVATE_AGENT:
                self._handle_activate_intent(intent)

            elif intent.action == IntentAction.DEACTIVATE_AGENT:
                self._handle_deactivate_command()

            elif intent.action == IntentAction.DEPLOY_APP:
                self._handle_deploy_app(intent)

            elif intent.action == IntentAction.ANALYZE_PROJECT:
                self._handle_analyze_project(intent)

            else:
                console.print(f"[yellow]Action '{intent.action.value}' not yet implemented[/yellow]")
                self.conversation_manager.add_message("assistant", f"Action not implemented: {intent.action.value}")

        except Exception as e:
            console.print(format_error(f"Execution failed: {e}"))
            self.conversation_manager.add_message("assistant", f"Failed to execute: {e}")

    def _handle_create_agent(self, intent):
        """Handle agent creation with smart tool suggestion"""
        params = intent.parameters
        user_request = params.get("description", "") or params.get("suggested_name", "")

        # If no tools specified, intelligently suggest them
        if "tools" not in params or not params["tools"]:
            suggested_tools = self._suggest_tools_for_agent(user_request)

            if suggested_tools:
                tools_str = ", ".join(suggested_tools)
                console.print(f"\n[cyan]Suggested tools for this agent:[/cyan] {tools_str}")
                console.print("[dim]These tools will be automatically added.[/dim]\n")
                params["tools"] = suggested_tools
            else:
                # No tools needed - general purpose agent
                console.print("\n[cyan]Creating a general-purpose conversational agent (no specific tools needed)[/cyan]\n")
                params["tools"] = []
        else:
            # Use explicitly mentioned tools
            pass

        # Pass suggested name, tools, and description to interactive creator
        suggested_name = params.get("suggested_name")
        suggested_tools = params.get("tools", [])
        description = params.get("description")  # User's agent description for smart prompt generation

        file_path = create_agent_interactive(
            tool_registry=self.tool_registry,
            suggested_name=suggested_name,
            suggested_tools=suggested_tools,
            description=description
        )

        if file_path:
            response = f"Created agent successfully at {file_path}"
            self.conversation_manager.add_message("assistant", response)
        else:
            response = "Agent creation was cancelled or failed"
            self.conversation_manager.add_message("assistant", response)

    def _suggest_tools_for_agent(self, description: str) -> list:
        """Intelligently suggest tools based on agent description"""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage
        import json

        if not description:
            return []

        try:
            # Show spinner while analyzing tools
            with Live(Spinner("dots", text="[cyan]Analyzing tools needed...", style="cyan"), refresh_per_second=10):
                llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

                # Get available tools
                available_tools = self.tool_registry.list_all()
                tools_str = ", ".join(available_tools)

                system_prompt = f"""You suggest tools for agent creation. You MUST ONLY use exact tool names from this list:

AVAILABLE TOOLS (use EXACT names):
{tools_str}

CRITICAL: Return ONLY tool names that EXACTLY match the above list. Do NOT invent or modify names.

MAPPING GUIDE:
- CSV/data analysis → csv_process, dataframe_describe, dataframe_visualize, dataframe_analyze_folder
- Charts/visualization → dataframe_visualize
- Research/papers → wikipedia_search, arxiv_search
- File reading → file_read, json_process, csv_process
- Code/git → git_status, git_diff, file_read
- General chat → [] (empty array)

Return ONLY a JSON array with 0-5 tool names. Nothing else.
Example outputs: [] or ["csv_process", "dataframe_visualize"]"""

                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=f"Agent description: {description}")
                ]

                response = llm.invoke(messages)
                suggested = json.loads(response.content)

            # Validate suggestions
            return [tool for tool in suggested if tool in available_tools][:5]
        except Exception:
            # If suggestion fails, return empty (no tools)
            return []

    def _handle_create_tool(self, intent):
        """Handle tool creation"""
        file_path = create_tool_interactive()

        if file_path:
            response = f"Created tool successfully at {file_path}"
            self.conversation_manager.add_message("assistant", response)
        else:
            response = "Tool creation was cancelled or failed"
            self.conversation_manager.add_message("assistant", response)

    def _handle_create_workflow(self, intent):
        """Handle workflow creation"""
        available_agents = self.config_generator.list_configs("agents")
        file_path = create_workflow_interactive(available_agents=available_agents)

        if file_path:
            response = f"Created workflow successfully at {file_path}"
            self.conversation_manager.add_message("assistant", response)
        else:
            response = "Workflow creation was cancelled or failed"
            self.conversation_manager.add_message("assistant", response)

    def _handle_run_agent(self, intent):
        """Handle agent execution"""
        params = intent.parameters

        agent_name = params.get("agent_name")
        query = params.get("query")

        if not agent_name:
            console.print(format_error("No agent name specified"))
            self.conversation_manager.add_message("assistant", "Run failed: no agent name")
            return

        if not query:
            console.print(format_error("No query specified"))
            self.conversation_manager.add_message("assistant", "Run failed: no query")
            return

        output = run_agent_command(
            agent_name,
            query,
            tool_registry=self.tool_registry,
            stream=True
        )

        if output:
            response = f"Ran agent '{agent_name}' successfully"
            self.conversation_manager.add_message("assistant", response)
        else:
            response = f"Failed to run agent '{agent_name}'"
            self.conversation_manager.add_message("assistant", response)

    def _handle_export_agent(self, intent):
        """Handle agent export to Python code"""
        from agent_os.cli.commands.export import export_agent_to_python, export_agent_as_class

        params = intent.parameters
        agent_name = params.get("agent_name")
        as_class = params.get("as_class", False)
        output_path = params.get("output_path")

        if not agent_name:
            console.print(format_error("No agent name specified"))
            self.conversation_manager.add_message("assistant", "Export failed: no agent name")
            return

        if as_class:
            file_path = export_agent_as_class(agent_name, output_path=output_path, tool_registry=self.tool_registry)
        else:
            file_path = export_agent_to_python(agent_name, output_path=output_path, tool_registry=self.tool_registry)

        if file_path:
            response = f"Exported agent '{agent_name}' to {file_path}"
            self.conversation_manager.add_message("assistant", response)
        else:
            response = f"Failed to export agent '{agent_name}'"
            self.conversation_manager.add_message("assistant", response)

    def _handle_show_info(self, intent):
        """Handle show info request"""
        params = intent.parameters

        resource_type = params.get("resource_type", "agent")
        resource_name = params.get("resource_name")

        if not resource_name:
            console.print(format_error("No resource name specified"))
            self.conversation_manager.add_message("assistant", "Show info failed: no resource name")
            return

        info = show_resource_info(
            resource_type,
            resource_name,
            tool_registry=self.tool_registry
        )

        if info:
            response = f"Showed info for {resource_type} '{resource_name}'"
            self.conversation_manager.add_message("assistant", response)
        else:
            response = f"Failed to show info for '{resource_name}'"
            self.conversation_manager.add_message("assistant", response)

    def _handle_delete(self, intent):
        """Handle delete request"""
        params = intent.parameters

        resource_type = params.get("resource_type", "agent")
        resource_name = params.get("resource_name")

        if not resource_name:
            console.print(format_error("No resource name specified"))
            self.conversation_manager.add_message("assistant", "Delete failed: no resource name")
            return

        config_type_map = {
            "agent": "agents",
            "tool": "tools",
            "workflow": "workflows",
        }

        config_type = config_type_map.get(resource_type, "agents")

        success = self.config_generator.delete_config(config_type, resource_name)

        if success:
            console.print(format_success(f"Deleted {resource_type} '{resource_name}'"))
            response = f"Deleted {resource_type} '{resource_name}' successfully"
            self.conversation_manager.add_message("assistant", response)
        else:
            console.print(format_error(f"{resource_type.title()} '{resource_name}' not found"))
            response = f"Failed to delete '{resource_name}': not found"
            self.conversation_manager.add_message("assistant", response)

    def _handle_general_query(self, intent):
        """Handle general questions with smart tool selection"""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage
        from agent_os.cli.core.tool_selector import ToolSelector
        from agent_os.cli.agents.chat_agent import ChatAgent

        params = intent.parameters
        query = params.get("query", "")

        if not query:
            console.print(format_error("No query provided"))
            return

        try:
            start_time = time.time()

            # Analyze if tools are needed
            with Live(Spinner("dots", text="[cyan]Analyzing query...", style="cyan"), refresh_per_second=10):
                selector = ToolSelector(tool_registry=self.tool_registry)
                selection = selector.analyze(query, file_path=None)

            # Execute with tools if confidence is high enough
            if selection.requires_tools and selection.confidence >= 0.7:
                answer = self._execute_with_tools(query, selection.selected_tools, start_time)
            else:
                answer = self._execute_simple_llm(query, start_time)

            self.conversation_manager.add_message("user", query)
            self.conversation_manager.add_message("assistant", answer)

        except Exception as e:
            console.print(format_error(f"Failed to answer query: {e}"))
            self.conversation_manager.add_message("assistant", f"Failed to answer: {e}")

    def _execute_with_tools(self, query: str, tools: List[str], start_time: float) -> str:
        """Execute query using ChatAgent with tools"""
        from agent_os.cli.agents.chat_agent import ChatAgent

        try:
            with Live(Spinner("dots", text=f"[cyan]Using tools: {', '.join(tools)}...", style="cyan"), refresh_per_second=10):
                messages = self.conversation_manager.get_messages(limit=10)
                chat_history = [
                    {"role": msg.role, "content": msg.content}
                    for msg in messages
                ]

                agent = ChatAgent(
                    tools=tools,
                    tool_registry=self.tool_registry,
                    model="gpt-4o-mini",
                    temperature=0.3,
                    max_iterations=15,
                    timeout=60
                )

                result = agent.run(query, chat_history)

            answer = result["output"]

            elapsed = time.time() - start_time
            console.print(f"\n[bold cyan][AgentOS]>[/bold cyan] {answer}")
            console.print(f"[dim]Tools used: {', '.join(tools)} | Response time: {elapsed:.2f}s[/dim]\n")

            return answer

        except Exception as e:
            import traceback
            error_detail = f"{type(e).__name__}: {str(e)}"
            console.print(format_error(f"Tool execution failed: {error_detail}"))

            if console.is_terminal:
                console.print(f"[dim]{traceback.format_exc()}[/dim]")

            return self._execute_simple_llm(query, start_time)

    def _execute_simple_llm(self, query: str, start_time: float) -> str:
        """Execute query with plain LLM (no tools)"""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        with Live(Spinner("dots", text="[cyan]Thinking...", style="cyan"), refresh_per_second=10):
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
            system_prompt = """You are a helpful AI assistant specializing in AI/ML, LangChain, Python, and software development.

Provide direct, accurate answers with:
- Official website links when asked
- Practical code examples when relevant
- Clear explanations without unnecessary details
- For requests requiring real-time data, suggest using tools

Be concise and helpful."""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=query)
            ]

            response = llm.invoke(messages)
            answer = response.content

        elapsed = time.time() - start_time
        console.print(f"\n[bold cyan][AgentOS]>[/bold cyan] {answer}")
        console.print(f"[dim]Response time: {elapsed:.2f}s[/dim]\n")

        return answer

    def _query_needs_tools(self, query: str) -> bool:
        """Determine if a query needs tools or can be answered directly"""
        query_lower = query.lower()

        # Needs tools for:
        tool_keywords = [
            "read file", "open file", "check file", "analyze file",
            "search web", "scrape", "fetch url", "get website",
            "current", "latest", "today", "recent news",
            "find papers", "search arxiv", "wikipedia",
        ]

        # Simple knowledge questions don't need tools:
        knowledge_keywords = [
            "what is", "explain", "how does", "difference between",
            "tell me about", "describe", "why", "when",
        ]

        for keyword in tool_keywords:
            if keyword in query_lower:
                return True

        for keyword in knowledge_keywords:
            if keyword in query_lower:
                return False

        # Default: don't use tools for uncertain cases
        return False

    def _handle_deploy_app(self, intent):
        """
        Handle application deployment request with conversational support.

        Enables iterative deployment workflow:
        - Deploy → Fail → Diagnose → Fix → Retry → Success
        - User can say "what went wrong?", "fix it", "retry" until success
        """
        params = intent.parameters

        project_path = params.get("project_path", str(self.working_directory))
        target = params.get("target", "cloud_run")
        region = params.get("region", "us-central1")
        gcp_project_id = params.get("gcp_project_id")

        # Get or create conversational deployer
        deployer = get_conversational_deployer(self.tool_registry)

        # Check if we're continuing an existing deployment conversation
        if deployer.is_active():
            # Continue the conversation
            result = deployer.process_message(intent.parameters.get("query", "deploy"))
        else:
            # Start new deployment session
            deployer.start_deployment_conversation(
                project_path=project_path,
                target=target,
                region=region,
                gcp_project_id=gcp_project_id,
            )
            result = deployer.process_message("deploy")

        # Store response in conversation
        response = result.get("response", "Deployment initiated")
        self.conversation_manager.add_message("assistant", response[:500])

        # Enable follow-up conversation mode
        if result.get("phase") not in ["success", "cancelled", "failed"]:
            self._deployment_conversation_active = True
        else:
            self._deployment_conversation_active = False

    def _handle_deployment_followup(self, user_input: str) -> bool:
        """
        Handle follow-up messages in an active deployment conversation.

        Returns True if the message was handled as deployment followup.
        """
        if not getattr(self, '_deployment_conversation_active', False):
            return False

        # Check if this is a deployment-related message
        deployment_keywords = [
            "retry", "again", "fix", "diagnose", "what went wrong",
            "error", "status", "cancel", "rollback", "deploy"
        ]

        if not any(kw in user_input.lower() for kw in deployment_keywords):
            # Not deployment related - exit deployment mode
            self._deployment_conversation_active = False
            return False

        # Handle through conversational deployer
        deployer = get_conversational_deployer(self.tool_registry)
        result = deployer.process_message(user_input)

        # Store response
        response = result.get("response", "")
        self.conversation_manager.add_message("assistant", response[:500])

        # Check if deployment conversation is complete
        if result.get("phase") in ["success", "cancelled", "failed"]:
            self._deployment_conversation_active = False

        return True

    def _handle_analyze_project(self, intent):
        """Handle project analysis request"""
        params = intent.parameters
        project_path = params.get("project_path", ".")

        console.print("\n[bold cyan]🔍 Analyzing Project...[/bold cyan]\n")

        try:
            result = analyze_project_command(project_path=project_path)

            if result:
                response = f"Project analysis complete. Detected: {result.get('language', 'Unknown')} / {result.get('framework', 'Unknown')}"
            else:
                response = "Project analysis complete."

            self.conversation_manager.add_message("assistant", response)

        except Exception as e:
            console.print(format_error(f"Analysis failed: {e}"))
            self.conversation_manager.add_message("assistant", f"Analysis failed: {e}")


def start_chat_repl(session_id: Optional[str] = None):
    """
    Start interactive chat REPL.

    Args:
        session_id: Resume existing session (None creates new)
    """
    repl = ChatREPL(session_id=session_id)
    repl.start()
