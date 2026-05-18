"""Deployment command handler for CLI"""

from typing import Optional, Dict, Any
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.prompt import Prompt, Confirm

from agent_os.workflows.deployment import (
    DeploymentOrchestrator,
    DeploymentRequest,
    DeploymentResult,
    DeploymentTarget,
    DeploymentStatus,
    TechStackAnalysis
)
from agent_os.tools.registry import ToolRegistry
from agent_os.cli.ui.formatters import format_success, format_error, format_info_panel
from agent_os.cli.core.deployment_conversation import (
    DeploymentConversationManager,
    DeploymentSession,
    DeploymentPhase,
    get_deployment_manager,
)

console = Console()


def deploy_command(
    project_path: str = ".",
    gcp_project_id: Optional[str] = None,
    target: str = "cloud_run",
    region: str = "us-central1",
    service_name: Optional[str] = None,
    env_file: Optional[str] = None,
    push_to_git: bool = False,
    commit_message: Optional[str] = None,
    interactive: bool = True,
    tool_registry: Optional[ToolRegistry] = None
) -> Optional[DeploymentResult]:
    """
    Execute deployment workflow via CLI.

    Args:
        project_path: Path to project source
        gcp_project_id: GCP project ID
        target: Deployment target (cloud_run, app_engine, gke)
        region: GCP region
        service_name: Service name
        env_file: Path to .env file
        push_to_git: Push to git before deploy
        commit_message: Git commit message
        interactive: Enable interactive mode for questions
        tool_registry: Tool registry instance

    Returns:
        DeploymentResult if successful, None otherwise
    """
    console.print("\n[bold cyan]Deployment Workflow[/bold cyan]\n")

    # Validate project path
    project = Path(project_path).resolve()
    if not project.exists():
        console.print(format_error(
            f"Project path not found: {project_path}",
            suggestions=["Verify the project path exists"]
        ))
        return None

    # Interactive mode - gather configuration
    if interactive:
        config = _gather_deployment_config(
            project_path=str(project),
            gcp_project_id=gcp_project_id,
            target=target,
            region=region,
            service_name=service_name,
            env_file=env_file,
            push_to_git=push_to_git
        )
        if config is None:
            return None
    else:
        config = {
            "project_path": str(project),
            "gcp_project_id": gcp_project_id,
            "target": target,
            "region": region,
            "service_name": service_name,
            "env_file": env_file,
            "push_to_git": push_to_git,
            "commit_message": commit_message
        }

    # Map target string to enum
    target_map = {
        "cloud_run": DeploymentTarget.CLOUD_RUN,
        "app_engine": DeploymentTarget.APP_ENGINE,
        "gke": DeploymentTarget.GKE,
        "cloud_functions": DeploymentTarget.CLOUD_FUNCTIONS
    }
    target_enum = target_map.get(config["target"], DeploymentTarget.CLOUD_RUN)

    # Build deployment request
    request = DeploymentRequest(
        project_path=config["project_path"],
        gcp_project_id=config["gcp_project_id"],
        target=target_enum,
        region=config["region"],
        service_name=config["service_name"],
        env_file=config["env_file"],
        sync_secrets=bool(config["env_file"]),
        push_to_git=config["push_to_git"],
        commit_message=config.get("commit_message")
    )

    # Show deployment plan
    _show_deployment_plan(request)

    # Confirm before proceeding
    if interactive and not Confirm.ask("\n[yellow]Proceed with deployment?[/yellow]"):
        console.print("[dim]Deployment cancelled.[/dim]")
        return None

    # Execute deployment
    try:
        console.print("\n[bold]Starting deployment...[/bold]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task = progress.add_task("Initializing orchestrator...", total=100)

            # Initialize orchestrator
            orchestrator = DeploymentOrchestrator(tool_registry=tool_registry)
            progress.update(task, advance=20, description="Analyzing project...")

            # Execute deployment
            progress.update(task, advance=20, description="Executing deployment...")
            result = orchestrator.deploy(request)

            progress.update(task, advance=60, description="Finalizing...")

        # Show result
        _show_deployment_result(result)

        return result

    except Exception as e:
        console.print(format_error(
            f"Deployment failed: {e}",
            suggestions=[
                "Check your GCP credentials",
                "Verify the project has required APIs enabled",
                "Check the logs for detailed error information"
            ]
        ))
        return None


def analyze_project_command(
    project_path: str = ".",
    tool_registry: Optional[ToolRegistry] = None
) -> Optional[TechStackAnalysis]:
    """
    Analyze project without deploying.

    Args:
        project_path: Path to project
        tool_registry: Tool registry instance

    Returns:
        TechStackAnalysis if successful
    """
    console.print("\n[bold cyan]Project Analysis[/bold cyan]\n")

    project = Path(project_path).resolve()
    if not project.exists():
        console.print(format_error(f"Project path not found: {project_path}"))
        return None

    try:
        orchestrator = DeploymentOrchestrator(tool_registry=tool_registry)
        analysis = orchestrator.analyze_project(str(project))

        # Show analysis results
        table = Table(title="Tech Stack Analysis")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        if analysis.language:
            table.add_row("Language", analysis.language)
        if analysis.framework:
            table.add_row("Framework", analysis.framework)
        if analysis.runtime:
            table.add_row("Runtime", analysis.runtime)

        table.add_row("Has Dockerfile", "Yes" if analysis.has_dockerfile else "No")
        table.add_row("Has cloudbuild.yaml", "Yes" if analysis.has_cloudbuild else "No")

        if analysis.suggested_services:
            table.add_row("Suggested Services", ", ".join(analysis.suggested_services))

        console.print(table)
        return analysis

    except Exception as e:
        console.print(format_error(f"Analysis failed: {e}"))
        return None


def _gather_deployment_config(
    project_path: str,
    gcp_project_id: Optional[str],
    target: str,
    region: str,
    service_name: Optional[str],
    env_file: Optional[str],
    push_to_git: bool
) -> Optional[Dict[str, Any]]:
    """Gather deployment configuration interactively"""

    console.print("[dim]Please provide deployment configuration:[/dim]\n")

    # Project path
    project_path = Prompt.ask(
        "Project path",
        default=project_path
    )

    # GCP Project ID
    gcp_project_id = Prompt.ask(
        "GCP Project ID",
        default=gcp_project_id or "(auto-detect)"
    )
    if gcp_project_id == "(auto-detect)":
        gcp_project_id = None

    # Target
    target = Prompt.ask(
        "Deployment target",
        choices=["cloud_run", "app_engine", "gke", "cloud_functions"],
        default=target
    )

    # Region
    region = Prompt.ask(
        "GCP Region",
        default=region
    )

    # Service name
    service_name = Prompt.ask(
        "Service name",
        default=service_name or "(auto-detect)"
    )
    if service_name == "(auto-detect)":
        service_name = None

    # Environment file
    env_file = Prompt.ask(
        "Environment file (.env)",
        default=env_file or "(none)"
    )
    if env_file == "(none)":
        env_file = None

    # Git push
    push_to_git = Confirm.ask("Push to git before deploy?", default=push_to_git)

    commit_message = None
    if push_to_git:
        commit_message = Prompt.ask(
            "Commit message",
            default="Deploy to GCP"
        )

    return {
        "project_path": project_path,
        "gcp_project_id": gcp_project_id,
        "target": target,
        "region": region,
        "service_name": service_name,
        "env_file": env_file,
        "push_to_git": push_to_git,
        "commit_message": commit_message
    }


def _show_deployment_plan(request: DeploymentRequest):
    """Display deployment plan"""
    table = Table(title="Deployment Plan", show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Project Path", request.project_path)
    table.add_row("GCP Project", request.gcp_project_id or "(auto-detect)")
    table.add_row("Target", request.target.value)
    table.add_row("Region", request.region)
    table.add_row("Service Name", request.service_name or "(auto-detect)")
    table.add_row("Memory", request.memory)
    table.add_row("CPU", request.cpu)
    table.add_row("Allow Public Access", "Yes" if request.allow_unauthenticated else "No")

    if request.env_file:
        table.add_row("Secrets From", request.env_file)
        table.add_row("Sync Secrets", "Yes" if request.sync_secrets else "No")

    if request.push_to_git:
        table.add_row("Git Push", "Yes")
        table.add_row("Branch", request.branch)

    console.print(table)


def _show_deployment_result(result: DeploymentResult):
    """Display deployment result"""
    if result.success:
        console.print("\n[bold green]DEPLOYMENT SUCCESSFUL[/bold green]\n")

        info = {}
        if result.endpoint_url:
            info["Endpoint URL"] = result.endpoint_url
        if result.service_name:
            info["Service Name"] = result.service_name
        if result.project_id:
            info["Project ID"] = result.project_id
        if result.region:
            info["Region"] = result.region
        info["Attempts"] = str(result.attempts)
        if result.total_duration_seconds:
            info["Duration"] = f"{result.total_duration_seconds:.1f}s"

        console.print(format_info_panel(info, title="Deployment Details"))

    else:
        console.print("\n[bold red]DEPLOYMENT FAILED[/bold red]\n")

        console.print(format_error(
            result.error or "Unknown error",
            suggestions=result.suggestions
        ))

        if result.error_analysis:
            console.print("\n[bold]Error Analysis:[/bold]")
            console.print(Panel(str(result.error_analysis), title="Analysis"))

        # Show execution history
        if result.steps:
            console.print("\n[bold]Execution History:[/bold]")
            for step in result.steps:
                status_icon = "[green]OK[/green]" if step.status == "completed" else "[red]FAIL[/red]"
                console.print(f"  {status_icon} {step.name}: {step.message[:100]}...")


def deploy_interactive(tool_registry: Optional[ToolRegistry] = None) -> Optional[DeploymentResult]:
    """
    Run deployment in fully interactive mode.

    This is called from the chat interface when user says "deploy my app".
    """
    return deploy_command(
        project_path=".",
        interactive=True,
        tool_registry=tool_registry
    )


# =============================================================================
# Conversational Deployment - Iterative Deploy/Fix/Retry until Success
# =============================================================================


class ConversationalDeployer:
    """
    Handles iterative conversational deployment.

    Enables users to have ongoing conversations:
    User: "deploy my app"
    [Deployment fails]
    User: "what went wrong?"
    [Shows diagnosis]
    User: "fix it"
    [Applies fix]
    User: "retry"
    [Retries deployment]
    [Success!]
    """

    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        self.manager = get_deployment_manager()
        self.tool_registry = tool_registry
        self.orchestrator: Optional[DeploymentOrchestrator] = None
        self._current_session: Optional[DeploymentSession] = None

    def start_deployment_conversation(
        self,
        project_path: str = ".",
        target: str = "cloud_run",
        region: str = "us-central1",
        gcp_project_id: Optional[str] = None,
    ) -> str:
        """Start a new deployment conversation session"""
        self._current_session = self.manager.start_session(
            project_path=project_path,
            target=target,
            region=region,
            project_id=gcp_project_id,
        )

        console.print(Panel(
            f"[bold green]Deployment Session Started[/bold green]\n\n"
            f"Session ID: {self._current_session.session_id}\n"
            f"Project: {project_path}\n"
            f"Target: {target}\n"
            f"Region: {region}\n\n"
            f"[dim]You can now have a conversation about this deployment.[/dim]\n"
            f"[dim]Say 'deploy', 'status', 'what went wrong?', 'fix it', 'retry', or 'cancel'[/dim]",
            title="Deployment Conversation Mode"
        ))

        return self._current_session.session_id

    def process_message(self, message: str) -> Dict[str, Any]:
        """
        Process a message in the deployment conversation.

        Args:
            message: User's message

        Returns:
            Response dict with 'response' text and other metadata
        """
        # Get or create session
        session = self._current_session or self.manager.get_active_session()

        if not session:
            # Start new session if user says deploy
            if any(kw in message.lower() for kw in ["deploy", "ship", "push"]):
                self.start_deployment_conversation()
                session = self._current_session

        if not session:
            return {
                "response": "No active deployment session. Say 'deploy my app' to start.",
                "action_taken": None,
                "phase": None,
            }

        # Process through conversation manager
        result = self.manager.process_message(session.session_id, message)

        # Execute tools if needed
        if result.get("tools_to_run"):
            self._execute_deployment_tools(session, result["tools_to_run"])

        # Display response
        console.print(result["response"])

        # If deployment should run, execute it
        if result.get("action_taken") == "start_deployment":
            deploy_result = self._execute_deployment(session)
            result["deployment_result"] = deploy_result

        return result

    def _execute_deployment(self, session: DeploymentSession) -> Optional[DeploymentResult]:
        """Execute the actual deployment"""
        try:
            # Initialize orchestrator
            if not self.orchestrator:
                self.orchestrator = DeploymentOrchestrator(tool_registry=self.tool_registry)

            # Build request
            target_map = {
                "cloud_run": DeploymentTarget.CLOUD_RUN,
                "app_engine": DeploymentTarget.APP_ENGINE,
                "gke": DeploymentTarget.GKE,
            }

            request = DeploymentRequest(
                project_path=session.project_path,
                gcp_project_id=session.project_id,
                target=target_map.get(session.target, DeploymentTarget.CLOUD_RUN),
                region=session.region,
                service_name=session.service_name,
            )

            # Execute with progress display
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                console=console
            ) as progress:
                task = progress.add_task("Deploying...", total=100)

                # Execute deployment
                result = self.orchestrator.deploy(request)

                progress.update(task, completed=100)

            # Record result
            if result.success:
                self.manager.record_attempt_result(
                    session.session_id,
                    success=True,
                    phase_reached=DeploymentPhase.SUCCESS,
                    endpoint_url=result.endpoint_url,
                )
                session.service_name = result.service_name
                session.endpoint_url = result.endpoint_url

                console.print(Panel(
                    f"[bold green]DEPLOYMENT SUCCESSFUL![/bold green]\n\n"
                    f"Endpoint: {result.endpoint_url}\n"
                    f"Service: {result.service_name}\n"
                    f"Attempts: {session.get_attempt_count()}",
                    title="Success",
                    border_style="green"
                ))
            else:
                self.manager.record_attempt_result(
                    session.session_id,
                    success=False,
                    phase_reached=DeploymentPhase.FAILED,
                    error_message=result.error,
                    error_logs=str(result.error_analysis) if result.error_analysis else None,
                )

                console.print(Panel(
                    f"[bold red]DEPLOYMENT FAILED[/bold red]\n\n"
                    f"Error: {result.error}\n\n"
                    f"[dim]Say 'what went wrong?' to diagnose, or 'retry' to try again.[/dim]",
                    title="Failed",
                    border_style="red"
                ))

            return result

        except Exception as e:
            self.manager.record_attempt_result(
                session.session_id,
                success=False,
                phase_reached=DeploymentPhase.FAILED,
                error_message=str(e),
            )
            console.print(format_error(f"Deployment error: {e}"))
            return None

    def _execute_deployment_tools(self, session: DeploymentSession, tools: list):
        """Execute deployment-related tools"""
        for tool_spec in tools:
            tool_name = tool_spec.get("tool")
            params = tool_spec.get("params", {})

            if not tool_name:
                continue

            try:
                from agent_os.tools.global_registry import get_global_registry
                registry = get_global_registry()
                tool = registry.get(tool_name)

                if tool:
                    console.print(f"[dim]Running {tool_name}...[/dim]")
                    result = tool.execute(**params)

                    # Store results in session based on tool type
                    if tool_name == "tech_stack_analyzer" and isinstance(result, dict):
                        session.tech_stack = result.get("result", {})
                    elif tool_name == "secret_scanner" and isinstance(result, dict):
                        r = result.get("result", {})
                        if isinstance(r, str):
                            import json
                            r = json.loads(r)
                        if r.get("secrets_found", 0) > 0:
                            session.security_issues = r.get("findings", [])
            except Exception as e:
                console.print(f"[yellow]Warning: {tool_name} failed: {e}[/yellow]")

    def get_status(self) -> str:
        """Get current deployment session status"""
        session = self._current_session or self.manager.get_active_session()

        if not session:
            return "No active deployment session."

        return self.manager._format_status(session)

    def is_active(self) -> bool:
        """Check if there's an active deployment conversation"""
        session = self._current_session or self.manager.get_active_session()
        return session is not None and not session.is_complete()


# Singleton instance
_conversational_deployer: Optional[ConversationalDeployer] = None


def get_conversational_deployer(tool_registry: Optional[ToolRegistry] = None) -> ConversationalDeployer:
    """Get or create the conversational deployer instance"""
    global _conversational_deployer
    if _conversational_deployer is None:
        _conversational_deployer = ConversationalDeployer(tool_registry=tool_registry)
    return _conversational_deployer


def handle_deployment_message(
    message: str,
    tool_registry: Optional[ToolRegistry] = None
) -> Dict[str, Any]:
    """
    Handle a message in the context of deployment conversation.

    This is the main entry point for the chat REPL to process deployment-related messages.

    Args:
        message: User's message
        tool_registry: Tool registry instance

    Returns:
        Response dict
    """
    deployer = get_conversational_deployer(tool_registry)
    return deployer.process_message(message)
