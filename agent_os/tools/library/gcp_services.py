"""GCP Cloud Services tools - API enablement, Cloud Run, Cloud Build"""

import subprocess
import shutil
import json
import time
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import ToolExecutionError, ErrorCode
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


def _quote_if_needed(s: str) -> str:
    """Quote a string if it contains spaces (for Windows shell commands)."""
    if " " in s and not (s.startswith('"') and s.endswith('"')):
        return f'"{s}"'
    return s


def run_gcloud(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    """Run gcloud command with Windows compatibility."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)

    if sys.platform == "win32":
        # Quote paths that contain spaces
        cmd_str = " ".join(_quote_if_needed(c) for c in cmd)
        return subprocess.run(cmd_str, shell=True, **kwargs)
    else:
        return subprocess.run(cmd, **kwargs)


# =============================================================================
# Type-Safe Models
# =============================================================================

class GCPServiceResult(BaseModel):
    """Result of GCP service operations"""
    success: bool
    operation: str
    project_id: Optional[str] = None
    service: Optional[str] = None
    message: str = ""
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class CloudRunDeployResult(BaseModel):
    """Result of Cloud Run deployment"""
    success: bool
    service_name: Optional[str] = None
    project_id: Optional[str] = None
    region: Optional[str] = None
    url: Optional[str] = None
    revision: Optional[str] = None
    status: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class CloudBuildResult(BaseModel):
    """Result of Cloud Build operations"""
    success: bool
    build_id: Optional[str] = None
    project_id: Optional[str] = None
    status: Optional[str] = None
    log_url: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    duration: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Common GCP API Services
# =============================================================================

COMMON_SERVICES = {
    "run": "run.googleapis.com",
    "cloudbuild": "cloudbuild.googleapis.com",
    "artifactregistry": "artifactregistry.googleapis.com",
    "secretmanager": "secretmanager.googleapis.com",
    "cloudfunctions": "cloudfunctions.googleapis.com",
    "appengine": "appengine.googleapis.com",
    "compute": "compute.googleapis.com",
    "container": "container.googleapis.com",
    "sql": "sql-component.googleapis.com",
    "storage": "storage.googleapis.com",
    "bigquery": "bigquery.googleapis.com",
    "pubsub": "pubsub.googleapis.com",
    "firestore": "firestore.googleapis.com",
    "iam": "iam.googleapis.com",
    "logging": "logging.googleapis.com",
    "monitoring": "monitoring.googleapis.com",
}


# =============================================================================
# GCP Service Enabler Tool
# =============================================================================

class GCPServiceEnablerTool(BaseTool):
    """Enable or disable GCP APIs/services

    Features:
    - Enable/disable individual services
    - List enabled services
    - Batch enable multiple services
    - Wait for enablement to complete
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="gcp_service_enabler",
                description="Enable or disable GCP APIs (Cloud Run, Cloud Build, etc.)",
                category="gcp",
                tags=["gcp", "api", "services", "deployment"],
                requires_auth=True
            )
        )
        self._gcloud_path = shutil.which("gcloud")

    def _run_gcloud(self, args: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
        """Run gcloud command with Windows compatibility"""
        cmd = [self._gcloud_path or "gcloud"] + args
        if sys.platform == "win32":
            # On Windows, gcloud is a .cmd file that requires shell=True
            # Quote paths that contain spaces
            cmd_str = " ".join(_quote_if_needed(c) for c in cmd)
            return subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=timeout)
        else:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _get_current_project(self) -> Optional[str]:
        """Get current GCP project"""
        try:
            result = self._run_gcloud(["config", "get-value", "project"])
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _resolve_service_name(self, service: str) -> str:
        """Resolve short service name to full API name"""
        service_lower = service.lower().strip()
        return COMMON_SERVICES.get(service_lower, service)

    def _execute(
        self,
        action: str,
        service: Optional[str] = None,
        services: Optional[List[str]] = None,
        project_id: Optional[str] = None,
        wait: bool = True
    ) -> str:
        """Manage GCP services

        Args:
            action: 'enable', 'disable', 'list', or 'check'
            service: Single service name (e.g., 'run', 'cloudbuild', or full API name)
            services: List of services for batch operations
            project_id: GCP project ID
            wait: Wait for operation to complete (for enable/disable)

        Returns:
            JSON with operation result
        """
        try:
            if not self._gcloud_path:
                return GCPServiceResult(
                    success=False,
                    operation=action,
                    error="gcloud CLI not installed",
                    error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
                ).to_json()

            project = project_id or self._get_current_project()
            if not project:
                return GCPServiceResult(
                    success=False,
                    operation=action,
                    error="No GCP project specified",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

            action = action.lower()

            # List enabled services
            if action == "list":
                result = self._run_gcloud([
                    "services", "list",
                    "--enabled",
                    "--project", project,
                    "--format", "json"
                ])

                if result.returncode != 0:
                    return GCPServiceResult(
                        success=False,
                        operation="list",
                        project_id=project,
                        error=result.stderr.strip(),
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

                try:
                    enabled = json.loads(result.stdout) if result.stdout else []
                    service_names = [s.get("config", {}).get("name", "") for s in enabled]
                except json.JSONDecodeError:
                    service_names = []

                return GCPServiceResult(
                    success=True,
                    operation="list",
                    project_id=project,
                    message=f"{len(service_names)} services enabled",
                    details={"enabled_services": service_names}
                ).to_json()

            # Check if service is enabled
            elif action == "check":
                if not service:
                    return GCPServiceResult(
                        success=False,
                        operation="check",
                        error="Service name required for check operation",
                        error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                    ).to_json()

                service_api = self._resolve_service_name(service)

                result = self._run_gcloud([
                    "services", "list",
                    "--enabled",
                    "--project", project,
                    "--filter", f"config.name:{service_api}",
                    "--format", "json"
                ])

                if result.returncode != 0:
                    return GCPServiceResult(
                        success=False,
                        operation="check",
                        service=service_api,
                        error=result.stderr.strip(),
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

                try:
                    enabled = json.loads(result.stdout) if result.stdout else []
                    is_enabled = len(enabled) > 0
                except json.JSONDecodeError:
                    is_enabled = False

                return GCPServiceResult(
                    success=True,
                    operation="check",
                    project_id=project,
                    service=service_api,
                    message=f"Service {'is' if is_enabled else 'is NOT'} enabled",
                    details={"enabled": is_enabled}
                ).to_json()

            # Enable service(s)
            elif action == "enable":
                to_enable = []
                if service:
                    to_enable.append(self._resolve_service_name(service))
                if services:
                    to_enable.extend([self._resolve_service_name(s) for s in services])

                if not to_enable:
                    return GCPServiceResult(
                        success=False,
                        operation="enable",
                        error="No services specified to enable",
                        error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                    ).to_json()

                enabled = []
                failed = []

                for svc in to_enable:
                    args = [
                        "services", "enable", svc,
                        "--project", project
                    ]
                    if not wait:
                        args.append("--async")

                    result = self._run_gcloud(args, timeout=180)

                    if result.returncode == 0:
                        enabled.append(svc)
                        logger.info(f"Enabled service: {svc}", extra={
                            "project": project,
                            "service": svc
                        })
                    else:
                        failed.append({"service": svc, "error": result.stderr.strip()})

                return GCPServiceResult(
                    success=len(failed) == 0,
                    operation="enable",
                    project_id=project,
                    message=f"Enabled {len(enabled)}/{len(to_enable)} services",
                    details={
                        "enabled": enabled,
                        "failed": failed
                    },
                    error=f"Failed to enable: {[f['service'] for f in failed]}" if failed else None
                ).to_json()

            # Disable service
            elif action == "disable":
                if not service:
                    return GCPServiceResult(
                        success=False,
                        operation="disable",
                        error="Service name required",
                        error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                    ).to_json()

                service_api = self._resolve_service_name(service)

                result = self._run_gcloud([
                    "services", "disable", service_api,
                    "--project", project,
                    "--force"
                ])

                if result.returncode != 0:
                    return GCPServiceResult(
                        success=False,
                        operation="disable",
                        project_id=project,
                        service=service_api,
                        error=result.stderr.strip(),
                        error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                    ).to_json()

                return GCPServiceResult(
                    success=True,
                    operation="disable",
                    project_id=project,
                    service=service_api,
                    message=f"Service '{service_api}' disabled"
                ).to_json()

            else:
                return GCPServiceResult(
                    success=False,
                    operation=action,
                    error=f"Unknown action: {action}. Use: enable, disable, list, check",
                    error_code=ErrorCode.TOOL_VALIDATION_ERROR.value
                ).to_json()

        except subprocess.TimeoutExpired:
            return GCPServiceResult(
                success=False,
                operation=action,
                error="Command timed out",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error(f"GCP service operation failed: {e}", exc_info=True)
            return GCPServiceResult(
                success=False,
                operation=action,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


# =============================================================================
# NOTE: GCPCloudRunTool and GCPCloudBuildTool have been migrated to YAML configs
# See: agent_os/tools/configs/gcp/cloud_run.yaml
# See: agent_os/tools/configs/gcp/cloud_build.yaml
# Use ConfigExecutor to load and execute these tools
# =============================================================================
