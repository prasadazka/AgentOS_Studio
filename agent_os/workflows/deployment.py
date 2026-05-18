"""
Deployment Workflow Orchestrator

Automates full deployment workflows with:
- Code analysis and tech stack detection
- Git operations (commit, push)
- Secrets management
- Cloud API enablement
- Deployment to GCP Cloud Run
- Log monitoring and error analysis
- Automatic retry with diagnosis

Uses SupervisorAgent to coordinate specialized worker agents.
"""

import json
from typing import Dict, List, Optional, Any, Literal
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field

from agent_os.agents.base import BaseAgent
from agent_os.tools.registry import ToolRegistry
from agent_os.tools.global_registry import get_global_registry
from agent_os.workflows.supervisor import SupervisorAgent
from agent_os.utils.logging import get_logger
from agent_os.utils.errors import WorkflowExecutionError

logger = get_logger("workflows.deployment")


# =============================================================================
# Type-Safe Models
# =============================================================================

class DeploymentTarget(str, Enum):
    """Supported deployment targets"""
    CLOUD_RUN = "cloud_run"
    APP_ENGINE = "app_engine"
    GKE = "gke"
    CLOUD_FUNCTIONS = "cloud_functions"


class DeploymentStatus(str, Enum):
    """Deployment workflow status"""
    PENDING = "pending"
    ANALYZING = "analyzing"
    PREPARING = "preparing"
    DEPLOYING = "deploying"
    VERIFYING = "verifying"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


class DeploymentRequest(BaseModel):
    """Request for deployment workflow"""
    project_path: str = Field(default=".", description="Path to project source code")
    gcp_project_id: Optional[str] = Field(None, description="GCP project ID (auto-detect if not specified)")
    target: DeploymentTarget = Field(default=DeploymentTarget.CLOUD_RUN, description="Deployment target")
    region: str = Field(default="us-central1", description="GCP region")
    service_name: Optional[str] = Field(None, description="Service name (auto-detect if not specified)")

    # Git options
    push_to_git: bool = Field(default=False, description="Push code to git before deploy")
    commit_message: Optional[str] = Field(None, description="Git commit message")
    branch: str = Field(default="main", description="Git branch")

    # Secrets options
    env_file: Optional[str] = Field(None, description="Path to .env file for secrets")
    sync_secrets: bool = Field(default=False, description="Sync secrets to GCP Secret Manager")

    # Build options
    dockerfile: Optional[str] = Field(None, description="Dockerfile path (auto-detect if not specified)")
    build_args: Dict[str, str] = Field(default_factory=dict, description="Build arguments")

    # Deployment options
    memory: str = Field(default="512Mi", description="Memory allocation")
    cpu: str = Field(default="1", description="CPU allocation")
    min_instances: int = Field(default=0, description="Minimum instances")
    max_instances: int = Field(default=10, description="Maximum instances")
    allow_unauthenticated: bool = Field(default=True, description="Allow public access")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables")

    # Retry options
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    auto_fix: bool = Field(default=True, description="Attempt automatic fixes on failure")


class DeploymentStep(BaseModel):
    """Single step in deployment workflow"""
    name: str
    status: str
    message: str
    duration_seconds: Optional[float] = None
    details: Optional[Dict[str, Any]] = None


class DeploymentResult(BaseModel):
    """Result of deployment workflow"""
    success: bool
    status: DeploymentStatus
    endpoint_url: Optional[str] = None
    service_name: Optional[str] = None
    project_id: Optional[str] = None
    region: Optional[str] = None
    attempts: int = 1
    steps: List[DeploymentStep] = Field(default_factory=list)
    error: Optional[str] = None
    error_analysis: Optional[Dict[str, Any]] = None
    suggestions: List[str] = Field(default_factory=list)
    total_duration_seconds: Optional[float] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class TechStackAnalysis(BaseModel):
    """Result of code analysis"""
    language: Optional[str] = None
    framework: Optional[str] = None
    runtime: Optional[str] = None
    python_version: Optional[str] = None
    node_version: Optional[str] = None
    dependencies_count: int = 0
    has_dockerfile: bool = False
    has_cloudbuild: bool = False
    suggested_services: List[str] = Field(default_factory=list)


# =============================================================================
# Agent System Prompts
# =============================================================================

CODE_ANALYZER_PROMPT = """You are a Code Analyzer specializing in detecting project tech stacks and deployment requirements.

Your responsibilities:
1. Analyze project structure and identify language, framework, and runtime
2. Check for deployment-related files (Dockerfile, cloudbuild.yaml, etc.)
3. Identify required GCP services based on dependencies
4. Suggest optimal deployment configuration

Be thorough but concise. Report findings in a structured format."""


GIT_AGENT_PROMPT = """You are a Git Operations Agent responsible for version control tasks.

Your responsibilities:
1. Check git status for uncommitted changes
2. Stage and commit changes with meaningful messages
3. Push commits to remote repository
4. Handle merge conflicts if they arise

RULES:
- Never force push without explicit approval
- Always check status before operations
- Report any issues clearly"""


SECRET_AGENT_PROMPT = """You are a Secrets Manager Agent responsible for secure secret handling.

Your responsibilities:
1. Read .env files and extract secret names (never expose values in logs)
2. Create/update secrets in GCP Secret Manager
3. Verify secrets are properly configured

SECURITY RULES:
- NEVER log or display secret values
- Always use secure channels for secret operations
- Verify secrets exist before deployment"""


INFRA_AGENT_PROMPT = """You are an Infrastructure Agent responsible for GCP resource management.

Your responsibilities:
1. Enable required GCP APIs (Cloud Run, Cloud Build, Secret Manager, etc.)
2. Verify service account permissions
3. Create necessary cloud resources

Be efficient - only enable APIs that are actually needed."""


DEPLOY_AGENT_PROMPT = """You are a Deployment Agent specializing in GCP Cloud Run deployments.

Your responsibilities:
1. Build container images using Cloud Build
2. Deploy to Cloud Run with proper configuration
3. Configure traffic, memory, and scaling settings

Report deployment status and any errors clearly."""


MONITOR_AGENT_PROMPT = """You are a Monitoring Agent responsible for deployment verification.

Your responsibilities:
1. Check deployment logs for errors
2. Verify service is healthy and responding
3. Analyze any errors and suggest fixes

If deployment failed, provide detailed error analysis with actionable suggestions."""


DEPLOYMENT_SUPERVISOR_PROMPT = """You are a Deployment Supervisor coordinating a team of specialized agents to deploy applications to GCP.

Available agents:
- code_analyzer: Analyzes code to detect tech stack and requirements
- git_agent: Handles git operations (commit, push)
- secret_agent: Manages secrets from .env to GCP Secret Manager
- infra_agent: Enables GCP APIs and creates resources
- deploy_agent: Builds and deploys to Cloud Run
- monitor_agent: Monitors logs and verifies deployment

DEPLOYMENT WORKFLOW:
1. Analyze code first to understand what we're deploying
2. Handle git operations if requested
3. Sync secrets if env file provided
4. Enable required GCP APIs
5. Build and deploy
6. Verify deployment is healthy

RULES:
- Follow the workflow in order
- If any step fails, stop and report the error
- Use monitor_agent to diagnose failures
- Signal 'FINISH' when deployment is complete or definitively failed
- Be efficient - skip steps that aren't needed"""


# =============================================================================
# Deployment Orchestrator
# =============================================================================

class DeploymentOrchestrator:
    """
    Orchestrates full deployment workflows with automatic retry and error diagnosis.

    Uses SupervisorAgent to coordinate specialized worker agents:
    - code_analyzer: Detect tech stack and requirements
    - git_agent: Git operations (commit, push)
    - secret_agent: Secrets management
    - infra_agent: GCP API enablement
    - deploy_agent: Build and deploy
    - monitor_agent: Log monitoring and verification

    Example:
        orchestrator = DeploymentOrchestrator()
        result = orchestrator.deploy(DeploymentRequest(
            project_path="./my-app",
            gcp_project_id="my-project",
            target=DeploymentTarget.CLOUD_RUN,
            region="us-central1"
        ))
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        model: str = "gpt-4o-mini",
        max_supervisor_iterations: int = 20
    ):
        """
        Initialize deployment orchestrator.

        Args:
            tool_registry: Tool registry (uses global registry if None)
            model: LLM model for agents
            max_supervisor_iterations: Max iterations for supervisor
        """
        self.registry = tool_registry or get_global_registry()
        self.model = model
        self.max_supervisor_iterations = max_supervisor_iterations

        # Create specialized agents
        self.agents = self._create_agents()

        # Create supervisor
        self.supervisor = SupervisorAgent(
            worker_agents=self.agents,
            model=model,
            max_iterations=max_supervisor_iterations,
            system_prompt=DEPLOYMENT_SUPERVISOR_PROMPT
        )

        logger.info(f"DeploymentOrchestrator initialized with {len(self.agents)} agents")

    def _create_agents(self) -> Dict[str, BaseAgent]:
        """Create specialized deployment agents"""
        agents = {}

        # Code Analyzer Agent
        code_analysis_tools = ["tech_stack_analyzer", "dependency_scanner", "dockerfile_analyzer"]
        available_tools = [t for t in code_analysis_tools if self.registry.get(t)]
        if available_tools:
            agents["code_analyzer"] = BaseAgent(
                name="CodeAnalyzer",
                tools=available_tools,
                model=self.model,
                temperature=0,
                system_prompt=CODE_ANALYZER_PROMPT,
                tool_registry=self.registry,
                enable_circuit_breaker=False,  # Disable for workflow agents
                enable_cost_tracking=False,
                enable_rate_limiting=False,
                enable_retry=False,
                enable_metrics=False
            )
            logger.debug(f"Created code_analyzer agent with tools: {available_tools}")

        # Git Agent
        git_tools = ["git_status", "git_diff", "git_add", "git_commit", "git_push"]
        available_tools = [t for t in git_tools if self.registry.get(t)]
        if available_tools:
            agents["git_agent"] = BaseAgent(
                name="GitAgent",
                tools=available_tools,
                model=self.model,
                temperature=0,
                system_prompt=GIT_AGENT_PROMPT,
                tool_registry=self.registry,
                enable_circuit_breaker=False,
                enable_cost_tracking=False,
                enable_rate_limiting=False,
                enable_retry=False,
                enable_metrics=False
            )
            logger.debug(f"Created git_agent with tools: {available_tools}")

        # Secret Agent
        secret_tools = ["env_file_reader", "gcp_secret_manager", "secret_sync"]
        available_tools = [t for t in secret_tools if self.registry.get(t)]
        if available_tools:
            agents["secret_agent"] = BaseAgent(
                name="SecretAgent",
                tools=available_tools,
                model=self.model,
                temperature=0,
                system_prompt=SECRET_AGENT_PROMPT,
                tool_registry=self.registry,
                enable_circuit_breaker=False,
                enable_cost_tracking=False,
                enable_rate_limiting=False,
                enable_retry=False,
                enable_metrics=False
            )
            logger.debug(f"Created secret_agent with tools: {available_tools}")

        # Infrastructure Agent
        infra_tools = ["gcp_service_enabler"]
        available_tools = [t for t in infra_tools if self.registry.get(t)]
        if available_tools:
            agents["infra_agent"] = BaseAgent(
                name="InfraAgent",
                tools=available_tools,
                model=self.model,
                temperature=0,
                system_prompt=INFRA_AGENT_PROMPT,
                tool_registry=self.registry,
                enable_circuit_breaker=False,
                enable_cost_tracking=False,
                enable_rate_limiting=False,
                enable_retry=False,
                enable_metrics=False
            )
            logger.debug(f"Created infra_agent with tools: {available_tools}")

        # Deploy Agent
        deploy_tools = ["gcp_cloud_build", "gcp_cloud_run"]
        available_tools = [t for t in deploy_tools if self.registry.get(t)]
        if available_tools:
            agents["deploy_agent"] = BaseAgent(
                name="DeployAgent",
                tools=available_tools,
                model=self.model,
                temperature=0,
                system_prompt=DEPLOY_AGENT_PROMPT,
                tool_registry=self.registry,
                max_execution_time=600,  # 10 minute timeout for deployments
                enable_circuit_breaker=False,
                enable_cost_tracking=False,
                enable_rate_limiting=False,
                enable_retry=False,
                enable_metrics=False
            )
            logger.debug(f"Created deploy_agent with tools: {available_tools}")

        # Monitor Agent
        monitor_tools = ["gcp_logging", "gcp_error_analyzer", "cloud_run_logs"]
        available_tools = [t for t in monitor_tools if self.registry.get(t)]
        if available_tools:
            agents["monitor_agent"] = BaseAgent(
                name="MonitorAgent",
                tools=available_tools,
                model=self.model,
                temperature=0,
                system_prompt=MONITOR_AGENT_PROMPT,
                tool_registry=self.registry,
                enable_circuit_breaker=False,
                enable_cost_tracking=False,
                enable_rate_limiting=False,
                enable_retry=False,
                enable_metrics=False
            )
            logger.debug(f"Created monitor_agent with tools: {available_tools}")

        if not agents:
            raise WorkflowExecutionError(
                "No deployment tools available. Ensure deployment tools are registered."
            )

        return agents

    def _build_deployment_prompt(self, request: DeploymentRequest) -> str:
        """Build comprehensive deployment prompt for supervisor"""
        prompt_parts = [
            f"Deploy the application at '{request.project_path}' to GCP {request.target.value}.",
            f"",
            f"Configuration:",
            f"- GCP Project: {request.gcp_project_id or '(auto-detect)'}",
            f"- Region: {request.region}",
            f"- Service Name: {request.service_name or '(auto-detect from project)'}",
            f"- Memory: {request.memory}",
            f"- CPU: {request.cpu}",
            f"- Allow Unauthenticated: {request.allow_unauthenticated}",
        ]

        if request.push_to_git:
            prompt_parts.append(f"")
            prompt_parts.append(f"Git Operations:")
            prompt_parts.append(f"- Commit and push changes to {request.branch}")
            if request.commit_message:
                prompt_parts.append(f"- Commit message: {request.commit_message}")

        if request.env_file and request.sync_secrets:
            prompt_parts.append(f"")
            prompt_parts.append(f"Secrets:")
            prompt_parts.append(f"- Sync secrets from {request.env_file} to GCP Secret Manager")

        prompt_parts.append(f"")
        prompt_parts.append("Workflow Steps:")
        prompt_parts.append("1. Use code_analyzer to detect tech stack and requirements")
        if request.push_to_git:
            prompt_parts.append("2. Use git_agent to commit and push changes")
        if request.env_file and request.sync_secrets:
            prompt_parts.append("3. Use secret_agent to sync secrets from .env to GCP")
        prompt_parts.append("4. Use infra_agent to enable required GCP APIs")
        prompt_parts.append("5. Use deploy_agent to build and deploy to Cloud Run")
        prompt_parts.append("6. Use monitor_agent to verify deployment is healthy")
        prompt_parts.append("")
        prompt_parts.append("Return 'FINISH' when deployment is complete with the endpoint URL.")

        return "\n".join(prompt_parts)

    def deploy(self, request: DeploymentRequest) -> DeploymentResult:
        """
        Execute deployment workflow with automatic retry.

        Args:
            request: Deployment configuration

        Returns:
            DeploymentResult with status, endpoint URL, and execution details
        """
        import time
        start_time = time.time()

        logger.info(f"Starting deployment for {request.project_path} to {request.target.value}")

        steps: List[DeploymentStep] = []
        last_error = None
        last_error_analysis = None

        for attempt in range(1, request.max_retries + 1):
            logger.info(f"Deployment attempt {attempt}/{request.max_retries}")

            try:
                # Build deployment prompt
                prompt = self._build_deployment_prompt(request)

                # Add retry context if not first attempt
                if attempt > 1 and last_error:
                    prompt += f"\n\nPREVIOUS ATTEMPT FAILED:\n{last_error}"
                    if last_error_analysis:
                        prompt += f"\n\nError Analysis:\n{json.dumps(last_error_analysis, indent=2)}"
                    prompt += "\n\nPlease diagnose the issue and retry the deployment."

                # Execute supervisor workflow
                result = self.supervisor.run(prompt)

                # Record step
                steps.append(DeploymentStep(
                    name=f"attempt_{attempt}",
                    status="completed" if result.get("completed") else "failed",
                    message=result.get("result", "")[:500],
                    details={"iterations": result.get("iterations"), "history": result.get("history")}
                ))

                # Check for success
                if result.get("completed") and not result.get("error"):
                    # Extract endpoint URL from result
                    endpoint_url = self._extract_endpoint_url(result.get("result", ""))

                    return DeploymentResult(
                        success=True,
                        status=DeploymentStatus.SUCCESS,
                        endpoint_url=endpoint_url,
                        service_name=request.service_name,
                        project_id=request.gcp_project_id,
                        region=request.region,
                        attempts=attempt,
                        steps=steps,
                        total_duration_seconds=time.time() - start_time
                    )
                else:
                    last_error = result.get("error") or result.get("result", "Unknown error")

                    # Try to get error analysis if we have monitor agent
                    if "monitor_agent" in self.agents and request.auto_fix:
                        try:
                            analysis_result = self.agents["monitor_agent"].run(
                                f"Analyze this deployment error and suggest fixes: {last_error}"
                            )
                            last_error_analysis = {"analysis": analysis_result}
                        except Exception as e:
                            logger.warning(f"Error analysis failed: {e}")

            except Exception as e:
                logger.error(f"Deployment attempt {attempt} exception: {e}")
                last_error = str(e)
                steps.append(DeploymentStep(
                    name=f"attempt_{attempt}",
                    status="error",
                    message=str(e)[:500]
                ))

        # All retries exhausted
        return DeploymentResult(
            success=False,
            status=DeploymentStatus.FAILED,
            service_name=request.service_name,
            project_id=request.gcp_project_id,
            region=request.region,
            attempts=request.max_retries,
            steps=steps,
            error=last_error,
            error_analysis=last_error_analysis,
            suggestions=self._generate_suggestions(last_error),
            total_duration_seconds=time.time() - start_time
        )

    def _extract_endpoint_url(self, result_text: str) -> Optional[str]:
        """Extract endpoint URL from deployment result"""
        import re

        # Look for Cloud Run URL patterns
        patterns = [
            r'https://[\w-]+-[\w-]+-[\w\.]+\.run\.app',
            r'https://[\w-]+\.[\w-]+\.run\.app',
            r'Service URL:\s*(https://[^\s]+)',
            r'Endpoint:\s*(https://[^\s]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, result_text, re.IGNORECASE)
            if match:
                return match.group(0) if match.group(0).startswith("https") else match.group(1)

        return None

    def _generate_suggestions(self, error: Optional[str]) -> List[str]:
        """Generate suggestions based on error"""
        if not error:
            return []

        error_lower = error.lower()
        suggestions = []

        if "permission" in error_lower or "denied" in error_lower:
            suggestions.append("Check service account permissions for Cloud Run and Cloud Build")
            suggestions.append("Ensure the service account has 'Cloud Run Admin' and 'Cloud Build Editor' roles")

        if "dockerfile" in error_lower or "build" in error_lower:
            suggestions.append("Verify Dockerfile exists and is valid")
            suggestions.append("Check that all dependencies are properly specified")

        if "quota" in error_lower or "limit" in error_lower:
            suggestions.append("Check GCP quotas for Cloud Run in your region")
            suggestions.append("Consider using a different region if quota is exceeded")

        if "secret" in error_lower:
            suggestions.append("Verify secrets exist in GCP Secret Manager")
            suggestions.append("Ensure service account has 'Secret Manager Secret Accessor' role")

        if "api" in error_lower and "enable" in error_lower:
            suggestions.append("Enable required GCP APIs: Cloud Run, Cloud Build, Secret Manager")
            suggestions.append("Use: gcloud services enable run.googleapis.com cloudbuild.googleapis.com")

        if not suggestions:
            suggestions.append("Check deployment logs for detailed error information")
            suggestions.append("Verify GCP project configuration and permissions")

        return suggestions

    def analyze_project(self, project_path: str) -> TechStackAnalysis:
        """
        Analyze project without deploying.

        Args:
            project_path: Path to project

        Returns:
            TechStackAnalysis with detected tech stack
        """
        if "code_analyzer" not in self.agents:
            raise WorkflowExecutionError("Code analyzer agent not available")

        result = self.agents["code_analyzer"].run(
            f"Analyze the project at '{project_path}' and report the tech stack, "
            f"framework, runtime, and deployment requirements."
        )

        # Parse result (basic extraction)
        return TechStackAnalysis(
            language=self._extract_field(result, "language"),
            framework=self._extract_field(result, "framework"),
            runtime=self._extract_field(result, "runtime"),
            has_dockerfile=Path(project_path, "Dockerfile").exists(),
            has_cloudbuild=Path(project_path, "cloudbuild.yaml").exists()
        )

    def _extract_field(self, text: str, field: str) -> Optional[str]:
        """Extract field value from text"""
        import re
        pattern = rf'{field}[:\s]+([^\n,]+)'
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def get_available_agents(self) -> List[str]:
        """Get list of available agent names"""
        return list(self.agents.keys())

    def get_agent_info(self) -> Dict[str, Any]:
        """Get information about all agents"""
        return {
            name: {
                "tools": [t.name for t in agent.tools],
                "model": agent.model_name
            }
            for name, agent in self.agents.items()
        }

    def __repr__(self) -> str:
        return f"<DeploymentOrchestrator(agents={len(self.agents)}, model='{self.model}')>"


# =============================================================================
# Convenience Functions
# =============================================================================

def deploy_to_cloud_run(
    project_path: str = ".",
    gcp_project_id: Optional[str] = None,
    region: str = "us-central1",
    service_name: Optional[str] = None,
    env_file: Optional[str] = None,
    push_to_git: bool = False,
    commit_message: Optional[str] = None
) -> DeploymentResult:
    """
    Quick deployment to Cloud Run.

    Args:
        project_path: Path to project source
        gcp_project_id: GCP project ID
        region: GCP region
        service_name: Service name
        env_file: Path to .env file
        push_to_git: Push to git before deploy
        commit_message: Git commit message

    Returns:
        DeploymentResult
    """
    orchestrator = DeploymentOrchestrator()

    request = DeploymentRequest(
        project_path=project_path,
        gcp_project_id=gcp_project_id,
        target=DeploymentTarget.CLOUD_RUN,
        region=region,
        service_name=service_name,
        env_file=env_file,
        sync_secrets=bool(env_file),
        push_to_git=push_to_git,
        commit_message=commit_message
    )

    return orchestrator.deploy(request)
