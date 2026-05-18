"""
GCP Infrastructure Tools - PHASE 0 Platform Setup

One-time infrastructure provisioning tools for:
- GCP Project creation
- Artifact Registry setup
- Service Account management
- IAM Role assignment
- Workload Identity (GitHub ↔ GCP OIDC)
- Multi-environment Cloud Run services
- Branch-based deployment triggers
"""

import subprocess
import json
import os
import sys
from typing import Optional, Dict, Any, List
from pydantic import Field

from agent_os.tools.base import BaseTool, ToolMetadata


def run_gcloud(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    """Run gcloud command with Windows compatibility.

    On Windows, gcloud is a .cmd file that requires shell=True.
    This helper handles that automatically.
    """
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)

    if sys.platform == "win32":
        # On Windows, join command and use shell=True
        cmd_str = " ".join(cmd)
        return subprocess.run(cmd_str, shell=True, **kwargs)
    else:
        # On Unix, use list format directly
        return subprocess.run(cmd, **kwargs)


# =============================================================================
# GCP Project Management
# =============================================================================

class GCPProjectTool(BaseTool):
    """
    Create and manage GCP projects.

    Handles project creation, billing linking, and project configuration.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="gcp_project",
            description="Create and manage GCP projects with billing configuration.",
            category="gcp_infrastructure",
            requires_auth=True
        )
        super().__init__(metadata)

    def _execute(
        self,
        action: str,
        project_id: str,
        project_name: Optional[str] = None,
        organization_id: Optional[str] = None,
        folder_id: Optional[str] = None,
        billing_account: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Manage GCP projects.

        Args:
            action: create, get, list, delete, set_billing
            project_id: Unique project ID
            project_name: Display name (defaults to project_id)
            organization_id: Organization to create project under
            folder_id: Folder to create project under
            billing_account: Billing account ID to link
            labels: Labels to apply to project

        Returns:
            Dict with operation result
        """
        if action == "create":
            return self._create_project(
                project_id, project_name, organization_id,
                folder_id, billing_account, labels
            )
        elif action == "get":
            return self._get_project(project_id)
        elif action == "list":
            return self._list_projects(organization_id, folder_id)
        elif action == "delete":
            return self._delete_project(project_id)
        elif action == "set_billing":
            return self._set_billing(project_id, billing_account)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    def _create_project(
        self,
        project_id: str,
        project_name: Optional[str],
        organization_id: Optional[str],
        folder_id: Optional[str],
        billing_account: Optional[str],
        labels: Optional[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Create a new GCP project."""
        cmd = ["gcloud", "projects", "create", project_id]

        if project_name:
            cmd.extend(["--name", project_name])

        if organization_id:
            cmd.extend(["--organization", organization_id])
        elif folder_id:
            cmd.extend(["--folder", folder_id])

        if labels:
            label_str = ",".join([f"{k}={v}" for k, v in labels.items()])
            cmd.extend(["--labels", label_str])

        try:
            result = run_gcloud(cmd)

            if result.returncode != 0:
                if "already exists" in result.stderr.lower():
                    return {
                        "success": False,
                        "error": f"Project '{project_id}' already exists.",
                        "already_exists": True
                    }
                return {"success": False, "error": result.stderr.strip()}

            response = {
                "success": True,
                "project_id": project_id,
                "project_name": project_name or project_id,
                "message": f"Project '{project_id}' created successfully."
            }

            # Link billing if provided
            if billing_account:
                billing_result = self._set_billing(project_id, billing_account)
                response["billing_linked"] = billing_result.get("success", False)

            return response

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_project(self, project_id: str) -> Dict[str, Any]:
        """Get project details."""
        try:
            result = run_gcloud(
                ["gcloud", "projects", "describe", project_id, "--format=json"],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}

            project_data = json.loads(result.stdout)
            return {
                "success": True,
                "project": project_data
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _list_projects(
        self,
        organization_id: Optional[str],
        folder_id: Optional[str]
    ) -> Dict[str, Any]:
        """List GCP projects."""
        cmd = ["gcloud", "projects", "list", "--format=json"]

        if organization_id:
            cmd.extend(["--filter", f"parent.id={organization_id}"])
        elif folder_id:
            cmd.extend(["--filter", f"parent.id={folder_id}"])

        try:
            result = run_gcloud(cmd)

            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}

            projects = json.loads(result.stdout)
            return {
                "success": True,
                "projects": projects,
                "count": len(projects)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delete_project(self, project_id: str) -> Dict[str, Any]:
        """Delete a GCP project (marks for deletion)."""
        try:
            result = run_gcloud(
                ["gcloud", "projects", "delete", project_id, "--quiet"],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}

            return {
                "success": True,
                "project_id": project_id,
                "message": f"Project '{project_id}' marked for deletion (30-day recovery window)."
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _set_billing(self, project_id: str, billing_account: str) -> Dict[str, Any]:
        """Link billing account to project."""
        try:
            result = run_gcloud(
                ["gcloud", "billing", "projects", "link", project_id,
                 "--billing-account", billing_account],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}

            return {
                "success": True,
                "project_id": project_id,
                "billing_account": billing_account,
                "message": "Billing account linked successfully."
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# NOTE: ArtifactRegistryTool and ServiceAccountTool have been migrated to YAML configs
# See: agent_os/tools/configs/gcp/artifact_registry.yaml
# See: agent_os/tools/configs/gcp/service_account.yaml
# Use ConfigExecutor to load and execute these tools
# =============================================================================


# =============================================================================
# IAM Role Management
# =============================================================================

class IAMRoleAssignerTool(BaseTool):
    """
    Assign IAM roles to service accounts or users.

    Handles role binding for project, folder, or organization level.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="iam_role_assigner",
            description="Assign IAM roles to service accounts, users, or groups.",
            category="gcp_infrastructure",
            requires_auth=True
        )
        super().__init__(metadata)

    # Common roles for deployment automation
    DEPLOYMENT_ROLES = [
        "roles/run.admin",                    # Cloud Run admin
        "roles/cloudbuild.builds.editor",     # Cloud Build
        "roles/artifactregistry.writer",      # Push images
        "roles/secretmanager.secretAccessor", # Access secrets
        "roles/logging.logWriter",            # Write logs
        "roles/iam.serviceAccountUser",       # Act as service account
    ]

    def _execute(
        self,
        action: str,
        project_id: str,
        member: str,
        role: Optional[str] = None,
        roles: Optional[List[str]] = None,
        preset: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Manage IAM role bindings.

        Args:
            action: add, remove, list, add_preset
            project_id: GCP project ID
            member: Member (e.g., serviceAccount:sa@project.iam.gserviceaccount.com)
            role: Single role to add/remove
            roles: List of roles to add/remove
            preset: Preset role group (deployment, viewer, editor)

        Returns:
            Dict with operation result
        """
        if action == "add":
            return self._add_binding(project_id, member, role, roles)
        elif action == "remove":
            return self._remove_binding(project_id, member, role, roles)
        elif action == "list":
            return self._list_bindings(project_id, member)
        elif action == "add_preset":
            return self._add_preset(project_id, member, preset)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    def _add_binding(
        self,
        project_id: str,
        member: str,
        role: Optional[str],
        roles: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Add IAM role binding."""
        roles_to_add = []

        if role:
            roles_to_add.append(role)
        if roles:
            roles_to_add.extend(roles)

        if not roles_to_add:
            return {"success": False, "error": "No roles specified."}

        results = []
        for r in roles_to_add:
            try:
                result = run_gcloud(
                    ["gcloud", "projects", "add-iam-policy-binding", project_id,
                     "--member", member, "--role", r, "--quiet"]
                )

                if result.returncode == 0:
                    results.append({"role": r, "success": True})
                else:
                    results.append({"role": r, "success": False, "error": result.stderr.strip()})

            except Exception as e:
                results.append({"role": r, "success": False, "error": str(e)})

        success_count = sum(1 for r in results if r["success"])

        return {
            "success": success_count == len(roles_to_add),
            "member": member,
            "results": results,
            "added": success_count,
            "failed": len(roles_to_add) - success_count,
            "message": f"Added {success_count}/{len(roles_to_add)} roles to {member}."
        }

    def _remove_binding(
        self,
        project_id: str,
        member: str,
        role: Optional[str],
        roles: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Remove IAM role binding."""
        roles_to_remove = []

        if role:
            roles_to_remove.append(role)
        if roles:
            roles_to_remove.extend(roles)

        if not roles_to_remove:
            return {"success": False, "error": "No roles specified."}

        results = []
        for r in roles_to_remove:
            try:
                result = run_gcloud(
                    ["gcloud", "projects", "remove-iam-policy-binding", project_id,
                     "--member", member, "--role", r, "--quiet"]
                )

                if result.returncode == 0:
                    results.append({"role": r, "success": True})
                else:
                    results.append({"role": r, "success": False, "error": result.stderr.strip()})

            except Exception as e:
                results.append({"role": r, "success": False, "error": str(e)})

        success_count = sum(1 for r in results if r["success"])

        return {
            "success": success_count == len(roles_to_remove),
            "member": member,
            "results": results,
            "removed": success_count,
            "message": f"Removed {success_count}/{len(roles_to_remove)} roles from {member}."
        }

    def _list_bindings(self, project_id: str, member: Optional[str]) -> Dict[str, Any]:
        """List IAM bindings for project or specific member."""
        try:
            result = run_gcloud(
                ["gcloud", "projects", "get-iam-policy", project_id, "--format=json"],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}

            policy = json.loads(result.stdout)
            bindings = policy.get("bindings", [])

            if member:
                # Filter for specific member
                member_roles = []
                for binding in bindings:
                    if member in binding.get("members", []):
                        member_roles.append(binding.get("role"))

                return {
                    "success": True,
                    "member": member,
                    "roles": member_roles,
                    "count": len(member_roles)
                }
            else:
                return {
                    "success": True,
                    "bindings": bindings,
                    "count": len(bindings)
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _add_preset(
        self,
        project_id: str,
        member: str,
        preset: str
    ) -> Dict[str, Any]:
        """Add preset role group."""
        presets = {
            "deployment": self.DEPLOYMENT_ROLES,
            "viewer": ["roles/viewer"],
            "editor": ["roles/editor"],
            "owner": ["roles/owner"],
            "cloud_run": [
                "roles/run.admin",
                "roles/iam.serviceAccountUser"
            ],
            "cloud_build": [
                "roles/cloudbuild.builds.editor",
                "roles/artifactregistry.writer"
            ]
        }

        roles = presets.get(preset)
        if not roles:
            return {
                "success": False,
                "error": f"Unknown preset: {preset}. Available: {list(presets.keys())}"
            }

        return self._add_binding(project_id, member, None, roles)


# =============================================================================
# NOTE: WorkloadIdentityTool has been migrated to YAML config
# See: agent_os/tools/configs/gcp/workload_identity.yaml
# Use ConfigExecutor to load and execute this tool
# =============================================================================


# =============================================================================
# Multi-Environment Setup
# =============================================================================

class MultiEnvSetupTool(BaseTool):
    """
    Set up multiple environments (dev/staging/prod) in one operation.

    Creates Cloud Run services, Artifact Registry, and triggers.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="multi_env_setup",
            description="Set up dev/staging/prod environments with Cloud Run services and triggers.",
            category="gcp_infrastructure",
            requires_auth=True
        )
        super().__init__(metadata)

    # Default environment configurations
    ENV_CONFIGS = {
        "dev": {
            "branch": "dev",
            "min_instances": 0,
            "max_instances": 2,
            "cpu": "1",
            "memory": "256Mi",
            "concurrency": 80,
            "allow_unauthenticated": True
        },
        "staging": {
            "branch": "staging",
            "min_instances": 0,
            "max_instances": 5,
            "cpu": "1",
            "memory": "512Mi",
            "concurrency": 100,
            "allow_unauthenticated": True
        },
        "prod": {
            "branch": "main",
            "min_instances": 2,
            "max_instances": 100,
            "cpu": "2",
            "memory": "1Gi",
            "concurrency": 200,
            "allow_unauthenticated": True
        }
    }

    def _execute(
        self,
        action: str,
        project_id: str,
        app_name: str,
        region: str = "us-central1",
        github_repo: Optional[str] = None,
        environments: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Set up multi-environment infrastructure.

        Args:
            action: setup, status, teardown
            project_id: GCP project ID
            app_name: Application name (used as service prefix)
            region: GCP region
            github_repo: GitHub repo (owner/repo) for triggers
            environments: List of environments (default: dev, staging, prod)

        Returns:
            Dict with setup results
        """
        envs = environments or ["dev", "staging", "prod"]

        if action == "setup":
            return self._setup_environments(project_id, app_name, region, github_repo, envs)
        elif action == "status":
            return self._get_status(project_id, app_name, region, envs)
        elif action == "teardown":
            return self._teardown(project_id, app_name, region, envs)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    def _setup_environments(
        self,
        project_id: str,
        app_name: str,
        region: str,
        github_repo: Optional[str],
        environments: List[str]
    ) -> Dict[str, Any]:
        """Set up all environments."""
        results = {
            "apis_enabled": [],
            "services_created": [],
            "triggers_created": [],
            "errors": []
        }

        # 1. Enable required APIs
        apis = [
            "run.googleapis.com",
            "cloudbuild.googleapis.com",
            "artifactregistry.googleapis.com",
            "secretmanager.googleapis.com"
        ]

        for api in apis:
            api_result = run_gcloud(
                ["gcloud", "services", "enable", api, "--project", project_id],
                capture_output=True, text=True
            )
            if api_result.returncode == 0:
                results["apis_enabled"].append(api)
            else:
                results["errors"].append(f"Failed to enable {api}")

        # 2. Create Artifact Registry
        registry_result = run_gcloud(
            ["gcloud", "artifacts", "repositories", "create", f"{app_name}-repo",
             "--project", project_id, "--location", region,
             "--repository-format", "docker"],
            capture_output=True, text=True
        )

        if registry_result.returncode == 0 or "already exists" in registry_result.stderr.lower():
            results["artifact_registry"] = f"{region}-docker.pkg.dev/{project_id}/{app_name}-repo"

        # 3. Create Cloud Run service placeholders for each environment
        for env in environments:
            config = self.ENV_CONFIGS.get(env, self.ENV_CONFIGS["dev"])
            service_name = f"{app_name}-{env}"

            # Create a minimal placeholder service
            service_result = run_gcloud(
                ["gcloud", "run", "services", "describe", service_name,
                 "--project", project_id, "--region", region],
                capture_output=True, text=True
            )

            if service_result.returncode != 0:
                # Service doesn't exist - that's OK, will be created on first deploy
                results["services_created"].append({
                    "name": service_name,
                    "environment": env,
                    "status": "ready_for_deploy",
                    "config": config
                })
            else:
                results["services_created"].append({
                    "name": service_name,
                    "environment": env,
                    "status": "exists"
                })

        # 4. Create Cloud Build triggers for each environment
        if github_repo:
            for env in environments:
                config = self.ENV_CONFIGS.get(env, self.ENV_CONFIGS["dev"])
                service_name = f"{app_name}-{env}"
                branch = config["branch"]

                trigger_result = run_gcloud([
                    "gcloud", "builds", "triggers", "create", "github",
                    "--project", project_id,
                    "--name", f"{app_name}-{env}-trigger",
                    "--repo-name", github_repo.split("/")[-1],
                    "--repo-owner", github_repo.split("/")[0],
                    "--branch-pattern", f"^{branch}$",
                    "--build-config", "cloudbuild.yaml",
                    "--substitutions", f"_SERVICE_NAME={service_name},_REGION={region}"
                ])

                if trigger_result.returncode == 0 or "already exists" in trigger_result.stderr.lower():
                    results["triggers_created"].append({
                        "name": f"{app_name}-{env}-trigger",
                        "branch": branch,
                        "service": service_name
                    })
                else:
                    results["errors"].append(f"Failed to create trigger for {env}: {trigger_result.stderr}")

        # Calculate cost estimate
        cost_estimate = self._calculate_cost_estimate(environments)

        return {
            "success": len(results["errors"]) == 0,
            "project_id": project_id,
            "app_name": app_name,
            "region": region,
            "results": results,
            "endpoints": {
                env: f"https://{app_name}-{env}-{project_id[:8]}.{region}.run.app"
                for env in environments
            },
            "cost_estimate": cost_estimate,
            "next_steps": [
                "1. Push code to trigger builds",
                "2. Monitor deployments in Cloud Console",
                "3. Configure custom domain (optional)",
                "4. Set up alerting and monitoring"
            ]
        }

    def _get_status(
        self,
        project_id: str,
        app_name: str,
        region: str,
        environments: List[str]
    ) -> Dict[str, Any]:
        """Get status of all environments."""
        services = []

        for env in environments:
            service_name = f"{app_name}-{env}"

            result = run_gcloud(
                ["gcloud", "run", "services", "describe", service_name,
                 "--project", project_id, "--region", region, "--format=json"],
                capture_output=True, text=True
            )

            if result.returncode == 0:
                service_data = json.loads(result.stdout)
                services.append({
                    "name": service_name,
                    "environment": env,
                    "status": "running",
                    "url": service_data.get("status", {}).get("url"),
                    "latestRevision": service_data.get("status", {}).get("latestReadyRevisionName")
                })
            else:
                services.append({
                    "name": service_name,
                    "environment": env,
                    "status": "not_deployed"
                })

        return {
            "success": True,
            "services": services
        }

    def _teardown(
        self,
        project_id: str,
        app_name: str,
        region: str,
        environments: List[str]
    ) -> Dict[str, Any]:
        """Remove all environments (dangerous)."""
        results = []

        for env in environments:
            service_name = f"{app_name}-{env}"

            # Delete service
            service_result = run_gcloud(
                ["gcloud", "run", "services", "delete", service_name,
                 "--project", project_id, "--region", region, "--quiet"],
                capture_output=True, text=True
            )

            results.append({
                "service": service_name,
                "deleted": service_result.returncode == 0
            })

            # Delete trigger
            trigger_result = run_gcloud(
                ["gcloud", "builds", "triggers", "delete", f"{app_name}-{env}-trigger",
                 "--project", project_id, "--quiet"],
                capture_output=True, text=True
            )

            results.append({
                "trigger": f"{app_name}-{env}-trigger",
                "deleted": trigger_result.returncode == 0
            })

        return {
            "success": True,
            "results": results,
            "message": "Environments removed. Artifact Registry preserved."
        }

    def _calculate_cost_estimate(self, environments: List[str]) -> Dict[str, Any]:
        """Calculate monthly cost estimate."""
        costs = {
            "dev": {"min": 5, "max": 25},
            "staging": {"min": 30, "max": 100},
            "prod": {"min": 100, "max": 500}
        }

        total_min = 0
        total_max = 0
        breakdown = {}

        for env in environments:
            cost = costs.get(env, costs["dev"])
            breakdown[env] = f"${cost['min']}-${cost['max']}/month"
            total_min += cost["min"]
            total_max += cost["max"]

        return {
            "total": f"${total_min}-${total_max}/month",
            "breakdown": breakdown,
            "note": "Costs vary based on traffic and resource usage"
        }


# =============================================================================
# Branch-Based Trigger Configuration
# =============================================================================

class BranchTriggerTool(BaseTool):
    """
    Configure branch-to-environment deployment mapping.

    Maps git branches to Cloud Run services for automatic deployments.
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="branch_trigger",
            description="Configure branch-to-environment deployment triggers.",
            category="gcp_infrastructure",
            requires_auth=True
        )
        super().__init__(metadata)

    def _execute(
        self,
        action: str,
        project_id: str,
        app_name: str,
        github_repo: str,
        region: str = "us-central1",
        branch_mappings: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Configure branch triggers.

        Args:
            action: create, list, delete, update
            project_id: GCP project ID
            app_name: Application name
            github_repo: GitHub repo (owner/repo)
            region: GCP region
            branch_mappings: Dict mapping branches to environments
                            e.g., {"main": "prod", "staging": "staging", "dev": "dev"}

        Returns:
            Dict with trigger configuration
        """
        # Default mappings
        mappings = branch_mappings or {
            "main": "prod",
            "master": "prod",
            "staging": "staging",
            "develop": "staging",
            "dev": "dev"
        }

        if action == "create":
            return self._create_triggers(project_id, app_name, github_repo, region, mappings)
        elif action == "list":
            return self._list_triggers(project_id, app_name)
        elif action == "delete":
            return self._delete_triggers(project_id, app_name)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    def _create_triggers(
        self,
        project_id: str,
        app_name: str,
        github_repo: str,
        region: str,
        mappings: Dict[str, str]
    ) -> Dict[str, Any]:
        """Create Cloud Build triggers for branch mappings."""
        results = []

        repo_parts = github_repo.split("/")
        if len(repo_parts) != 2:
            return {"success": False, "error": "Invalid github_repo format. Use 'owner/repo'."}

        owner, repo = repo_parts

        # First, generate cloudbuild.yaml
        cloudbuild_content = self._generate_cloudbuild_yaml(project_id, region)

        for branch, env in mappings.items():
            service_name = f"{app_name}-{env}"
            trigger_name = f"{app_name}-{branch}-to-{env}"

            cmd = [
                "gcloud", "builds", "triggers", "create", "github",
                "--project", project_id,
                "--name", trigger_name,
                "--repo-name", repo,
                "--repo-owner", owner,
                "--branch-pattern", f"^{branch}$",
                "--build-config", "cloudbuild.yaml",
                "--substitutions", f"_SERVICE_NAME={service_name},_REGION={region},_ENV={env}"
            ]

            result = run_gcloud(cmd)

            if result.returncode == 0 or "already exists" in result.stderr.lower():
                results.append({
                    "branch": branch,
                    "environment": env,
                    "trigger": trigger_name,
                    "service": service_name,
                    "success": True
                })
            else:
                results.append({
                    "branch": branch,
                    "environment": env,
                    "success": False,
                    "error": result.stderr.strip()
                })

        success_count = sum(1 for r in results if r.get("success"))

        return {
            "success": success_count == len(mappings),
            "triggers": results,
            "created": success_count,
            "total": len(mappings),
            "cloudbuild_yaml": cloudbuild_content,
            "message": f"Created {success_count}/{len(mappings)} triggers.",
            "next_steps": [
                "1. Add cloudbuild.yaml to your repository root",
                "2. Push to mapped branches to trigger deployments",
                "3. Monitor builds in Cloud Build console"
            ]
        }

    def _list_triggers(self, project_id: str, app_name: str) -> Dict[str, Any]:
        """List triggers for app."""
        try:
            result = run_gcloud(
                ["gcloud", "builds", "triggers", "list",
                 "--project", project_id, "--format=json",
                 "--filter", f"name~{app_name}"],
                capture_output=True, text=True
            )

            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}

            triggers = json.loads(result.stdout)
            return {
                "success": True,
                "triggers": triggers,
                "count": len(triggers)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delete_triggers(self, project_id: str, app_name: str) -> Dict[str, Any]:
        """Delete all triggers for app."""
        # First list triggers
        list_result = self._list_triggers(project_id, app_name)

        if not list_result.get("success"):
            return list_result

        triggers = list_result.get("triggers", [])
        deleted = []

        for trigger in triggers:
            trigger_id = trigger.get("id") or trigger.get("name", "").split("/")[-1]

            result = run_gcloud(
                ["gcloud", "builds", "triggers", "delete", trigger_id,
                 "--project", project_id, "--quiet"],
                capture_output=True, text=True
            )

            deleted.append({
                "trigger": trigger_id,
                "success": result.returncode == 0
            })

        return {
            "success": True,
            "deleted": deleted,
            "count": len(deleted)
        }

    def _generate_cloudbuild_yaml(self, project_id: str, region: str) -> str:
        """Generate cloudbuild.yaml content."""
        return f"""# cloudbuild.yaml - Auto-generated by AgentOS
# Builds and deploys to Cloud Run based on branch

steps:
  # Build the container image
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - '{region}-docker.pkg.dev/$PROJECT_ID/${{_SERVICE_NAME}}-repo/${{_SERVICE_NAME}}:$COMMIT_SHA'
      - '-t'
      - '{region}-docker.pkg.dev/$PROJECT_ID/${{_SERVICE_NAME}}-repo/${{_SERVICE_NAME}}:latest'
      - '.'

  # Push to Artifact Registry
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'push'
      - '--all-tags'
      - '{region}-docker.pkg.dev/$PROJECT_ID/${{_SERVICE_NAME}}-repo/${{_SERVICE_NAME}}'

  # Deploy to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - '${{_SERVICE_NAME}}'
      - '--image'
      - '{region}-docker.pkg.dev/$PROJECT_ID/${{_SERVICE_NAME}}-repo/${{_SERVICE_NAME}}:$COMMIT_SHA'
      - '--region'
      - '${{_REGION}}'
      - '--platform'
      - 'managed'
      - '--allow-unauthenticated'

substitutions:
  _SERVICE_NAME: my-service
  _REGION: {region}
  _ENV: dev

options:
  logging: CLOUD_LOGGING_ONLY

images:
  - '{region}-docker.pkg.dev/$PROJECT_ID/${{_SERVICE_NAME}}-repo/${{_SERVICE_NAME}}:$COMMIT_SHA'
  - '{region}-docker.pkg.dev/$PROJECT_ID/${{_SERVICE_NAME}}-repo/${{_SERVICE_NAME}}:latest'
"""
