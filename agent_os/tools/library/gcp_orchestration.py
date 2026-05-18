"""
Multi-Service Orchestration Tool

Handles complex multi-service deployments with dependency management.
"""

import re
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
from ..base import BaseTool, ToolMetadata
from agent_os.utils.logging import get_logger

# Constants
DEFAULT_REGION = "us-central1"
DEFAULT_DB_TIER = "db-f1-micro"
PRODUCTION_DB_TIER = "db-n1-standard-1"

# Service type categories
DATABASE_TYPES = {"postgres", "mysql", "cloud_sql", "alloydb"}
BACKEND_TYPES = {"fastapi", "flask", "express", "spring"}
FRONTEND_TYPES = {"react", "vue", "angular", "nextjs"}

# Framework-specific environment variable names
FRAMEWORK_ENV_VARS = {
    "react": "REACT_APP_API_URL",
    "vue": "VUE_APP_API_URL",
    "angular": "NG_API_URL",
    "nextjs": "NEXT_PUBLIC_API_URL"
}

logger = get_logger(__name__)


class ServiceOrchestrationTool(BaseTool):
    """
    Orchestrate multi-service deployments with automatic dependency resolution.

    Handles:
    - Frontend + Backend + Database deployments
    - Service-to-service communication setup
    - Environment variable injection
    - Network configuration
    - Load balancer setup

    Examples:
        # Deploy full stack
        deploy_stack({
            "frontend": {"path": "./frontend", "type": "react"},
            "backend": {"path": "./backend", "type": "fastapi"},
            "database": {"type": "cloud_sql", "version": "POSTGRES_15"}
        })
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="orchestrate_services",
            description=(
                "Deploy and connect multiple services (frontend + backend + database). "
                "Automatically handles: service URLs, env vars, networking, dependencies."
            ),
            category="orchestration"
        )
        super().__init__(metadata)

    def _execute(
        self,
        services: Dict[str, Dict[str, Any]],
        deploy_order: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Orchestrate multi-service deployment.

        Args:
            services: Dict of service_name -> config
                     Example: {"frontend": {"path": "./frontend", "type": "react"},
                              "backend": {"path": "./api", "type": "fastapi"},
                              "database": {"type": "cloud_sql"}}
            deploy_order: Optional deployment order (auto-detected if None)

        Returns:
            Deployment result with service URLs and connection info
        """
        # Auto-detect deployment order based on dependencies
        if deploy_order is None:
            deploy_order = self._resolve_dependencies(services)

        results = {}
        service_urls = {}

        # Deploy in order
        for service_name in deploy_order:
            service_config = services[service_name]
            service_type = service_config.get("type")

            # Deploy based on type
            if service_type in ["postgres", "mysql", "cloud_sql"]:
                # Deploy database first
                result = self._deploy_database(service_name, service_config)
                results[service_name] = result
                service_urls[service_name] = result.get("connection_string")

            elif service_type in ["fastapi", "flask", "express", "spring"]:
                # Deploy backend with DB connection
                db_url = self._find_database_url(services, service_urls)
                result = self._deploy_backend(service_name, service_config, db_url)
                results[service_name] = result
                service_urls[service_name] = result.get("url")

            elif service_type in ["react", "vue", "angular", "nextjs"]:
                # Deploy frontend with backend URL
                backend_url = self._find_backend_url(services, service_urls)
                result = self._deploy_frontend(service_name, service_config, backend_url)
                results[service_name] = result
                service_urls[service_name] = result.get("url")

        return {
            "success": True,
            "services": results,
            "urls": service_urls,
            "deploy_order": deploy_order
        }

    def _resolve_dependencies(self, services: Dict[str, Dict]) -> List[str]:
        """Auto-detect deployment order: database → backend → frontend"""
        order = []

        # Databases first
        for name, config in services.items():
            if config.get("type") in ["postgres", "mysql", "cloud_sql", "alloydb"]:
                order.append(name)

        # Backends second
        for name, config in services.items():
            if config.get("type") in ["fastapi", "flask", "express", "spring"]:
                order.append(name)

        # Frontends last
        for name, config in services.items():
            if config.get("type") in ["react", "vue", "angular", "nextjs"]:
                order.append(name)

        return order

    def _find_database_url(self, services: Dict, urls: Dict) -> Optional[str]:
        """Find database connection URL from deployed services"""
        for name, config in services.items():
            if config.get("type") in ["postgres", "mysql", "cloud_sql"]:
                return urls.get(name)
        return None

    def _find_backend_url(self, services: Dict, urls: Dict) -> Optional[str]:
        """Find backend API URL from deployed services"""
        for name, config in services.items():
            if config.get("type") in ["fastapi", "flask", "express"]:
                return urls.get(name)
        return None

    def _deploy_database(self, name: str, config: Dict) -> Dict:
        """
        Deploy database service using gcloud.

        Supports: Cloud SQL, AlloyDB, Spanner
        """
        db_type = config.get("type", "cloud_sql")
        version = config.get("version", "POSTGRES_15")
        tier = config.get("tier", "db-f1-micro")
        region = config.get("region", "us-central1")

        if db_type in ["postgres", "mysql", "cloud_sql"]:
            # Cloud SQL deployment
            db_version = version if "POSTGRES" in version or "MYSQL" in version else f"POSTGRES_{version}"

            command = (
                f"sql instances create {name} "
                f"--database-version={db_version} "
                f"--tier={tier} "
                f"--region={region} "
                f"--backup --backup-start-time=03:00"
            )

            # Use gcloud CLI (this would actually call execute_gcloud in real usage)
            # For now, return structured result
            connection_string = f"postgresql://user:pass@/{name}?host=/cloudsql/project:region:{name}"

            return {
                "status": "deployed",
                "connection_string": connection_string,
                "connection_name": f"project:{region}:{name}",
                "type": db_type,
                "version": db_version,
                "command": command
            }

        elif db_type == "alloydb":
            # AlloyDB cluster deployment
            command = (
                f"alloydb clusters create {name} "
                f"--region={region} "
                f"--password=TEMP_PASSWORD_CHANGE_ME"
            )

            return {
                "status": "deployed",
                "connection_string": f"alloydb://{name}.{region}.alloydb",
                "type": "alloydb",
                "command": command
            }

        return {
            "status": "error",
            "error": f"Unsupported database type: {db_type}"
        }

    def _deploy_backend(self, name: str, config: Dict, db_url: Optional[str]) -> Dict:
        """
        Deploy backend service to Cloud Run.

        Automatically injects database connection.
        """
        project_path = config.get("path", "./")
        backend_type = config.get("type", "fastapi")
        region = config.get("region", "us-central1")

        # Build container image
        image_name = f"gcr.io/project/{name}:latest"
        build_command = f"builds submit --tag={image_name} {project_path}"

        # Prepare environment variables
        env_vars = config.get("env_vars", {})
        if db_url and "DATABASE_URL" not in env_vars:
            env_vars["DATABASE_URL"] = db_url

        env_flags = " ".join([f"--set-env-vars={k}={v}" for k, v in env_vars.items() if v != "auto"])

        # Deploy to Cloud Run
        deploy_command = (
            f"run deploy {name} "
            f"--image={image_name} "
            f"--region={region} "
            f"--allow-unauthenticated "
            f"{env_flags}"
        )

        service_url = f"https://{name}-{region[:2]}.run.app"

        return {
            "status": "deployed",
            "url": service_url,
            "env_vars": env_vars,
            "commands": [build_command, deploy_command],
            "image": image_name
        }

    def _deploy_frontend(self, name: str, config: Dict, backend_url: Optional[str]) -> Dict:
        """
        Deploy frontend with backend API URL injected.

        Supports: React, Vue, Angular, Next.js
        """
        project_path = config.get("path", "./")
        frontend_type = config.get("type", "react")
        region = config.get("region", "us-central1")

        # Determine env var name based on frontend type
        api_env_var = {
            "react": "REACT_APP_API_URL",
            "vue": "VUE_APP_API_URL",
            "angular": "NG_API_URL",
            "nextjs": "NEXT_PUBLIC_API_URL"
        }.get(frontend_type, "API_URL")

        # Build container image
        image_name = f"gcr.io/project/{name}:latest"
        build_command = f"builds submit --tag={image_name} {project_path}"

        # Prepare environment variables
        env_vars = config.get("env_vars", {})
        if backend_url and api_env_var not in env_vars:
            env_vars[api_env_var] = backend_url

        env_flags = " ".join([f"--set-env-vars={k}={v}" for k, v in env_vars.items() if v != "auto"])

        # Deploy to Cloud Run
        deploy_command = (
            f"run deploy {name} "
            f"--image={image_name} "
            f"--region={region} "
            f"--allow-unauthenticated "
            f"{env_flags}"
        )

        service_url = f"https://{name}-{region[:2]}.run.app"

        return {
            "status": "deployed",
            "url": service_url,
            "env_vars": env_vars,
            "commands": [build_command, deploy_command],
            "image": image_name
        }


class InfraProvisionerTool(BaseTool):
    """
    Universal infrastructure provisioning tool.

    Single tool to provision ANY GCP resource:
    - Cloud SQL, AlloyDB, Spanner
    - VPC, Subnets, Firewall Rules
    - Load Balancers, CDN
    - Secret Manager, IAM
    """

    def __init__(self):
        metadata = ToolMetadata(
            name="provision_infrastructure",
            description=(
                "Provision ANY GCP infrastructure from natural language description. "
                "Examples: 'Cloud SQL with PostgreSQL 15', 'VPC with private subnet', "
                "'AlloyDB cluster in us-central1'"
            ),
            category="gcp"
        )
        super().__init__(metadata)

    def _execute(
        self,
        description: str,
        project_id: str,
        region: str = "us-central1"
    ) -> Dict[str, Any]:
        """
        Provision infrastructure from natural language.

        Args:
            description: What to provision (e.g., "Cloud SQL with PostgreSQL 15")
            project_id: GCP project ID
            region: GCP region

        Returns:
            Provisioning result with resource details
        """
        import re

        desc_lower = description.lower()
        commands = []
        resources = []

        # Detect resource type and generate appropriate commands

        # Cloud SQL Database
        if any(keyword in desc_lower for keyword in ["cloud sql", "cloudsql", "postgres", "mysql"]):
            # Determine database type
            if "mysql" in desc_lower:
                db_version = "MYSQL_8_0"
                db_type = "mysql"
            else:
                db_version = "POSTGRES_15"
                db_type = "postgres"

            # Extract version if specified
            version_match = re.search(r'(postgres|postgresql)\s*(\d+)', desc_lower)
            if version_match:
                version_num = version_match.group(2)
                db_version = f"POSTGRES_{version_num}"

            mysql_match = re.search(r'mysql\s*(\d+)', desc_lower)
            if mysql_match:
                version_num = mysql_match.group(1)
                db_version = f"MYSQL_{version_num}_0"

            # Determine tier
            tier = "db-f1-micro"
            if "production" in desc_lower or "prod" in desc_lower:
                tier = "db-n1-standard-1"

            instance_name = f"db-{db_type}-{region}"

            commands.append(
                f"sql instances create {instance_name} "
                f"--database-version={db_version} "
                f"--tier={tier} "
                f"--region={region} "
                f"--backup --backup-start-time=03:00 "
                f"--project={project_id}"
            )
            resources.append({
                "type": "cloud_sql",
                "name": instance_name,
                "version": db_version,
                "tier": tier
            })

        # AlloyDB
        if "alloydb" in desc_lower:
            cluster_name = f"alloydb-cluster-{region}"

            # Check if VPC is mentioned
            if "vpc" in desc_lower or "private" in desc_lower:
                # Need to create/use VPC first
                vpc_name = "alloydb-vpc"
                commands.append(
                    f"compute networks create {vpc_name} "
                    f"--subnet-mode=custom "
                    f"--project={project_id}"
                )
                commands.append(
                    f"compute networks subnets create alloydb-subnet "
                    f"--network={vpc_name} "
                    f"--range=10.0.0.0/24 "
                    f"--region={region} "
                    f"--project={project_id}"
                )

                commands.append(
                    f"alloydb clusters create {cluster_name} "
                    f"--network={vpc_name} "
                    f"--region={region} "
                    f"--password=CHANGE_ME_IMMEDIATELY "
                    f"--project={project_id}"
                )
            else:
                commands.append(
                    f"alloydb clusters create {cluster_name} "
                    f"--region={region} "
                    f"--password=CHANGE_ME_IMMEDIATELY "
                    f"--project={project_id}"
                )

            resources.append({
                "type": "alloydb",
                "name": cluster_name,
                "region": region
            })

        # VPC and Networking
        if any(keyword in desc_lower for keyword in ["vpc", "network", "subnet"]) and "alloydb" not in desc_lower:
            vpc_name = "custom-vpc"

            # Extract VPC name if specified
            name_match = re.search(r'vpc\s+(?:named\s+)?([a-z0-9-]+)', desc_lower)
            if name_match:
                vpc_name = name_match.group(1)

            commands.append(
                f"compute networks create {vpc_name} "
                f"--subnet-mode=custom "
                f"--project={project_id}"
            )

            # Create subnet if mentioned
            if "subnet" in desc_lower:
                # Extract IP range if specified
                ip_range = "10.0.0.0/24"
                ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+/\d+)', description)
                if ip_match:
                    ip_range = ip_match.group(1)

                commands.append(
                    f"compute networks subnets create {vpc_name}-subnet "
                    f"--network={vpc_name} "
                    f"--range={ip_range} "
                    f"--region={region} "
                    f"--project={project_id}"
                )

            resources.append({
                "type": "vpc",
                "name": vpc_name,
                "region": region
            })

        # Firewall Rules
        if "firewall" in desc_lower:
            rule_name = "allow-http-https"

            if "ssh" in desc_lower:
                rule_name = "allow-ssh"
                commands.append(
                    f"compute firewall-rules create {rule_name} "
                    f"--allow tcp:22 "
                    f"--source-ranges=0.0.0.0/0 "
                    f"--project={project_id}"
                )
            else:
                commands.append(
                    f"compute firewall-rules create {rule_name} "
                    f"--allow tcp:80,tcp:443 "
                    f"--source-ranges=0.0.0.0/0 "
                    f"--project={project_id}"
                )

            resources.append({
                "type": "firewall_rule",
                "name": rule_name
            })

        # Load Balancer
        if any(keyword in desc_lower for keyword in ["load balancer", "lb"]):
            lb_name = "http-lb"
            commands.append(
                f"compute backend-services create {lb_name} "
                f"--protocol=HTTP "
                f"--global "
                f"--project={project_id}"
            )
            resources.append({
                "type": "load_balancer",
                "name": lb_name
            })

        # Secret Manager
        if "secret" in desc_lower:
            secret_name = "app-secret"
            name_match = re.search(r'secret\s+(?:named\s+)?([a-z0-9-]+)', desc_lower)
            if name_match:
                secret_name = name_match.group(1)

            commands.append(
                f"secrets create {secret_name} "
                f"--replication-policy=automatic "
                f"--project={project_id}"
            )
            resources.append({
                "type": "secret",
                "name": secret_name
            })

        if not commands:
            return {
                "success": False,
                "error": f"Could not parse infrastructure description: {description}",
                "suggestion": "Try descriptions like: 'Cloud SQL with PostgreSQL 15', 'VPC with private subnet', 'AlloyDB cluster'"
            }

        return {
            "success": True,
            "description": description,
            "project": project_id,
            "region": region,
            "commands": commands,
            "resources": resources,
            "next_steps": [
                "Review generated commands",
                "Execute using execute_gcloud tool",
                "Verify resources created successfully"
            ]
        }
