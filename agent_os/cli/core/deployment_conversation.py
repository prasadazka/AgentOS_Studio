"""
Deployment Conversation Manager for AgentOS

Enables iterative conversational deployment workflow:
User → Deploy → Fail → Diagnose → Fix → Retry → Success

Maintains deployment state across conversation turns and automatically
guides users through troubleshooting until deployment succeeds.
"""

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agent_os.tools.global_registry import get_global_registry


class DeploymentPhase(str, Enum):
    """Current phase in deployment workflow"""
    NOT_STARTED = "not_started"
    ANALYZING = "analyzing"
    SECURITY_SCAN = "security_scan"
    BUILDING = "building"
    DEPLOYING = "deploying"
    VERIFYING = "verifying"
    DIAGNOSING = "diagnosing"
    FIXING = "fixing"
    RETRYING = "retrying"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeploymentAttempt(BaseModel):
    """Record of a single deployment attempt"""
    attempt_number: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    phase_reached: DeploymentPhase
    success: bool = False
    error_message: Optional[str] = None
    error_logs: Optional[str] = None
    diagnosis: Optional[str] = None
    fix_applied: Optional[str] = None


class DeploymentSession(BaseModel):
    """Persistent deployment session state"""
    session_id: str
    project_path: str
    target: str = "cloud_run"
    region: str = "us-central1"
    project_id: Optional[str] = None
    service_name: Optional[str] = None

    # State tracking
    current_phase: DeploymentPhase = DeploymentPhase.NOT_STARTED
    attempts: List[DeploymentAttempt] = Field(default_factory=list)
    max_attempts: int = 5

    # Analysis results
    tech_stack: Optional[Dict[str, Any]] = None
    security_issues: Optional[List[Dict]] = None

    # Deployment results
    endpoint_url: Optional[str] = None
    revision: Optional[str] = None

    # Conversation context
    last_user_message: Optional[str] = None
    pending_action: Optional[str] = None  # What we're waiting for user to confirm

    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    def get_attempt_count(self) -> int:
        return len(self.attempts)

    def can_retry(self) -> bool:
        return self.get_attempt_count() < self.max_attempts

    def is_complete(self) -> bool:
        return self.current_phase in [
            DeploymentPhase.SUCCESS,
            DeploymentPhase.FAILED,
            DeploymentPhase.CANCELLED
        ]


class DeploymentConversationManager:
    """
    Manages iterative deployment conversations.

    Enables users to have ongoing conversations about deployment:
    - Tracks deployment state across messages
    - Automatically diagnoses failures
    - Suggests fixes based on error patterns
    - Supports retry until success
    - Maintains full conversation context

    Usage:
        manager = DeploymentConversationManager()
        session = manager.start_session(project_path=".", target="cloud_run")

        # User says "deploy my app"
        response = manager.process_message(session.session_id, "deploy my app")

        # If deployment fails, user can say "what went wrong?"
        response = manager.process_message(session.session_id, "what went wrong?")

        # User can say "fix it" or "retry"
        response = manager.process_message(session.session_id, "fix it and retry")
    """

    # Error patterns and suggested fixes
    ERROR_PATTERNS = {
        "permission denied": {
            "diagnosis": "Missing IAM permissions",
            "fix_suggestion": "Grant Cloud Run Admin role to service account",
            "tool": "iam_validator",
        },
        "image not found": {
            "diagnosis": "Container image doesn't exist or wrong path",
            "fix_suggestion": "Build and push the image first using Cloud Build",
            "tool": "gcp_cloud_build",
        },
        "port 8080": {
            "diagnosis": "Application not listening on expected port",
            "fix_suggestion": "Ensure app listens on PORT env var or 8080",
            "tool": "cloud_run_config_reader",
        },
        "memory limit": {
            "diagnosis": "Container exceeded memory limit",
            "fix_suggestion": "Increase memory allocation or optimize app",
            "tool": "auto_scaling_config",
        },
        "timeout": {
            "diagnosis": "Container startup or request timeout",
            "fix_suggestion": "Increase timeout or optimize startup time",
            "tool": "health_check_config",
        },
        "secret": {
            "diagnosis": "Missing or inaccessible secret",
            "fix_suggestion": "Ensure secrets exist in Secret Manager and SA has access",
            "tool": "gcp_secret_manager",
        },
        "vpc": {
            "diagnosis": "VPC connector issue",
            "fix_suggestion": "Check VPC connector configuration and permissions",
            "tool": "vpc_config",
        },
        "quota": {
            "diagnosis": "GCP quota exceeded",
            "fix_suggestion": "Request quota increase or use different region",
            "tool": None,
        },
    }

    # Message patterns for intent detection
    MESSAGE_INTENTS = {
        "deploy": ["deploy", "push", "ship", "release", "launch"],
        "diagnose": ["what went wrong", "why fail", "error", "issue", "problem", "diagnose"],
        "fix": ["fix", "repair", "solve", "resolve"],
        "retry": ["retry", "try again", "redeploy", "again"],
        "status": ["status", "progress", "where", "how far"],
        "cancel": ["cancel", "stop", "abort", "quit"],
        "config": ["config", "setting", "change", "modify", "adjust"],
        "rollback": ["rollback", "revert", "previous", "undo"],
    }

    def __init__(self):
        self._sessions: Dict[str, DeploymentSession] = {}
        self._registry = get_global_registry()

    def start_session(
        self,
        project_path: str = ".",
        target: str = "cloud_run",
        region: str = "us-central1",
        project_id: Optional[str] = None,
        service_name: Optional[str] = None,
    ) -> DeploymentSession:
        """Start a new deployment conversation session"""
        import uuid

        session_id = str(uuid.uuid4())[:8]
        session = DeploymentSession(
            session_id=session_id,
            project_path=project_path,
            target=target,
            region=region,
            project_id=project_id,
            service_name=service_name,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[DeploymentSession]:
        """Get existing session by ID"""
        return self._sessions.get(session_id)

    def get_active_session(self) -> Optional[DeploymentSession]:
        """Get the most recent active (non-complete) session"""
        for session in reversed(list(self._sessions.values())):
            if not session.is_complete():
                return session
        return None

    def process_message(
        self,
        session_id: str,
        user_message: str
    ) -> Dict[str, Any]:
        """
        Process a user message in the deployment conversation.

        Returns:
            Dict with:
            - response: Text response to show user
            - action_taken: What action was performed
            - phase: Current deployment phase
            - needs_confirmation: If waiting for user confirmation
            - tools_to_run: List of tools that should be executed
        """
        session = self.get_session(session_id)
        if not session:
            return {
                "response": "No active deployment session. Start with 'deploy my app'.",
                "action_taken": None,
                "phase": None,
            }

        session.last_user_message = user_message
        intent = self._detect_intent(user_message)

        # Route based on intent
        if intent == "deploy":
            return self._handle_deploy(session)
        elif intent == "diagnose":
            return self._handle_diagnose(session)
        elif intent == "fix":
            return self._handle_fix(session)
        elif intent == "retry":
            return self._handle_retry(session)
        elif intent == "status":
            return self._handle_status(session)
        elif intent == "cancel":
            return self._handle_cancel(session)
        elif intent == "config":
            return self._handle_config_change(session, user_message)
        elif intent == "rollback":
            return self._handle_rollback(session)
        else:
            # General question about deployment
            return self._handle_general_query(session, user_message)

    def _detect_intent(self, message: str) -> str:
        """Detect user intent from message"""
        message_lower = message.lower()

        for intent, keywords in self.MESSAGE_INTENTS.items():
            for keyword in keywords:
                if keyword in message_lower:
                    return intent

        return "general"

    def _handle_deploy(self, session: DeploymentSession) -> Dict[str, Any]:
        """Handle deploy intent"""
        if session.current_phase == DeploymentPhase.SUCCESS:
            return {
                "response": f"Deployment already succeeded! Endpoint: {session.endpoint_url}\nSay 'redeploy' to deploy again.",
                "action_taken": None,
                "phase": session.current_phase,
            }

        if not session.can_retry():
            return {
                "response": f"Max attempts ({session.max_attempts}) reached. Review errors and start a new session.",
                "action_taken": None,
                "phase": session.current_phase,
            }

        # Start deployment workflow
        attempt = DeploymentAttempt(
            attempt_number=session.get_attempt_count() + 1,
            started_at=datetime.utcnow(),
            phase_reached=DeploymentPhase.ANALYZING,
        )
        session.attempts.append(attempt)
        session.current_phase = DeploymentPhase.ANALYZING

        return {
            "response": self._generate_deploy_plan(session),
            "action_taken": "start_deployment",
            "phase": session.current_phase,
            "tools_to_run": self._get_deployment_tools(session),
        }

    def _handle_diagnose(self, session: DeploymentSession) -> Dict[str, Any]:
        """Handle diagnose intent - analyze what went wrong"""
        if not session.attempts:
            return {
                "response": "No deployment attempts yet. Say 'deploy' to start.",
                "action_taken": None,
                "phase": session.current_phase,
            }

        last_attempt = session.attempts[-1]
        if last_attempt.success:
            return {
                "response": "Last deployment was successful! No errors to diagnose.",
                "action_taken": None,
                "phase": session.current_phase,
            }

        session.current_phase = DeploymentPhase.DIAGNOSING

        # Analyze error
        diagnosis = self._diagnose_error(last_attempt.error_message or "", last_attempt.error_logs or "")
        last_attempt.diagnosis = diagnosis["diagnosis"]

        return {
            "response": self._format_diagnosis(diagnosis, last_attempt),
            "action_taken": "diagnose",
            "phase": session.current_phase,
            "tools_to_run": [
                {"tool": "health_monitor", "params": {"service_name": session.service_name}},
                {"tool": "cloud_run_logs", "params": {"service_name": session.service_name}},
            ] if session.service_name else [],
        }

    def _handle_fix(self, session: DeploymentSession) -> Dict[str, Any]:
        """Handle fix intent - apply suggested fix"""
        if not session.attempts:
            return {
                "response": "No deployment attempts yet. Say 'deploy' to start.",
                "action_taken": None,
                "phase": session.current_phase,
            }

        last_attempt = session.attempts[-1]
        if not last_attempt.diagnosis:
            # Need to diagnose first
            return self._handle_diagnose(session)

        session.current_phase = DeploymentPhase.FIXING

        # Get fix suggestion
        fix_info = self._get_fix_for_error(last_attempt.error_message or "")

        return {
            "response": self._format_fix_plan(fix_info, session),
            "action_taken": "propose_fix",
            "phase": session.current_phase,
            "needs_confirmation": True,
            "tools_to_run": [fix_info] if fix_info.get("tool") else [],
        }

    def _handle_retry(self, session: DeploymentSession) -> Dict[str, Any]:
        """Handle retry intent"""
        if not session.can_retry():
            return {
                "response": f"Max attempts ({session.max_attempts}) reached. Start a new session.",
                "action_taken": None,
                "phase": session.current_phase,
            }

        session.current_phase = DeploymentPhase.RETRYING
        return self._handle_deploy(session)

    def _handle_status(self, session: DeploymentSession) -> Dict[str, Any]:
        """Handle status intent"""
        return {
            "response": self._format_status(session),
            "action_taken": "show_status",
            "phase": session.current_phase,
        }

    def _handle_cancel(self, session: DeploymentSession) -> Dict[str, Any]:
        """Handle cancel intent"""
        session.current_phase = DeploymentPhase.CANCELLED
        session.completed_at = datetime.utcnow()

        return {
            "response": "Deployment cancelled. Start a new session when ready.",
            "action_taken": "cancel",
            "phase": session.current_phase,
        }

    def _handle_config_change(self, session: DeploymentSession, message: str) -> Dict[str, Any]:
        """Handle configuration change requests"""
        return {
            "response": self._format_config_options(session),
            "action_taken": "show_config",
            "phase": session.current_phase,
            "tools_to_run": [
                {"tool": "cloud_run_config_reader", "params": {"service_name": session.service_name}}
            ] if session.service_name else [],
        }

    def _handle_rollback(self, session: DeploymentSession) -> Dict[str, Any]:
        """Handle rollback intent"""
        if not session.service_name:
            return {
                "response": "No service deployed yet. Nothing to rollback.",
                "action_taken": None,
                "phase": session.current_phase,
            }

        return {
            "response": f"Rolling back {session.service_name} to previous revision...",
            "action_taken": "rollback",
            "phase": session.current_phase,
            "needs_confirmation": True,
            "tools_to_run": [
                {"tool": "rollback", "params": {
                    "service_name": session.service_name,
                    "region": session.region,
                }}
            ],
        }

    def _handle_general_query(self, session: DeploymentSession, message: str) -> Dict[str, Any]:
        """Handle general questions about deployment"""
        # Provide context-aware response
        context = f"""
Current deployment status:
- Project: {session.project_path}
- Target: {session.target}
- Region: {session.region}
- Phase: {session.current_phase.value}
- Attempts: {session.get_attempt_count()}/{session.max_attempts}
"""
        if session.endpoint_url:
            context += f"- Endpoint: {session.endpoint_url}\n"

        return {
            "response": f"I can help with your deployment.\n{context}\nYou can ask: 'deploy', 'what went wrong?', 'fix it', 'retry', 'status', 'rollback', or 'cancel'",
            "action_taken": "help",
            "phase": session.current_phase,
        }

    def _diagnose_error(self, error_message: str, error_logs: str) -> Dict[str, Any]:
        """Analyze error and return diagnosis"""
        combined = f"{error_message} {error_logs}".lower()

        for pattern, diagnosis_info in self.ERROR_PATTERNS.items():
            if pattern in combined:
                return diagnosis_info

        return {
            "diagnosis": "Unknown error - requires manual investigation",
            "fix_suggestion": "Check Cloud Logging for detailed error messages",
            "tool": "gcp_logging",
        }

    def _get_fix_for_error(self, error_message: str) -> Dict[str, Any]:
        """Get fix suggestion for error"""
        error_lower = error_message.lower()

        for pattern, fix_info in self.ERROR_PATTERNS.items():
            if pattern in error_lower:
                return fix_info

        return {
            "diagnosis": "Unknown error",
            "fix_suggestion": "Manual investigation required",
            "tool": None,
        }

    def _generate_deploy_plan(self, session: DeploymentSession) -> str:
        """Generate deployment plan message"""
        attempt_num = session.get_attempt_count()

        plan = f"""
{'=' * 50}
DEPLOYMENT ATTEMPT {attempt_num}/{session.max_attempts}
{'=' * 50}

Project: {session.project_path}
Target: {session.target}
Region: {session.region}

WORKFLOW:
1. [  ] Security scan (secret_scanner)
2. [  ] Analyze tech stack (tech_stack_analyzer)
3. [  ] Validate IAM permissions (iam_validator)
4. [  ] Build container (gcp_cloud_build)
5. [  ] Scan container (container_scanner)
6. [  ] Deploy to Cloud Run (gcp_cloud_run)
7. [  ] Verify health (health_monitor)

Starting deployment...
"""
        return plan

    def _format_diagnosis(self, diagnosis: Dict, attempt: DeploymentAttempt) -> str:
        """Format diagnosis for display"""
        return f"""
{'=' * 50}
DEPLOYMENT DIAGNOSIS
{'=' * 50}

Attempt #{attempt.attempt_number} - FAILED
Phase Reached: {attempt.phase_reached.value}

ERROR:
{attempt.error_message or 'No error message captured'}

DIAGNOSIS:
{diagnosis.get('diagnosis', 'Unknown')}

SUGGESTED FIX:
{diagnosis.get('fix_suggestion', 'Manual investigation required')}

Say 'fix it' to apply the suggested fix, or 'retry' to try again.
"""

    def _format_fix_plan(self, fix_info: Dict, session: DeploymentSession) -> str:
        """Format fix plan for confirmation"""
        return f"""
{'=' * 50}
PROPOSED FIX
{'=' * 50}

Issue: {fix_info.get('diagnosis', 'Unknown')}

Fix: {fix_info.get('fix_suggestion', 'N/A')}

Tool to use: {fix_info.get('tool', 'Manual')}

Say 'yes' to apply this fix, or 'no' to skip.
After fixing, say 'retry' to redeploy.
"""

    def _format_status(self, session: DeploymentSession) -> str:
        """Format current status"""
        status = f"""
{'=' * 50}
DEPLOYMENT STATUS
{'=' * 50}

Session: {session.session_id}
Project: {session.project_path}
Target: {session.target} ({session.region})
Phase: {session.current_phase.value}
Attempts: {session.get_attempt_count()}/{session.max_attempts}
"""

        if session.endpoint_url:
            status += f"\nEndpoint: {session.endpoint_url}"

        if session.attempts:
            last = session.attempts[-1]
            status += f"\n\nLast Attempt: {'SUCCESS' if last.success else 'FAILED'}"
            if last.error_message:
                status += f"\nError: {last.error_message[:100]}..."

        return status

    def _format_config_options(self, session: DeploymentSession) -> str:
        """Format configuration options"""
        return f"""
{'=' * 50}
DEPLOYMENT CONFIGURATION
{'=' * 50}

Current Settings:
- Project Path: {session.project_path}
- Target: {session.target}
- Region: {session.region}
- Project ID: {session.project_id or 'auto-detect'}
- Service Name: {session.service_name or 'auto-detect'}
- Max Attempts: {session.max_attempts}

You can change settings by saying:
- "change region to us-east1"
- "set max attempts to 10"
- "use project my-gcp-project"
"""

    def _get_deployment_tools(self, session: DeploymentSession) -> List[Dict]:
        """Get list of tools to run for deployment"""
        return [
            {"tool": "secret_scanner", "params": {"project_path": session.project_path}},
            {"tool": "tech_stack_analyzer", "params": {"project_path": session.project_path}},
            {"tool": "iam_validator", "params": {"project_id": session.project_id, "operation": "cloud_run_deploy"}},
            {"tool": "gcp_cloud_build", "params": {"project_id": session.project_id}},
            {"tool": "container_scanner", "params": {}},
            {"tool": "gcp_cloud_run", "params": {"region": session.region}},
            {"tool": "health_monitor", "params": {}},
        ]

    def record_attempt_result(
        self,
        session_id: str,
        success: bool,
        phase_reached: DeploymentPhase,
        error_message: Optional[str] = None,
        error_logs: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        """Record the result of a deployment attempt"""
        session = self.get_session(session_id)
        if not session or not session.attempts:
            return

        attempt = session.attempts[-1]
        attempt.completed_at = datetime.utcnow()
        attempt.success = success
        attempt.phase_reached = phase_reached
        attempt.error_message = error_message
        attempt.error_logs = error_logs

        if success:
            session.current_phase = DeploymentPhase.SUCCESS
            session.endpoint_url = endpoint_url
            session.completed_at = datetime.utcnow()
        else:
            session.current_phase = DeploymentPhase.FAILED


# Singleton instance for use across the application
_deployment_manager: Optional[DeploymentConversationManager] = None


def get_deployment_manager() -> DeploymentConversationManager:
    """Get or create the deployment conversation manager"""
    global _deployment_manager
    if _deployment_manager is None:
        _deployment_manager = DeploymentConversationManager()
    return _deployment_manager
