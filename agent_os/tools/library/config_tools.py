"""
Config-Driven Tool Wrapper

Bridges YAML-defined tools with AgentOS ToolRegistry.
This allows config-driven tools to work with LangChain, MCP, etc.
"""

from typing import Dict, Any, List, Optional
from pathlib import Path

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.tools.configs import get_executor, ConfigExecutor


class ConfigDrivenTool(BaseTool):
    """
    Universal tool that executes any config-defined GCP service.

    This is a meta-tool that provides access to 100+ GCP services
    defined in YAML configs, without writing Python code for each.
    """

    def __init__(self):
        super().__init__(
            metadata=ToolMetadata(
                name="gcp_service",
                description=(
                    "Execute any GCP service operation. Supports Cloud SQL, Pub/Sub, "
                    "Cloud Storage, and 100+ other services defined in config. "
                    "Use 'list_tools' action to see available services."
                ),
                category="gcp",
                version="1.0.0",
                tags=["gcp", "cloud", "config-driven", "universal"],
                requires_auth=True,
                supports_async=True
            )
        )
        self.executor = get_executor()

    def _execute(
        self,
        tool: Optional[str] = None,
        action: str = "list_tools",
        dry_run: bool = False,
        **params
    ) -> Dict[str, Any]:
        """
        Execute a config-driven GCP tool.

        Args:
            tool: Tool name (e.g., "cloud_sql", "pubsub", "cloud_storage")
            action: Action to perform (e.g., "create", "delete", "list")
            dry_run: If True, return command without executing
            **params: Tool-specific parameters

        Returns:
            Dict with success status and results
        """
        # Special action: list available tools
        if action == "list_tools" or tool is None:
            tools = self.executor.list_tools()
            return {
                "success": True,
                "tools": tools,
                "count": len(tools),
                "message": f"Found {len(tools)} config-driven tools. Use tool='name' to execute."
            }

        # Special action: get tool schema
        if action == "get_schema":
            schema = self.executor.get_tool_schema(tool)
            if schema:
                return {"success": True, "schema": schema}
            return {"success": False, "error": f"Tool not found: {tool}"}

        # Special action: get examples
        if action == "get_examples":
            examples = self.executor.get_examples(tool)
            return {"success": True, "examples": examples}

        # Special action: estimate cost
        if action == "estimate_cost":
            cost = self.executor.estimate_cost(tool)
            return {"success": True, "estimated_cost": cost}

        # Execute the tool
        params['action'] = action
        return self.executor.execute(tool, dry_run=dry_run, **params)


class CloudSQLTool(BaseTool):
    """Dedicated Cloud SQL tool for common database operations"""

    def __init__(self):
        super().__init__(
            metadata=ToolMetadata(
                name="cloud_sql",
                description=(
                    "Create and manage Cloud SQL (PostgreSQL/MySQL) instances. "
                    "Supports create, delete, describe, list, restart actions."
                ),
                category="gcp_database",
                version="1.0.0",
                tags=["gcp", "database", "sql", "postgres", "mysql"],
                requires_auth=True
            )
        )
        self.executor = get_executor()

    def _execute(
        self,
        action: str = "list",
        instance_name: Optional[str] = None,
        project_id: Optional[str] = None,
        database_version: str = "POSTGRES_15",
        tier: str = "db-f1-micro",
        region: str = "us-central1",
        dry_run: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute Cloud SQL operation"""
        params = {
            "action": action,
            "database_version": database_version,
            "tier": tier,
            "region": region,
            **kwargs
        }

        if instance_name:
            params["instance_name"] = instance_name
        if project_id:
            params["project_id"] = project_id

        return self.executor.execute("cloud_sql", dry_run=dry_run, **params)


class PubSubTool(BaseTool):
    """Dedicated Pub/Sub tool for messaging operations"""

    def __init__(self):
        super().__init__(
            metadata=ToolMetadata(
                name="pubsub",
                description=(
                    "Create and manage Pub/Sub topics and subscriptions. "
                    "Supports create_topic, create_subscription, list_topics, etc."
                ),
                category="gcp_messaging",
                version="1.0.0",
                tags=["gcp", "messaging", "pubsub", "events"],
                requires_auth=True
            )
        )
        self.executor = get_executor()

    def _execute(
        self,
        action: str = "list_topics",
        topic_name: Optional[str] = None,
        subscription_name: Optional[str] = None,
        project_id: Optional[str] = None,
        push_endpoint: Optional[str] = None,
        dry_run: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute Pub/Sub operation"""
        params = {"action": action, **kwargs}

        if topic_name:
            params["topic_name"] = topic_name
        if subscription_name:
            params["subscription_name"] = subscription_name
        if project_id:
            params["project_id"] = project_id
        if push_endpoint:
            params["push_endpoint"] = push_endpoint

        return self.executor.execute("pubsub", dry_run=dry_run, **params)


class CloudStorageTool(BaseTool):
    """Dedicated Cloud Storage tool for bucket operations"""

    def __init__(self):
        super().__init__(
            metadata=ToolMetadata(
                name="cloud_storage",
                description=(
                    "Create and manage Cloud Storage buckets. "
                    "Supports create, delete, describe, list actions."
                ),
                category="gcp_storage",
                version="1.0.0",
                tags=["gcp", "storage", "buckets", "objects"],
                requires_auth=True
            )
        )
        self.executor = get_executor()

    def _execute(
        self,
        action: str = "list",
        bucket_name: Optional[str] = None,
        project_id: Optional[str] = None,
        location: str = "US",
        storage_class: str = "STANDARD",
        dry_run: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute Cloud Storage operation"""
        params = {
            "action": action,
            "location": location,
            "storage_class": storage_class,
            **kwargs
        }

        if bucket_name:
            params["bucket_name"] = bucket_name
        if project_id:
            params["project_id"] = project_id

        return self.executor.execute("cloud_storage", dry_run=dry_run, **params)


class CloudRunTool(BaseTool):
    """Dedicated Cloud Run tool for serverless container deployment"""

    def __init__(self):
        super().__init__(
            metadata=ToolMetadata(
                name="cloud_run",
                description=(
                    "Deploy and manage Cloud Run services. "
                    "Supports deploy, describe, delete, list, update, and traffic management."
                ),
                category="gcp_compute",
                version="1.0.0",
                tags=["gcp", "cloud-run", "serverless", "deployment", "containers"],
                requires_auth=True
            )
        )
        self.executor = get_executor()

    def _execute(
        self,
        action: str = "list",
        service_name: Optional[str] = None,
        project_id: Optional[str] = None,
        region: str = "us-central1",
        image: Optional[str] = None,
        memory: str = "512Mi",
        cpu: str = "1",
        min_instances: int = 0,
        max_instances: int = 100,
        allow_unauthenticated: bool = False,
        dry_run: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute Cloud Run operation"""
        params = {
            "action": action,
            "region": region,
            "memory": memory,
            "cpu": cpu,
            "min_instances": min_instances,
            "max_instances": max_instances,
            "allow_unauthenticated": allow_unauthenticated,
            **kwargs
        }

        if service_name:
            params["service_name"] = service_name
        if project_id:
            params["project_id"] = project_id
        if image:
            params["image"] = image

        return self.executor.execute("cloud_run", dry_run=dry_run, **params)


class CloudBuildTool(BaseTool):
    """Dedicated Cloud Build tool for CI/CD operations"""

    def __init__(self):
        super().__init__(
            metadata=ToolMetadata(
                name="cloud_build",
                description=(
                    "Trigger and manage Cloud Build operations. "
                    "Supports submit, status, list, cancel, create_trigger actions."
                ),
                category="gcp_devops",
                version="1.0.0",
                tags=["gcp", "cloud-build", "ci-cd", "build", "deployment"],
                requires_auth=True
            )
        )
        self.executor = get_executor()

    def _execute(
        self,
        action: str = "list",
        project_id: Optional[str] = None,
        source_path: str = ".",
        config_file: Optional[str] = None,
        tag: Optional[str] = None,
        build_id: Optional[str] = None,
        region: str = "global",
        dry_run: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute Cloud Build operation"""
        params = {
            "action": action,
            "source_path": source_path,
            "region": region,
            **kwargs
        }

        if project_id:
            params["project_id"] = project_id
        if config_file:
            params["config_file"] = config_file
        if tag:
            params["tag"] = tag
        if build_id:
            params["build_id"] = build_id

        return self.executor.execute("cloud_build", dry_run=dry_run, **params)


class ArtifactRegistryTool(BaseTool):
    """Dedicated Artifact Registry tool for container image management"""

    def __init__(self):
        super().__init__(
            metadata=ToolMetadata(
                name="artifact_registry",
                description=(
                    "Create and manage Artifact Registry repositories. "
                    "Supports create, describe, delete, list, list_images actions."
                ),
                category="gcp_devops",
                version="1.0.0",
                tags=["gcp", "artifact-registry", "docker", "containers", "images"],
                requires_auth=True
            )
        )
        self.executor = get_executor()

    def _execute(
        self,
        action: str = "list",
        repository_name: Optional[str] = None,
        project_id: Optional[str] = None,
        region: str = "us-central1",
        format: str = "docker",
        dry_run: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute Artifact Registry operation"""
        params = {
            "action": action,
            "region": region,
            "format": format,
            **kwargs
        }

        if repository_name:
            params["repository_name"] = repository_name
        if project_id:
            params["project_id"] = project_id

        return self.executor.execute("artifact_registry", dry_run=dry_run, **params)


class ServiceAccountTool(BaseTool):
    """Dedicated Service Account tool for IAM identity management"""

    def __init__(self):
        super().__init__(
            metadata=ToolMetadata(
                name="service_account",
                description=(
                    "Create and manage GCP Service Accounts. "
                    "Supports create, delete, describe, list, add_iam, remove_iam actions."
                ),
                category="gcp_security",
                version="1.0.0",
                tags=["gcp", "iam", "service-account", "security", "identity"],
                requires_auth=True
            )
        )
        self.executor = get_executor()

    def _execute(
        self,
        action: str = "list",
        account_name: Optional[str] = None,
        project_id: Optional[str] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        role: Optional[str] = None,
        dry_run: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute Service Account operation"""
        params = {"action": action, **kwargs}

        if account_name:
            params["account_name"] = account_name
        if project_id:
            params["project_id"] = project_id
        if display_name:
            params["display_name"] = display_name
        if description:
            params["description"] = description
        if role:
            params["role"] = role

        return self.executor.execute("service_account", dry_run=dry_run, **params)


class WorkloadIdentityTool(BaseTool):
    """Dedicated Workload Identity tool for GitHub Actions OIDC auth"""

    def __init__(self):
        super().__init__(
            metadata=ToolMetadata(
                name="workload_identity",
                description=(
                    "Configure Workload Identity Federation for keyless GitHub Actions auth. "
                    "Supports setup, get_config, add_provider, bind_service_account actions."
                ),
                category="gcp_security",
                version="1.0.0",
                tags=["gcp", "iam", "workload-identity", "github", "oidc", "ci-cd"],
                requires_auth=True
            )
        )
        self.executor = get_executor()

    def _execute(
        self,
        action: str = "get_config",
        project_id: Optional[str] = None,
        pool_name: str = "github-pool",
        provider_name: str = "github-provider",
        github_repo: Optional[str] = None,
        service_account: Optional[str] = None,
        dry_run: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute Workload Identity operation"""
        params = {
            "action": action,
            "pool_name": pool_name,
            "provider_name": provider_name,
            **kwargs
        }

        if project_id:
            params["project_id"] = project_id
        if github_repo:
            params["github_repo"] = github_repo
        if service_account:
            params["service_account"] = service_account

        return self.executor.execute("workload_identity", dry_run=dry_run, **params)


def register_config_tools(registry) -> int:
    """
    Register all config-driven tools with a ToolRegistry.

    Args:
        registry: AgentOS ToolRegistry instance

    Returns:
        Number of tools registered
    """
    tools = [
        # Universal config tool
        ConfigDrivenTool(),
        # Database tools
        CloudSQLTool(),
        # Messaging tools
        PubSubTool(),
        # Storage tools
        CloudStorageTool(),
        # Compute/Deployment tools (previously hardcoded)
        CloudRunTool(),
        CloudBuildTool(),
        # DevOps tools (previously hardcoded)
        ArtifactRegistryTool(),
        # Security/IAM tools (previously hardcoded)
        ServiceAccountTool(),
        WorkloadIdentityTool(),
    ]

    for tool in tools:
        registry.register(tool, replace=True)

    return len(tools)
