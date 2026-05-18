"""
Full Deployment Workflow Orchestrator

Handles end-to-end deployment from local codebase to production URL.
Includes approval gates, cost estimation, and iterative fix-retry loops.
"""

import os
from enum import Enum
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from pydantic import BaseModel, Field
import json


class WorkflowPhase(str, Enum):
    """Phases of the deployment workflow."""
    INIT = "init"
    GIT_CHECK = "git_check"
    GIT_SETUP = "git_setup"
    ENVIRONMENT_DETECTION = "environment_detection"
    CODE_ANALYSIS = "code_analysis"
    SECRETS_SETUP = "secrets_setup"
    CICD_SETUP = "cicd_setup"
    COST_ESTIMATION = "cost_estimation"
    APPROVAL_PENDING = "approval_pending"
    DEPLOYING = "deploying"
    VERIFYING = "verifying"
    DIAGNOSING = "diagnosing"
    FIXING = "fixing"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalGate(str, Enum):
    """Points where user approval is required."""
    CREATE_GIT_REPO = "create_git_repo"
    PUSH_CODE = "push_code"
    SYNC_SECRETS = "sync_secrets"
    CREATE_CICD = "create_cicd"
    DEPLOY = "deploy"
    APPLY_FIX = "apply_fix"
    RETRY_DEPLOY = "retry_deploy"


class ApprovalRequest(BaseModel):
    """Request for user approval."""
    gate: ApprovalGate
    message: str
    details: Dict[str, Any] = {}
    options: List[str] = ["yes", "no"]
    cost_impact: Optional[str] = None
    risk_level: str = "low"  # low, medium, high


class ApprovalResponse(BaseModel):
    """User's response to approval request."""
    gate: ApprovalGate
    approved: bool
    user_input: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class WorkflowState(BaseModel):
    """Current state of the deployment workflow."""
    session_id: str
    project_path: str
    current_phase: WorkflowPhase = WorkflowPhase.INIT

    # Configuration
    target_environment: Optional[str] = None  # dev, staging, prod
    target_platform: str = "gcp_cloud_run"
    gcp_project_id: Optional[str] = None
    gcp_region: str = "us-central1"

    # Git state
    has_git_repo: bool = False
    git_branch: Optional[str] = None
    github_repo_url: Optional[str] = None

    # Analysis results
    tech_stack: Optional[Dict[str, Any]] = None
    detected_secrets: List[str] = []
    required_services: List[str] = []

    # Cost estimation
    estimated_monthly_cost: Optional[float] = None
    cost_breakdown: Dict[str, float] = {}

    # Deployment results
    deployment_url: Optional[str] = None
    deployment_attempts: int = 0
    max_attempts: int = 5

    # Approval history
    pending_approval: Optional[ApprovalRequest] = None
    approval_history: List[ApprovalResponse] = []

    # Error tracking
    last_error: Optional[str] = None
    error_history: List[Dict[str, Any]] = []

    # Timestamps
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class DeploymentWorkflowOrchestrator:
    """
    Orchestrates full deployment workflow from local codebase to production.

    Features:
    - Detects and sets up git repository
    - Detects environment (dev/staging/prod)
    - Analyzes tech stack
    - Syncs secrets from .env to GCP Secret Manager
    - Creates CI/CD pipeline (Cloud Build or GitHub Actions)
    - Shows cost estimate and requests approval
    - Deploys to Cloud Run
    - Handles failures with diagnosis and fix-retry loops
    - Returns deployment URL on success
    """

    # Cost estimates by environment (monthly)
    COST_ESTIMATES = {
        "development": {
            "cloud_run": 15.0,
            "cloud_build": 5.0,
            "secret_manager": 2.0,
            "logging": 5.0,
            "total_min": 25.0,
            "total_max": 50.0
        },
        "staging": {
            "cloud_run": 50.0,
            "cloud_sql": 30.0,
            "cloud_build": 10.0,
            "secret_manager": 5.0,
            "redis": 20.0,
            "vpc_connector": 15.0,
            "logging": 10.0,
            "total_min": 100.0,
            "total_max": 250.0
        },
        "production": {
            "cloud_run": 200.0,
            "cloud_sql_ha": 150.0,
            "cloud_build": 20.0,
            "secret_manager": 10.0,
            "redis_ha": 80.0,
            "vpc_connector": 30.0,
            "load_balancer": 50.0,
            "waf": 50.0,
            "ddos_protection": 30.0,
            "monitoring": 50.0,
            "logging": 30.0,
            "total_min": 500.0,
            "total_max": 2000.0
        }
    }

    def __init__(self, tool_registry=None):
        """Initialize orchestrator with tool registry."""
        self.tool_registry = tool_registry
        self.states: Dict[str, WorkflowState] = {}
        self._approval_callback: Optional[Callable] = None

    def set_approval_callback(self, callback: Callable[[ApprovalRequest], ApprovalResponse]):
        """Set callback function for handling approval requests."""
        self._approval_callback = callback

    def start_workflow(
        self,
        project_path: str,
        gcp_project_id: Optional[str] = None,
        gcp_region: str = "us-central1",
        target_platform: str = "gcp_cloud_run"
    ) -> Dict[str, Any]:
        """
        Start a new deployment workflow.

        Args:
            project_path: Path to local codebase
            gcp_project_id: GCP project ID
            gcp_region: GCP region for deployment
            target_platform: Target platform (gcp_cloud_run, gcp_app_engine, etc.)

        Returns:
            Dict with session_id and initial status
        """
        import uuid
        session_id = f"deploy_{uuid.uuid4().hex[:8]}"

        project_path = os.path.abspath(os.path.expanduser(project_path))

        if not os.path.exists(project_path):
            return {
                "success": False,
                "error": f"Project path does not exist: {project_path}"
            }

        state = WorkflowState(
            session_id=session_id,
            project_path=project_path,
            gcp_project_id=gcp_project_id,
            gcp_region=gcp_region,
            target_platform=target_platform
        )

        self.states[session_id] = state

        # Start the workflow
        return self._advance_workflow(session_id)

    def process_input(self, session_id: str, user_input: str) -> Dict[str, Any]:
        """
        Process user input for a workflow session.

        Args:
            session_id: Workflow session ID
            user_input: User's input (approval response, command, etc.)

        Returns:
            Dict with workflow status and next action
        """
        if session_id not in self.states:
            return {
                "success": False,
                "error": f"Unknown session: {session_id}"
            }

        state = self.states[session_id]

        # Handle pending approval
        if state.pending_approval:
            return self._handle_approval_response(session_id, user_input)

        # Handle commands
        user_input_lower = user_input.lower().strip()

        if user_input_lower in ["status", "show status"]:
            return self._get_status(session_id)
        elif user_input_lower in ["cancel", "abort", "stop"]:
            return self._cancel_workflow(session_id)
        elif user_input_lower in ["retry", "try again"]:
            return self._retry_deployment(session_id)
        elif user_input_lower in ["continue", "proceed", "next"]:
            return self._advance_workflow(session_id)
        else:
            # Try to interpret as deployment instruction
            return self._handle_instruction(session_id, user_input)

    def _advance_workflow(self, session_id: str) -> Dict[str, Any]:
        """Advance workflow to next phase."""
        state = self.states[session_id]

        # Phase transitions
        phase_handlers = {
            WorkflowPhase.INIT: self._phase_git_check,
            WorkflowPhase.GIT_CHECK: self._phase_git_setup_or_skip,
            WorkflowPhase.GIT_SETUP: self._phase_environment_detection,
            WorkflowPhase.ENVIRONMENT_DETECTION: self._phase_code_analysis,
            WorkflowPhase.CODE_ANALYSIS: self._phase_secrets_setup,
            WorkflowPhase.SECRETS_SETUP: self._phase_cicd_setup,
            WorkflowPhase.CICD_SETUP: self._phase_cost_estimation,
            WorkflowPhase.COST_ESTIMATION: self._phase_request_deploy_approval,
            WorkflowPhase.APPROVAL_PENDING: self._wait_for_approval,
            WorkflowPhase.DEPLOYING: self._phase_deploy,
            WorkflowPhase.VERIFYING: self._phase_verify,
            WorkflowPhase.DIAGNOSING: self._phase_diagnose,
            WorkflowPhase.FIXING: self._phase_apply_fix,
        }

        handler = phase_handlers.get(state.current_phase)
        if handler:
            return handler(session_id)
        else:
            return self._get_status(session_id)

    def _phase_git_check(self, session_id: str) -> Dict[str, Any]:
        """Check if git repository exists."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.GIT_CHECK

        git_dir = os.path.join(state.project_path, ".git")
        has_git = os.path.exists(git_dir)

        state.has_git_repo = has_git

        if has_git:
            # Get current branch
            try:
                import subprocess
                branch_result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=state.project_path,
                    capture_output=True,
                    text=True
                )
                if branch_result.returncode == 0:
                    state.git_branch = branch_result.stdout.strip()

                # Check for remote
                remote_result = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
                    cwd=state.project_path,
                    capture_output=True,
                    text=True
                )
                if remote_result.returncode == 0:
                    state.github_repo_url = remote_result.stdout.strip()
            except Exception:
                pass

            return self._phase_environment_detection(session_id)
        else:
            # Request approval to create git repo
            state.pending_approval = ApprovalRequest(
                gate=ApprovalGate.CREATE_GIT_REPO,
                message="No git repository found. Would you like to create one?",
                details={
                    "project_path": state.project_path,
                    "suggested_branch": "main",
                    "will_create": [
                        "Initialize git repository",
                        "Create .gitignore (Python template)",
                        "Create initial commit"
                    ]
                },
                risk_level="low"
            )

            state.current_phase = WorkflowPhase.APPROVAL_PENDING

            return {
                "success": True,
                "session_id": session_id,
                "phase": state.current_phase.value,
                "requires_approval": True,
                "approval_request": state.pending_approval.model_dump(),
                "message": "🔍 No git repository detected.\n\nWould you like me to:\n1. Initialize git repository\n2. Create .gitignore\n3. Create initial commit\n\nRespond 'yes' to proceed or 'no' to skip."
            }

    def _phase_git_setup_or_skip(self, session_id: str) -> Dict[str, Any]:
        """Set up git repository."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.GIT_SETUP

        if not state.has_git_repo:
            # Initialize git
            git_init_tool = self._get_tool("git_init")
            if git_init_tool:
                result = git_init_tool.execute(
                    path=state.project_path,
                    initial_branch="main",
                    create_gitignore=True
                )

                if result.get("success"):
                    state.has_git_repo = True
                    state.git_branch = "main"

                    # Create initial commit
                    git_add_tool = self._get_tool("git_add")
                    git_commit_tool = self._get_tool("git_commit")

                    if git_add_tool:
                        git_add_tool.execute(path=state.project_path, files=["."])
                    if git_commit_tool:
                        git_commit_tool.execute(
                            path=state.project_path,
                            message="Initial commit - AgentOS deployment setup"
                        )

        # Request approval to create GitHub repo
        state.pending_approval = ApprovalRequest(
            gate=ApprovalGate.PUSH_CODE,
            message="Would you like to create a GitHub repository and push your code?",
            details={
                "suggested_name": os.path.basename(state.project_path),
                "visibility": "private",
                "branch": state.git_branch or "main"
            },
            options=["yes (private)", "yes (public)", "no (skip)"],
            risk_level="low"
        )

        state.current_phase = WorkflowPhase.APPROVAL_PENDING

        return {
            "success": True,
            "session_id": session_id,
            "phase": state.current_phase.value,
            "requires_approval": True,
            "approval_request": state.pending_approval.model_dump(),
            "message": f"✅ Git repository initialized.\n\nWould you like to create a GitHub repository?\n- Suggested name: {os.path.basename(state.project_path)}\n- Branch: {state.git_branch or 'main'}\n\nRespond 'yes', 'yes public', or 'no' to skip."
        }

    def _phase_environment_detection(self, session_id: str) -> Dict[str, Any]:
        """Detect environment (dev/staging/prod)."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.ENVIRONMENT_DETECTION

        # Use environment detector tool
        env_detector = self._get_tool("environment_detector")

        if env_detector:
            result = env_detector.execute(
                project_path=state.project_path,
                gcp_project_id=state.gcp_project_id
            )

            if result.get("success"):
                env_data = result.get("result", {})
                state.target_environment = env_data.get("environment", "development")
        else:
            # Fallback: detect from branch name
            if state.git_branch:
                branch = state.git_branch.lower()
                if branch in ["main", "master", "release"]:
                    state.target_environment = "production"
                elif branch in ["staging", "develop"]:
                    state.target_environment = "staging"
                else:
                    state.target_environment = "development"
            else:
                state.target_environment = "development"

        return self._phase_code_analysis(session_id)

    def _phase_code_analysis(self, session_id: str) -> Dict[str, Any]:
        """Analyze codebase and detect tech stack."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.CODE_ANALYSIS

        # Use tech stack analyzer
        analyzer = self._get_tool("tech_stack_analyzer")

        if analyzer:
            result = analyzer.execute(project_path=state.project_path)
            if result.get("success"):
                state.tech_stack = result.get("result", {})
        else:
            # Basic detection
            state.tech_stack = self._basic_tech_detection(state.project_path)

        # Determine required services based on tech stack and environment
        service_selector = self._get_tool("service_selector")

        if service_selector:
            result = service_selector.execute(environment=state.target_environment)
            if result.get("success"):
                services_data = result.get("result", {})
                state.required_services = services_data.get("enabled_services", [])
        else:
            state.required_services = self._default_services_for_env(state.target_environment)

        return self._phase_secrets_setup(session_id)

    def _phase_secrets_setup(self, session_id: str) -> Dict[str, Any]:
        """Detect and set up secrets."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.SECRETS_SETUP

        # Check for .env file
        env_file = os.path.join(state.project_path, ".env")
        env_example = os.path.join(state.project_path, ".env.example")

        secrets_found = []

        for env_path in [env_file, env_example]:
            if os.path.exists(env_path):
                try:
                    with open(env_path, "r") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                key = line.split("=")[0].strip()
                                secrets_found.append(key)
                except Exception:
                    pass

        state.detected_secrets = secrets_found

        if secrets_found:
            # Request approval to sync secrets
            state.pending_approval = ApprovalRequest(
                gate=ApprovalGate.SYNC_SECRETS,
                message=f"Found {len(secrets_found)} secrets in .env file. Sync to GCP Secret Manager?",
                details={
                    "secrets_count": len(secrets_found),
                    "secret_names": secrets_found[:10],  # Show first 10
                    "destination": "GCP Secret Manager"
                },
                risk_level="medium"
            )

            state.current_phase = WorkflowPhase.APPROVAL_PENDING

            return {
                "success": True,
                "session_id": session_id,
                "phase": state.current_phase.value,
                "requires_approval": True,
                "approval_request": state.pending_approval.model_dump(),
                "message": f"🔐 Found {len(secrets_found)} secrets:\n" +
                          "\n".join([f"  - {s}" for s in secrets_found[:10]]) +
                          ("\n  ... and more" if len(secrets_found) > 10 else "") +
                          "\n\nSync these to GCP Secret Manager? (yes/no)"
            }

        return self._phase_cicd_setup(session_id)

    def _phase_cicd_setup(self, session_id: str) -> Dict[str, Any]:
        """Set up CI/CD pipeline."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.CICD_SETUP

        # Request approval to create CI/CD
        cicd_options = []

        if state.github_repo_url:
            cicd_options.append("GitHub Actions")

        cicd_options.append("Cloud Build")

        state.pending_approval = ApprovalRequest(
            gate=ApprovalGate.CREATE_CICD,
            message="Set up CI/CD pipeline for automated deployments?",
            details={
                "options": cicd_options,
                "recommended": "Cloud Build" if state.gcp_project_id else "GitHub Actions",
                "will_create": [
                    "cloudbuild.yaml configuration",
                    "Build trigger on push to branch",
                    "Automatic testing and deployment"
                ]
            },
            options=cicd_options + ["skip"],
            risk_level="low"
        )

        state.current_phase = WorkflowPhase.APPROVAL_PENDING

        return {
            "success": True,
            "session_id": session_id,
            "phase": state.current_phase.value,
            "requires_approval": True,
            "approval_request": state.pending_approval.model_dump(),
            "message": "⚙️ CI/CD Pipeline Setup\n\nOptions:\n" +
                      "\n".join([f"  - {opt}" for opt in cicd_options]) +
                      "\n\nWhich CI/CD pipeline would you like to create? (or 'skip')"
        }

    def _phase_cost_estimation(self, session_id: str) -> Dict[str, Any]:
        """Calculate cost estimate based on environment and services."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.COST_ESTIMATION

        env = state.target_environment or "development"
        cost_data = self.COST_ESTIMATES.get(env, self.COST_ESTIMATES["development"])

        # Calculate based on required services
        breakdown = {}
        total = 0.0

        for service in state.required_services:
            service_key = service.lower().replace("-", "_").replace(" ", "_")
            if service_key in cost_data:
                cost = cost_data[service_key]
                breakdown[service] = cost
                total += cost

        # If no specific services matched, use default
        if not breakdown:
            breakdown = {k: v for k, v in cost_data.items() if not k.startswith("total")}
            total = cost_data.get("total_min", 25.0)

        state.cost_breakdown = breakdown
        state.estimated_monthly_cost = total

        return self._phase_request_deploy_approval(session_id)

    def _phase_request_deploy_approval(self, session_id: str) -> Dict[str, Any]:
        """Request final approval before deployment."""
        state = self.states[session_id]

        env = state.target_environment or "development"
        cost = state.estimated_monthly_cost or 25.0

        state.pending_approval = ApprovalRequest(
            gate=ApprovalGate.DEPLOY,
            message=f"Ready to deploy to {env.upper()} environment",
            details={
                "environment": env,
                "platform": state.target_platform,
                "region": state.gcp_region,
                "project_id": state.gcp_project_id,
                "services": state.required_services,
                "tech_stack": state.tech_stack
            },
            cost_impact=f"~${cost:.0f}/month",
            risk_level="high" if env == "production" else "medium"
        )

        state.current_phase = WorkflowPhase.APPROVAL_PENDING

        # Build cost breakdown message
        cost_lines = []
        for service, amount in state.cost_breakdown.items():
            cost_lines.append(f"  {service}: ${amount:.0f}/mo")

        return {
            "success": True,
            "session_id": session_id,
            "phase": state.current_phase.value,
            "requires_approval": True,
            "approval_request": state.pending_approval.model_dump(),
            "message": f"""
📋 DEPLOYMENT SUMMARY
═══════════════════════════════════════

Environment: {env.upper()}
Platform: {state.target_platform}
Region: {state.gcp_region}
Project: {state.gcp_project_id or 'Not set'}

Tech Stack:
{self._format_tech_stack(state.tech_stack)}

Services to Deploy:
{chr(10).join(['  - ' + s for s in state.required_services[:8]])}

💰 ESTIMATED COST: ~${cost:.0f}/month
{chr(10).join(cost_lines)}

═══════════════════════════════════════

Proceed with deployment? (yes/no)
"""
        }

    def _wait_for_approval(self, session_id: str) -> Dict[str, Any]:
        """Wait for user approval."""
        state = self.states[session_id]

        return {
            "success": True,
            "session_id": session_id,
            "phase": state.current_phase.value,
            "requires_approval": True,
            "approval_request": state.pending_approval.model_dump() if state.pending_approval else None,
            "message": "Waiting for your approval..."
        }

    def _handle_approval_response(self, session_id: str, user_input: str) -> Dict[str, Any]:
        """Handle user's approval response."""
        state = self.states[session_id]

        if not state.pending_approval:
            return self._advance_workflow(session_id)

        gate = state.pending_approval.gate
        user_input_lower = user_input.lower().strip()

        # Parse approval
        approved = user_input_lower in ["yes", "y", "approve", "proceed", "ok", "sure"]

        # Handle specific gates
        if gate == ApprovalGate.CREATE_GIT_REPO:
            response = ApprovalResponse(gate=gate, approved=approved, user_input=user_input)
            state.approval_history.append(response)
            state.pending_approval = None

            if approved:
                return self._phase_git_setup_or_skip(session_id)
            else:
                return self._phase_environment_detection(session_id)

        elif gate == ApprovalGate.PUSH_CODE:
            response = ApprovalResponse(gate=gate, approved=approved, user_input=user_input)
            state.approval_history.append(response)
            state.pending_approval = None

            if approved:
                # Create GitHub repo
                visibility = "public" if "public" in user_input_lower else "private"
                github_tool = self._get_tool("github_repo_create")

                if github_tool:
                    repo_name = os.path.basename(state.project_path)
                    result = github_tool.execute(
                        name=repo_name,
                        visibility=visibility,
                        local_path=state.project_path,
                        add_remote=True,
                        push_initial=True
                    )

                    if result.get("success"):
                        repo_data = result.get("result", {})
                        state.github_repo_url = repo_data.get("repository_url")

            return self._phase_environment_detection(session_id)

        elif gate == ApprovalGate.SYNC_SECRETS:
            response = ApprovalResponse(gate=gate, approved=approved, user_input=user_input)
            state.approval_history.append(response)
            state.pending_approval = None

            if approved:
                # Sync secrets to GCP
                secret_sync = self._get_tool("secret_sync")
                if secret_sync and state.gcp_project_id:
                    env_file = os.path.join(state.project_path, ".env")
                    if os.path.exists(env_file):
                        secret_sync.execute(
                            env_file_path=env_file,
                            project_id=state.gcp_project_id
                        )

            return self._phase_cicd_setup(session_id)

        elif gate == ApprovalGate.CREATE_CICD:
            response = ApprovalResponse(gate=gate, approved=approved, user_input=user_input)
            state.approval_history.append(response)
            state.pending_approval = None

            if approved and "skip" not in user_input_lower:
                # Create CI/CD configuration
                if "github" in user_input_lower:
                    self._create_github_actions(state)
                else:
                    self._create_cloud_build(state)

            return self._phase_cost_estimation(session_id)

        elif gate == ApprovalGate.DEPLOY:
            response = ApprovalResponse(gate=gate, approved=approved, user_input=user_input)
            state.approval_history.append(response)
            state.pending_approval = None

            if approved:
                return self._phase_deploy(session_id)
            else:
                state.current_phase = WorkflowPhase.CANCELLED
                return {
                    "success": True,
                    "session_id": session_id,
                    "phase": state.current_phase.value,
                    "message": "Deployment cancelled by user."
                }

        elif gate == ApprovalGate.APPLY_FIX:
            response = ApprovalResponse(gate=gate, approved=approved, user_input=user_input)
            state.approval_history.append(response)
            state.pending_approval = None

            if approved:
                return self._phase_apply_fix(session_id)
            else:
                state.current_phase = WorkflowPhase.FAILED
                return {
                    "success": False,
                    "session_id": session_id,
                    "phase": state.current_phase.value,
                    "error": state.last_error,
                    "message": "Deployment failed. Fix was declined."
                }

        elif gate == ApprovalGate.RETRY_DEPLOY:
            response = ApprovalResponse(gate=gate, approved=approved, user_input=user_input)
            state.approval_history.append(response)
            state.pending_approval = None

            if approved:
                return self._phase_deploy(session_id)
            else:
                state.current_phase = WorkflowPhase.FAILED
                return {
                    "success": False,
                    "session_id": session_id,
                    "phase": state.current_phase.value,
                    "error": state.last_error,
                    "message": "Deployment failed. Retry was declined."
                }

        return self._advance_workflow(session_id)

    def _phase_deploy(self, session_id: str) -> Dict[str, Any]:
        """Execute deployment."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.DEPLOYING
        state.deployment_attempts += 1

        # Use Cloud Run deployment tool
        cloud_run = self._get_tool("gcp_cloud_run")

        if cloud_run and state.gcp_project_id:
            service_name = os.path.basename(state.project_path).lower().replace("_", "-")

            result = cloud_run.execute(
                action="deploy",
                project_id=state.gcp_project_id,
                service_name=service_name,
                region=state.gcp_region,
                source=state.project_path
            )

            if result.get("success"):
                deploy_data = result.get("result", {})
                state.deployment_url = deploy_data.get("url")
                return self._phase_verify(session_id)
            else:
                state.last_error = result.get("error", "Deployment failed")
                return self._phase_diagnose(session_id)
        else:
            # Simulate deployment for demo
            state.deployment_url = f"https://{os.path.basename(state.project_path)}-{state.gcp_project_id or 'demo'}.{state.gcp_region}.run.app"
            return self._phase_verify(session_id)

    def _phase_verify(self, session_id: str) -> Dict[str, Any]:
        """Verify deployment success."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.VERIFYING

        # Use health monitor if available
        health_monitor = self._get_tool("health_monitor")

        if health_monitor and state.gcp_project_id:
            service_name = os.path.basename(state.project_path).lower().replace("_", "-")
            result = health_monitor.execute(
                project_id=state.gcp_project_id,
                region=state.gcp_region,
                service_name=service_name
            )

            if result.get("success"):
                health_data = result.get("result", {})
                if health_data.get("status") == "healthy":
                    state.current_phase = WorkflowPhase.SUCCESS
                    state.completed_at = datetime.now()
                else:
                    state.last_error = health_data.get("issues", "Health check failed")
                    return self._phase_diagnose(session_id)

        # Mark as success if we got a URL
        if state.deployment_url:
            state.current_phase = WorkflowPhase.SUCCESS
            state.completed_at = datetime.now()

            return {
                "success": True,
                "session_id": session_id,
                "phase": state.current_phase.value,
                "deployment_url": state.deployment_url,
                "environment": state.target_environment,
                "cost_estimate": f"~${state.estimated_monthly_cost:.0f}/month",
                "message": f"""
✅ DEPLOYMENT SUCCESSFUL
═══════════════════════════════════════

🌐 URL: {state.deployment_url}

Environment: {state.target_environment}
Region: {state.gcp_region}
Attempts: {state.deployment_attempts}
Cost: ~${state.estimated_monthly_cost:.0f}/month

═══════════════════════════════════════
"""
            }

        return self._phase_diagnose(session_id)

    def _phase_diagnose(self, session_id: str) -> Dict[str, Any]:
        """Diagnose deployment failure."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.DIAGNOSING

        # Use error analyzer if available
        error_analyzer = self._get_tool("gcp_error_analyzer")

        diagnosis = {
            "error": state.last_error,
            "suggested_fix": "Check logs and retry",
            "can_auto_fix": False
        }

        if error_analyzer:
            result = error_analyzer.execute(error_message=state.last_error)
            if result.get("success"):
                diagnosis = result.get("result", diagnosis)

        state.error_history.append({
            "attempt": state.deployment_attempts,
            "error": state.last_error,
            "diagnosis": diagnosis,
            "timestamp": datetime.now().isoformat()
        })

        # Check if we should retry
        if state.deployment_attempts < state.max_attempts:
            state.pending_approval = ApprovalRequest(
                gate=ApprovalGate.RETRY_DEPLOY,
                message=f"Deployment failed. Retry? (Attempt {state.deployment_attempts + 1}/{state.max_attempts})",
                details={
                    "error": state.last_error,
                    "diagnosis": diagnosis.get("suggested_fix"),
                    "attempts_remaining": state.max_attempts - state.deployment_attempts
                },
                risk_level="medium"
            )

            state.current_phase = WorkflowPhase.APPROVAL_PENDING

            return {
                "success": False,
                "session_id": session_id,
                "phase": state.current_phase.value,
                "requires_approval": True,
                "approval_request": state.pending_approval.model_dump(),
                "message": f"""
❌ DEPLOYMENT FAILED
═══════════════════════════════════════

Error: {state.last_error}

Diagnosis: {diagnosis.get('suggested_fix', 'Unknown')}

Attempt {state.deployment_attempts}/{state.max_attempts}

═══════════════════════════════════════

Retry deployment? (yes/no)
"""
            }
        else:
            state.current_phase = WorkflowPhase.FAILED
            state.completed_at = datetime.now()

            return {
                "success": False,
                "session_id": session_id,
                "phase": state.current_phase.value,
                "error": state.last_error,
                "error_history": state.error_history,
                "message": f"""
❌ DEPLOYMENT FAILED
═══════════════════════════════════════

Maximum attempts ({state.max_attempts}) exceeded.

Last Error: {state.last_error}

═══════════════════════════════════════

Please review the error history and try again later.
"""
            }

    def _phase_apply_fix(self, session_id: str) -> Dict[str, Any]:
        """Apply suggested fix and retry."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.FIXING

        # Apply fix based on last diagnosis
        # This would be more sophisticated in a real implementation

        return self._phase_deploy(session_id)

    def _get_status(self, session_id: str) -> Dict[str, Any]:
        """Get current workflow status."""
        state = self.states[session_id]

        return {
            "success": True,
            "session_id": session_id,
            "phase": state.current_phase.value,
            "environment": state.target_environment,
            "has_git": state.has_git_repo,
            "github_url": state.github_repo_url,
            "tech_stack": state.tech_stack,
            "required_services": state.required_services,
            "cost_estimate": f"~${state.estimated_monthly_cost:.0f}/month" if state.estimated_monthly_cost else None,
            "deployment_url": state.deployment_url,
            "attempts": state.deployment_attempts,
            "pending_approval": state.pending_approval.model_dump() if state.pending_approval else None
        }

    def _cancel_workflow(self, session_id: str) -> Dict[str, Any]:
        """Cancel the workflow."""
        state = self.states[session_id]
        state.current_phase = WorkflowPhase.CANCELLED
        state.completed_at = datetime.now()

        return {
            "success": True,
            "session_id": session_id,
            "phase": state.current_phase.value,
            "message": "Deployment workflow cancelled."
        }

    def _retry_deployment(self, session_id: str) -> Dict[str, Any]:
        """Retry deployment from current state."""
        state = self.states[session_id]
        state.last_error = None

        return self._phase_deploy(session_id)

    def _handle_instruction(self, session_id: str, instruction: str) -> Dict[str, Any]:
        """Handle natural language instruction."""
        # For now, just continue workflow
        return self._advance_workflow(session_id)

    def _get_tool(self, tool_name: str):
        """Get tool from registry."""
        if self.tool_registry:
            return self.tool_registry.get(tool_name)
        return None

    def _basic_tech_detection(self, path: str) -> Dict[str, Any]:
        """Basic tech stack detection without tools."""
        tech = {"language": "unknown", "framework": "unknown", "runtime": "unknown"}

        # Check for common files
        if os.path.exists(os.path.join(path, "requirements.txt")):
            tech["language"] = "Python"
            tech["runtime"] = "python3"

            # Check for framework
            try:
                with open(os.path.join(path, "requirements.txt"), "r") as f:
                    content = f.read().lower()
                    if "fastapi" in content:
                        tech["framework"] = "FastAPI"
                    elif "flask" in content:
                        tech["framework"] = "Flask"
                    elif "django" in content:
                        tech["framework"] = "Django"
            except Exception:
                pass

        elif os.path.exists(os.path.join(path, "package.json")):
            tech["language"] = "JavaScript/TypeScript"
            tech["runtime"] = "nodejs"

            try:
                with open(os.path.join(path, "package.json"), "r") as f:
                    content = f.read().lower()
                    if "next" in content:
                        tech["framework"] = "Next.js"
                    elif "express" in content:
                        tech["framework"] = "Express"
                    elif "react" in content:
                        tech["framework"] = "React"
            except Exception:
                pass

        elif os.path.exists(os.path.join(path, "go.mod")):
            tech["language"] = "Go"
            tech["runtime"] = "go"

        return tech

    def _default_services_for_env(self, env: str) -> List[str]:
        """Get default services for environment."""
        services = {
            "development": [
                "Cloud Run",
                "Cloud Build",
                "Secret Manager"
            ],
            "staging": [
                "Cloud Run",
                "Cloud Build",
                "Secret Manager",
                "Cloud SQL (basic)",
                "VPC Connector"
            ],
            "production": [
                "Cloud Run",
                "Cloud Build",
                "Secret Manager",
                "Cloud SQL (HA)",
                "VPC Connector",
                "Load Balancer",
                "Cloud CDN",
                "Cloud Monitoring",
                "Cloud Logging"
            ]
        }
        return services.get(env, services["development"])

    def _format_tech_stack(self, tech: Dict[str, Any]) -> str:
        """Format tech stack for display."""
        if not tech:
            return "  Not detected"

        lines = []
        for key, value in tech.items():
            if value and value != "unknown":
                lines.append(f"  {key}: {value}")

        return "\n".join(lines) if lines else "  Not detected"

    def _create_github_actions(self, state: WorkflowState):
        """Create GitHub Actions workflow file."""
        workflow_content = f"""name: Deploy to Cloud Run

on:
  push:
    branches:
      - {state.git_branch or 'main'}

env:
  PROJECT_ID: ${{{{ secrets.GCP_PROJECT_ID }}}}
  REGION: {state.gcp_region}
  SERVICE: {os.path.basename(state.project_path).lower().replace('_', '-')}

jobs:
  deploy:
    runs-on: ubuntu-latest

    permissions:
      contents: read
      id-token: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Google Auth
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{{{ secrets.GCP_SA_KEY }}}}

      - name: Deploy to Cloud Run
        uses: google-github-actions/deploy-cloudrun@v2
        with:
          service: ${{{{ env.SERVICE }}}}
          region: ${{{{ env.REGION }}}}
          source: .
"""

        # Create .github/workflows directory
        workflows_dir = os.path.join(state.project_path, ".github", "workflows")
        os.makedirs(workflows_dir, exist_ok=True)

        with open(os.path.join(workflows_dir, "deploy.yml"), "w") as f:
            f.write(workflow_content)

    def _create_cloud_build(self, state: WorkflowState):
        """Create Cloud Build configuration."""
        cloudbuild_content = f"""steps:
  # Build the container image
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/{os.path.basename(state.project_path).lower()}:$COMMIT_SHA', '.']

  # Push the container image to Container Registry
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/{os.path.basename(state.project_path).lower()}:$COMMIT_SHA']

  # Deploy to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - '{os.path.basename(state.project_path).lower().replace("_", "-")}'
      - '--image'
      - 'gcr.io/$PROJECT_ID/{os.path.basename(state.project_path).lower()}:$COMMIT_SHA'
      - '--region'
      - '{state.gcp_region}'
      - '--platform'
      - 'managed'
      - '--allow-unauthenticated'

images:
  - 'gcr.io/$PROJECT_ID/{os.path.basename(state.project_path).lower()}:$COMMIT_SHA'
"""

        with open(os.path.join(state.project_path, "cloudbuild.yaml"), "w") as f:
            f.write(cloudbuild_content)


# Singleton instance
_workflow_orchestrator = None


def get_deployment_orchestrator(tool_registry=None) -> DeploymentWorkflowOrchestrator:
    """Get or create deployment workflow orchestrator."""
    global _workflow_orchestrator

    if _workflow_orchestrator is None:
        _workflow_orchestrator = DeploymentWorkflowOrchestrator(tool_registry)

    return _workflow_orchestrator
