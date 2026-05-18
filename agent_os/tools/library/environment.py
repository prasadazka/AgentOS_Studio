"""
Environment-Aware Deployment Tools for AgentOS

Expert-level DevOps tools for:
- Environment detection (dev/staging/prod)
- Service selection based on environment
- Cost optimization per environment
- Security layer management

Key Principle: Dev/Staging = minimal cost, Prod = full features + security
"""

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from agent_os.tools.base import BaseTool, ToolMetadata


class Environment(str, Enum):
    """Deployment environment types"""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    UNKNOWN = "unknown"


class ServiceTier(str, Enum):
    """Service tier for resource allocation"""
    MINIMAL = "minimal"      # Dev: cheapest possible
    STANDARD = "standard"    # Staging: balanced
    ENTERPRISE = "enterprise"  # Prod: full features


# =============================================================================
# Environment Configuration Profiles
# =============================================================================

ENVIRONMENT_PROFILES = {
    Environment.DEVELOPMENT: {
        "tier": ServiceTier.MINIMAL,
        "description": "Development - Minimal cost, fast iteration",
        "cloud_run": {
            "min_instances": 0,  # Scale to zero when not in use
            "max_instances": 2,
            "cpu": "1",
            "memory": "256Mi",
            "concurrency": 80,
            "timeout": "60s",
            "cpu_throttling": True,  # Throttle CPU when idle
            "startup_cpu_boost": False,
        },
        "cloud_sql": {
            "enabled": False,  # Use SQLite or in-memory for dev
            "tier": None,
            "ha": False,
            "backup": False,
        },
        "redis": {
            "enabled": False,  # Use in-memory cache
            "tier": None,
        },
        "monitoring": {
            "enabled": False,
            "alerting": False,
            "logging_retention_days": 7,
            "uptime_checks": False,
        },
        "security": {
            "waf": False,
            "ddos_protection": False,
            "vpc_connector": False,
            "binary_authorization": False,
            "vulnerability_scanning": False,
            "ssl_policy": "COMPATIBLE",  # Less strict
            "ingress": "all",  # Public access for easy testing
        },
        "networking": {
            "load_balancer": False,
            "cdn": False,
            "custom_domain": False,
        },
        "cost_controls": {
            "budget_alert_threshold": 50,  # $50/month
            "auto_shutdown_enabled": True,
            "shutdown_schedule": "0 20 * * *",  # 8 PM daily
            "startup_schedule": "0 8 * * 1-5",  # 8 AM weekdays
        },
    },

    Environment.STAGING: {
        "tier": ServiceTier.STANDARD,
        "description": "Staging - Production-like but cost-optimized",
        "cloud_run": {
            "min_instances": 0,  # Can scale to zero
            "max_instances": 5,
            "cpu": "1",
            "memory": "512Mi",
            "concurrency": 80,
            "timeout": "300s",
            "cpu_throttling": True,
            "startup_cpu_boost": True,
        },
        "cloud_sql": {
            "enabled": True,
            "tier": "db-f1-micro",  # Smallest instance
            "ha": False,  # No HA for staging
            "backup": True,
            "backup_retention_days": 7,
        },
        "redis": {
            "enabled": True,
            "tier": "BASIC",  # No replication
            "memory_size_gb": 1,
        },
        "monitoring": {
            "enabled": True,
            "alerting": True,
            "logging_retention_days": 30,
            "uptime_checks": True,
            "error_reporting": True,
        },
        "security": {
            "waf": False,  # No WAF for staging
            "ddos_protection": False,
            "vpc_connector": True,  # VPC for internal access
            "binary_authorization": False,
            "vulnerability_scanning": True,
            "ssl_policy": "MODERN",
            "ingress": "internal-and-cloud-load-balancing",
        },
        "networking": {
            "load_balancer": True,
            "cdn": False,
            "custom_domain": True,
        },
        "cost_controls": {
            "budget_alert_threshold": 200,  # $200/month
            "auto_shutdown_enabled": True,
            "shutdown_schedule": "0 22 * * *",  # 10 PM daily
            "startup_schedule": "0 6 * * 1-5",  # 6 AM weekdays
        },
    },

    Environment.PRODUCTION: {
        "tier": ServiceTier.ENTERPRISE,
        "description": "Production - Full features, security, and reliability",
        "cloud_run": {
            "min_instances": 2,  # Always-on for zero cold starts
            "max_instances": 100,
            "cpu": "2",
            "memory": "1Gi",
            "concurrency": 80,
            "timeout": "300s",
            "cpu_throttling": False,  # Full CPU always
            "startup_cpu_boost": True,
        },
        "cloud_sql": {
            "enabled": True,
            "tier": "db-custom-2-4096",  # 2 vCPU, 4GB RAM
            "ha": True,  # High availability
            "backup": True,
            "backup_retention_days": 30,
            "point_in_time_recovery": True,
        },
        "redis": {
            "enabled": True,
            "tier": "STANDARD_HA",  # With replication
            "memory_size_gb": 4,
        },
        "monitoring": {
            "enabled": True,
            "alerting": True,
            "pagerduty_integration": True,
            "logging_retention_days": 365,
            "uptime_checks": True,
            "error_reporting": True,
            "trace_sampling": 0.1,  # 10% trace sampling
            "slo_monitoring": True,
        },
        "security": {
            "waf": True,  # Cloud Armor WAF
            "ddos_protection": True,
            "vpc_connector": True,
            "binary_authorization": True,
            "vulnerability_scanning": True,
            "ssl_policy": "RESTRICTED",  # Strictest
            "ingress": "internal-and-cloud-load-balancing",
            "iap": True,  # Identity-Aware Proxy
            "secret_manager": True,
            "audit_logging": True,
        },
        "networking": {
            "load_balancer": True,
            "cdn": True,
            "custom_domain": True,
            "ssl_certificate": "managed",
        },
        "cost_controls": {
            "budget_alert_threshold": 1000,  # $1000/month
            "auto_shutdown_enabled": False,  # Never shutdown
            "committed_use_discount": True,
        },
    },
}


class EnvironmentDetectionResult(BaseModel):
    """Result of environment detection"""
    success: bool
    environment: Environment = Environment.UNKNOWN
    confidence: float = 0.0
    detection_sources: List[Dict[str, Any]] = Field(default_factory=list)
    profile: Optional[Dict[str, Any]] = None
    recommendations: List[str] = Field(default_factory=list)
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class CostOptimizationResult(BaseModel):
    """Result of cost optimization analysis"""
    success: bool
    environment: Environment
    current_monthly_cost: float = 0.0
    optimized_monthly_cost: float = 0.0
    savings_percent: float = 0.0
    recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    services_to_disable: List[str] = Field(default_factory=list)
    services_to_downgrade: List[Dict[str, str]] = Field(default_factory=list)
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class ServiceSelectionResult(BaseModel):
    """Result of environment-based service selection"""
    success: bool
    environment: Environment
    tier: ServiceTier
    services: Dict[str, Any] = Field(default_factory=dict)
    excluded_services: List[str] = Field(default_factory=list)
    security_layers: List[str] = Field(default_factory=list)
    estimated_monthly_cost: float = 0.0
    cost_comparison: Optional[Dict[str, float]] = None
    error: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class EnvironmentDetectorTool(BaseTool):
    """
    Detect deployment environment from multiple sources.

    Detection sources (in priority order):
    1. Explicit environment variable (ENVIRONMENT, NODE_ENV, etc.)
    2. Git branch name patterns
    3. Git tags
    4. Config file markers
    5. Terraform workspace
    6. Cloud project naming conventions
    """

    # Branch patterns for environment detection
    BRANCH_PATTERNS = {
        Environment.PRODUCTION: [
            r"^main$", r"^master$", r"^release/.*", r"^production$",
            r"^prod$", r"^v\d+\.\d+\.\d+$"
        ],
        Environment.STAGING: [
            r"^staging$", r"^stage$", r"^uat$", r"^qa$",
            r"^pre-prod$", r"^preprod$", r"^develop$"
        ],
        Environment.DEVELOPMENT: [
            r"^dev$", r"^development$", r"^feature/.*", r"^feat/.*",
            r"^fix/.*", r"^hotfix/.*", r"^bugfix/.*", r"^.*-dev$"
        ],
    }

    # Environment variables to check
    ENV_VARS = [
        "ENVIRONMENT", "ENV", "NODE_ENV", "RAILS_ENV", "FLASK_ENV",
        "APP_ENV", "DEPLOY_ENV", "STAGE", "DEPLOYMENT_ENVIRONMENT"
    ]

    # Project name patterns
    PROJECT_PATTERNS = {
        Environment.PRODUCTION: [r".*-prod$", r".*-production$", r".*-prd$"],
        Environment.STAGING: [r".*-staging$", r".*-stage$", r".*-stg$", r".*-uat$"],
        Environment.DEVELOPMENT: [r".*-dev$", r".*-development$", r".*-sandbox$"],
    }

    def __init__(self):
        self._git_path = shutil.which("git")
        self._gcloud_path = shutil.which("gcloud")
        metadata = ToolMetadata(
            name="environment_detector",
            description="Detect deployment environment (dev/staging/prod) from multiple sources",
            category="deployment",
            version="1.0.0",
        )
        super().__init__(metadata)

    def _execute(
        self,
        project_path: str = ".",
        gcp_project_id: Optional[str] = None,
        override_env: Optional[str] = None,
    ) -> str:
        """
        Detect environment from multiple sources.

        Args:
            project_path: Path to project
            gcp_project_id: Optional GCP project ID to analyze
            override_env: Force a specific environment (dev/staging/prod)

        Returns:
            EnvironmentDetectionResult with detected environment and profile
        """
        try:
            # If override provided, use it
            if override_env:
                env = self._parse_env_string(override_env)
                return EnvironmentDetectionResult(
                    success=True,
                    environment=env,
                    confidence=1.0,
                    detection_sources=[{"source": "override", "value": override_env}],
                    profile=ENVIRONMENT_PROFILES.get(env),
                    recommendations=self._get_recommendations(env),
                ).to_json()

            # Collect detection signals
            signals = []

            # 1. Check environment variables
            env_var_signal = self._detect_from_env_vars()
            if env_var_signal:
                signals.append(env_var_signal)

            # 2. Check git branch
            branch_signal = self._detect_from_git_branch(project_path)
            if branch_signal:
                signals.append(branch_signal)

            # 3. Check git tags
            tag_signal = self._detect_from_git_tags(project_path)
            if tag_signal:
                signals.append(tag_signal)

            # 4. Check config files
            config_signal = self._detect_from_config_files(project_path)
            if config_signal:
                signals.append(config_signal)

            # 5. Check GCP project name
            if gcp_project_id:
                project_signal = self._detect_from_project_name(gcp_project_id)
                if project_signal:
                    signals.append(project_signal)

            # 6. Check Terraform workspace
            tf_signal = self._detect_from_terraform(project_path)
            if tf_signal:
                signals.append(tf_signal)

            # Determine environment from signals
            env, confidence = self._resolve_environment(signals)

            return EnvironmentDetectionResult(
                success=True,
                environment=env,
                confidence=confidence,
                detection_sources=signals,
                profile=ENVIRONMENT_PROFILES.get(env),
                recommendations=self._get_recommendations(env),
            ).to_json()

        except Exception as e:
            return EnvironmentDetectionResult(
                success=False,
                error=str(e)
            ).to_json()

    def _detect_from_env_vars(self) -> Optional[Dict]:
        """Detect environment from environment variables"""
        for var_name in self.ENV_VARS:
            value = os.environ.get(var_name, "").lower()
            if value:
                env = self._parse_env_string(value)
                if env != Environment.UNKNOWN:
                    return {
                        "source": "environment_variable",
                        "variable": var_name,
                        "value": value,
                        "environment": env.value,
                        "weight": 0.9,  # High confidence
                    }
        return None

    def _detect_from_git_branch(self, project_path: str) -> Optional[Dict]:
        """Detect environment from git branch name"""
        if not self._git_path:
            return None

        try:
            result = subprocess.run(
                [self._git_path, "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None

            branch = result.stdout.strip()

            for env, patterns in self.BRANCH_PATTERNS.items():
                for pattern in patterns:
                    if re.match(pattern, branch, re.IGNORECASE):
                        return {
                            "source": "git_branch",
                            "branch": branch,
                            "matched_pattern": pattern,
                            "environment": env.value,
                            "weight": 0.8,
                        }
        except Exception:
            pass
        return None

    def _detect_from_git_tags(self, project_path: str) -> Optional[Dict]:
        """Detect environment from git tags (version tags = production)"""
        if not self._git_path:
            return None

        try:
            result = subprocess.run(
                [self._git_path, "describe", "--tags", "--exact-match"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                tag = result.stdout.strip()
                # Version tags indicate production
                if re.match(r"^v?\d+\.\d+\.\d+", tag):
                    return {
                        "source": "git_tag",
                        "tag": tag,
                        "environment": Environment.PRODUCTION.value,
                        "weight": 0.95,  # Very high confidence
                    }
        except Exception:
            pass
        return None

    def _detect_from_config_files(self, project_path: str) -> Optional[Dict]:
        """Detect environment from config files"""
        project = Path(project_path)

        # Check for environment-specific config files
        env_files = {
            ".env.production": Environment.PRODUCTION,
            ".env.prod": Environment.PRODUCTION,
            ".env.staging": Environment.STAGING,
            ".env.stage": Environment.STAGING,
            ".env.development": Environment.DEVELOPMENT,
            ".env.dev": Environment.DEVELOPMENT,
        }

        for filename, env in env_files.items():
            if (project / filename).exists():
                return {
                    "source": "config_file",
                    "file": filename,
                    "environment": env.value,
                    "weight": 0.6,  # Medium confidence
                }

        # Check app.yaml for App Engine
        app_yaml = project / "app.yaml"
        if app_yaml.exists():
            try:
                import yaml
                with open(app_yaml) as f:
                    config = yaml.safe_load(f)
                    service = config.get("service", "default")
                    if "prod" in service.lower():
                        return {"source": "app_yaml", "service": service,
                                "environment": Environment.PRODUCTION.value, "weight": 0.7}
                    elif "staging" in service.lower() or "stage" in service.lower():
                        return {"source": "app_yaml", "service": service,
                                "environment": Environment.STAGING.value, "weight": 0.7}
            except Exception:
                pass

        return None

    def _detect_from_project_name(self, project_id: str) -> Optional[Dict]:
        """Detect environment from GCP project naming convention"""
        for env, patterns in self.PROJECT_PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, project_id, re.IGNORECASE):
                    return {
                        "source": "gcp_project_name",
                        "project_id": project_id,
                        "matched_pattern": pattern,
                        "environment": env.value,
                        "weight": 0.85,
                    }
        return None

    def _detect_from_terraform(self, project_path: str) -> Optional[Dict]:
        """Detect environment from Terraform workspace"""
        tf_path = shutil.which("terraform")
        if not tf_path:
            return None

        try:
            result = subprocess.run(
                [tf_path, "workspace", "show"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                workspace = result.stdout.strip()
                env = self._parse_env_string(workspace)
                if env != Environment.UNKNOWN:
                    return {
                        "source": "terraform_workspace",
                        "workspace": workspace,
                        "environment": env.value,
                        "weight": 0.9,
                    }
        except Exception:
            pass
        return None

    def _parse_env_string(self, value: str) -> Environment:
        """Parse environment from string value"""
        value = value.lower().strip()
        if value in ["prod", "production", "prd", "live"]:
            return Environment.PRODUCTION
        elif value in ["staging", "stage", "stg", "uat", "qa", "pre-prod", "preprod"]:
            return Environment.STAGING
        elif value in ["dev", "development", "local", "sandbox", "test"]:
            return Environment.DEVELOPMENT
        return Environment.UNKNOWN

    def _resolve_environment(self, signals: List[Dict]) -> Tuple[Environment, float]:
        """Resolve final environment from multiple signals using weighted voting"""
        if not signals:
            return Environment.DEVELOPMENT, 0.5  # Default to dev

        # Calculate weighted scores
        scores = {
            Environment.PRODUCTION: 0.0,
            Environment.STAGING: 0.0,
            Environment.DEVELOPMENT: 0.0,
        }

        total_weight = 0.0
        for signal in signals:
            env = Environment(signal["environment"])
            weight = signal.get("weight", 0.5)
            scores[env] += weight
            total_weight += weight

        # Find winner
        winner = max(scores, key=scores.get)
        confidence = scores[winner] / total_weight if total_weight > 0 else 0.5

        return winner, confidence

    def _get_recommendations(self, env: Environment) -> List[str]:
        """Get recommendations for the detected environment"""
        recommendations = []

        if env == Environment.DEVELOPMENT:
            recommendations = [
                "Use min_instances=0 to scale to zero when not in use",
                "Disable Cloud SQL - use SQLite or in-memory database",
                "Disable monitoring and alerting to reduce costs",
                "Enable auto-shutdown schedule (e.g., 8 PM daily)",
                "Use smallest CPU/memory configuration",
                "Skip CDN and load balancer",
            ]
        elif env == Environment.STAGING:
            recommendations = [
                "Enable VPC connector for internal access testing",
                "Use smallest Cloud SQL tier (db-f1-micro)",
                "Enable basic monitoring but skip PagerDuty integration",
                "Consider auto-shutdown outside business hours",
                "Enable vulnerability scanning for pre-prod validation",
            ]
        elif env == Environment.PRODUCTION:
            recommendations = [
                "Set min_instances >= 1 to avoid cold starts",
                "Enable Cloud Armor WAF for DDoS protection",
                "Enable High Availability for Cloud SQL",
                "Configure Binary Authorization for container security",
                "Enable audit logging and 365-day log retention",
                "Set up SLO monitoring and PagerDuty alerts",
            ]

        return recommendations


class ServiceSelectorTool(BaseTool):
    """
    Select and configure services based on detected environment.

    Automatically:
    - Enables/disables services based on environment
    - Configures appropriate resource sizes
    - Adds security layers for production
    - Calculates estimated costs
    """

    # Service costs per month (approximate GCP pricing)
    SERVICE_COSTS = {
        "cloud_run": {
            "minimal": 5,      # Scale to zero, minimal use
            "standard": 30,    # Some always-on instances
            "enterprise": 150,  # Always-on, high resources
        },
        "cloud_sql": {
            "disabled": 0,
            "db-f1-micro": 10,
            "db-g1-small": 30,
            "db-custom-2-4096": 100,
            "db-custom-4-8192": 200,
        },
        "redis": {
            "disabled": 0,
            "BASIC": 30,
            "STANDARD_HA": 100,
        },
        "load_balancer": {
            "disabled": 0,
            "enabled": 20,
        },
        "cdn": {
            "disabled": 0,
            "enabled": 50,
        },
        "waf": {
            "disabled": 0,
            "enabled": 75,
        },
        "monitoring": {
            "minimal": 0,
            "standard": 20,
            "enterprise": 100,
        },
    }

    def __init__(self):
        metadata = ToolMetadata(
            name="service_selector",
            description="Select and configure services based on environment for cost optimization",
            category="deployment",
            version="1.0.0",
        )
        super().__init__(metadata)

    def _execute(
        self,
        environment: str,
        include_services: Optional[List[str]] = None,
        exclude_services: Optional[List[str]] = None,
        custom_overrides: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Select services for the given environment.

        Args:
            environment: Environment name (dev/staging/prod)
            include_services: Force include specific services
            exclude_services: Force exclude specific services
            custom_overrides: Override specific service configurations

        Returns:
            ServiceSelectionResult with selected services and costs
        """
        try:
            env = Environment(environment.lower())
            profile = ENVIRONMENT_PROFILES.get(env, ENVIRONMENT_PROFILES[Environment.DEVELOPMENT])

            # Start with base profile
            services = {}
            excluded = []
            security_layers = []

            # Cloud Run (always needed)
            services["cloud_run"] = profile["cloud_run"].copy()

            # Cloud SQL
            if profile["cloud_sql"]["enabled"]:
                services["cloud_sql"] = profile["cloud_sql"].copy()
            else:
                excluded.append("cloud_sql")

            # Redis
            if profile["redis"]["enabled"]:
                services["redis"] = profile["redis"].copy()
            else:
                excluded.append("redis")

            # Networking
            if profile["networking"]["load_balancer"]:
                services["load_balancer"] = {"enabled": True}
            else:
                excluded.append("load_balancer")

            if profile["networking"]["cdn"]:
                services["cdn"] = {"enabled": True}
            else:
                excluded.append("cdn")

            # Security layers
            security_config = profile["security"]
            if security_config["waf"]:
                security_layers.append("cloud_armor_waf")
                services["waf"] = {"enabled": True}
            if security_config["ddos_protection"]:
                security_layers.append("ddos_protection")
            if security_config["vpc_connector"]:
                security_layers.append("vpc_connector")
            if security_config.get("binary_authorization"):
                security_layers.append("binary_authorization")
            if security_config.get("iap"):
                security_layers.append("identity_aware_proxy")
            if security_config.get("audit_logging"):
                security_layers.append("audit_logging")

            # Monitoring
            services["monitoring"] = profile["monitoring"].copy()

            # Cost controls
            services["cost_controls"] = profile["cost_controls"].copy()

            # Apply includes/excludes
            if include_services:
                for svc in include_services:
                    if svc in excluded:
                        excluded.remove(svc)
                    if svc not in services:
                        services[svc] = {"enabled": True}

            if exclude_services:
                for svc in exclude_services:
                    if svc in services:
                        del services[svc]
                        excluded.append(svc)

            # Apply custom overrides
            if custom_overrides:
                for svc, config in custom_overrides.items():
                    if svc in services:
                        services[svc].update(config)
                    else:
                        services[svc] = config

            # Calculate costs
            estimated_cost = self._calculate_cost(env, services)
            cost_comparison = {
                "development": self._calculate_cost(Environment.DEVELOPMENT, ENVIRONMENT_PROFILES[Environment.DEVELOPMENT]),
                "staging": self._calculate_cost(Environment.STAGING, ENVIRONMENT_PROFILES[Environment.STAGING]),
                "production": self._calculate_cost(Environment.PRODUCTION, ENVIRONMENT_PROFILES[Environment.PRODUCTION]),
            }

            return ServiceSelectionResult(
                success=True,
                environment=env,
                tier=ServiceTier(profile["tier"]),
                services=services,
                excluded_services=excluded,
                security_layers=security_layers,
                estimated_monthly_cost=estimated_cost,
                cost_comparison=cost_comparison,
            ).to_json()

        except Exception as e:
            return ServiceSelectionResult(
                success=False,
                environment=Environment.UNKNOWN,
                tier=ServiceTier.MINIMAL,
                error=str(e),
            ).to_json()

    def _calculate_cost(self, env: Environment, profile_or_services: Dict) -> float:
        """Calculate estimated monthly cost"""
        cost = 0.0

        # Get the right profile
        if "cloud_run" in profile_or_services:
            profile = profile_or_services
        else:
            profile = ENVIRONMENT_PROFILES.get(env, ENVIRONMENT_PROFILES[Environment.DEVELOPMENT])

        # Cloud Run cost based on tier
        tier = profile.get("tier", ServiceTier.MINIMAL)
        if isinstance(tier, str):
            tier = ServiceTier(tier)
        cost += self.SERVICE_COSTS["cloud_run"].get(tier.value, 5)

        # Cloud SQL
        sql_config = profile.get("cloud_sql", {})
        if sql_config.get("enabled"):
            sql_tier = sql_config.get("tier", "db-f1-micro")
            cost += self.SERVICE_COSTS["cloud_sql"].get(sql_tier, 0)

        # Redis
        redis_config = profile.get("redis", {})
        if redis_config.get("enabled"):
            redis_tier = redis_config.get("tier", "BASIC")
            cost += self.SERVICE_COSTS["redis"].get(redis_tier, 0)

        # Networking
        net_config = profile.get("networking", {})
        if net_config.get("load_balancer"):
            cost += self.SERVICE_COSTS["load_balancer"]["enabled"]
        if net_config.get("cdn"):
            cost += self.SERVICE_COSTS["cdn"]["enabled"]

        # Security
        sec_config = profile.get("security", {})
        if sec_config.get("waf"):
            cost += self.SERVICE_COSTS["waf"]["enabled"]

        # Monitoring
        mon_config = profile.get("monitoring", {})
        if mon_config.get("enabled"):
            if mon_config.get("slo_monitoring"):
                cost += self.SERVICE_COSTS["monitoring"]["enterprise"]
            elif mon_config.get("alerting"):
                cost += self.SERVICE_COSTS["monitoring"]["standard"]
            else:
                cost += self.SERVICE_COSTS["monitoring"]["minimal"]

        return cost


class CostOptimizerTool(BaseTool):
    """
    Analyze current deployment and recommend cost optimizations.

    Analyzes:
    - Over-provisioned resources
    - Unused services
    - Environment-appropriate configurations
    - Time-based shutdown opportunities
    """

    def __init__(self):
        self._gcloud_path = shutil.which("gcloud")
        metadata = ToolMetadata(
            name="cost_optimizer",
            description="Analyze deployment and recommend cost optimizations based on environment",
            category="deployment",
            version="1.0.0",
            requires_auth=True,
        )
        super().__init__(metadata)

    def _execute(
        self,
        project_id: str,
        environment: str,
        service_name: Optional[str] = None,
        region: str = "us-central1",
        analyze_usage: bool = True,
    ) -> str:
        """
        Analyze and recommend cost optimizations.

        Args:
            project_id: GCP project ID
            environment: Target environment (dev/staging/prod)
            service_name: Optional specific service to analyze
            region: GCP region
            analyze_usage: Whether to analyze actual usage metrics

        Returns:
            CostOptimizationResult with recommendations
        """
        try:
            env = Environment(environment.lower())
            target_profile = ENVIRONMENT_PROFILES[env]

            recommendations = []
            services_to_disable = []
            services_to_downgrade = []

            current_cost = 0.0
            optimized_cost = 0.0

            # Analyze Cloud Run services
            run_analysis = self._analyze_cloud_run(project_id, region, service_name, env)
            recommendations.extend(run_analysis["recommendations"])
            services_to_downgrade.extend(run_analysis["downgrades"])
            current_cost += run_analysis["current_cost"]
            optimized_cost += run_analysis["optimized_cost"]

            # Analyze Cloud SQL (only check if it should be disabled for dev)
            if env == Environment.DEVELOPMENT:
                sql_analysis = self._analyze_cloud_sql(project_id, env)
                recommendations.extend(sql_analysis["recommendations"])
                if sql_analysis.get("disable"):
                    services_to_disable.append("cloud_sql")
                current_cost += sql_analysis["current_cost"]
                optimized_cost += sql_analysis["optimized_cost"]

            # Analyze monitoring/logging
            mon_analysis = self._analyze_monitoring(project_id, env)
            recommendations.extend(mon_analysis["recommendations"])
            current_cost += mon_analysis["current_cost"]
            optimized_cost += mon_analysis["optimized_cost"]

            # Add time-based shutdown recommendation for non-prod
            if env in [Environment.DEVELOPMENT, Environment.STAGING]:
                recommendations.append({
                    "category": "scheduling",
                    "title": "Enable auto-shutdown outside business hours",
                    "description": f"Configure Cloud Scheduler to shutdown {env.value} resources at night",
                    "estimated_savings": current_cost * 0.3,  # ~30% savings
                    "implementation": f"Set shutdown at {target_profile['cost_controls']['shutdown_schedule']}",
                })
                optimized_cost *= 0.7  # Account for shutdown savings

            # Calculate savings
            savings_percent = ((current_cost - optimized_cost) / current_cost * 100) if current_cost > 0 else 0

            return CostOptimizationResult(
                success=True,
                environment=env,
                current_monthly_cost=current_cost,
                optimized_monthly_cost=optimized_cost,
                savings_percent=round(savings_percent, 1),
                recommendations=recommendations,
                services_to_disable=services_to_disable,
                services_to_downgrade=services_to_downgrade,
            ).to_json()

        except Exception as e:
            return CostOptimizationResult(
                success=False,
                environment=Environment.UNKNOWN,
                error=str(e),
            ).to_json()

    def _analyze_cloud_run(
        self, project_id: str, region: str, service_name: Optional[str], env: Environment
    ) -> Dict:
        """Analyze Cloud Run service configuration"""
        recommendations = []
        downgrades = []
        current_cost = 50.0  # Default estimate
        optimized_cost = current_cost

        target = ENVIRONMENT_PROFILES[env]["cloud_run"]

        if not self._gcloud_path:
            return {
                "recommendations": [],
                "downgrades": [],
                "current_cost": current_cost,
                "optimized_cost": optimized_cost,
            }

        try:
            # Get current service config
            cmd = [self._gcloud_path, "run", "services", "list",
                   "--project", project_id, "--region", region, "--format", "json"]
            if service_name:
                cmd = [self._gcloud_path, "run", "services", "describe", service_name,
                       "--project", project_id, "--region", region, "--format", "json"]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return {"recommendations": [], "downgrades": [],
                        "current_cost": current_cost, "optimized_cost": optimized_cost}

            services = json.loads(result.stdout)
            if not isinstance(services, list):
                services = [services]

            for svc in services:
                template = svc.get("spec", {}).get("template", {})
                annotations = template.get("metadata", {}).get("annotations", {})
                container = template.get("spec", {}).get("containers", [{}])[0]

                svc_name = svc.get("metadata", {}).get("name", "unknown")

                # Check min instances
                min_instances = int(annotations.get("autoscaling.knative.dev/minScale", "0"))
                if min_instances > target["min_instances"]:
                    savings = (min_instances - target["min_instances"]) * 20  # ~$20/instance
                    recommendations.append({
                        "category": "scaling",
                        "service": svc_name,
                        "title": f"Reduce min_instances from {min_instances} to {target['min_instances']}",
                        "description": f"For {env.value}, min_instances={target['min_instances']} is sufficient",
                        "estimated_savings": savings,
                    })
                    current_cost += min_instances * 20
                    optimized_cost += target["min_instances"] * 20

                # Check CPU
                cpu = container.get("resources", {}).get("limits", {}).get("cpu", "1")
                if cpu > target["cpu"]:
                    recommendations.append({
                        "category": "resources",
                        "service": svc_name,
                        "title": f"Reduce CPU from {cpu} to {target['cpu']}",
                        "description": f"For {env.value}, {target['cpu']} CPU is recommended",
                        "estimated_savings": 10,
                    })
                    downgrades.append({"service": svc_name, "resource": "cpu",
                                       "from": cpu, "to": target["cpu"]})

                # Check memory
                memory = container.get("resources", {}).get("limits", {}).get("memory", "512Mi")
                if self._memory_to_mb(memory) > self._memory_to_mb(target["memory"]):
                    recommendations.append({
                        "category": "resources",
                        "service": svc_name,
                        "title": f"Reduce memory from {memory} to {target['memory']}",
                        "description": f"For {env.value}, {target['memory']} is recommended",
                        "estimated_savings": 5,
                    })
                    downgrades.append({"service": svc_name, "resource": "memory",
                                       "from": memory, "to": target["memory"]})

                # Check CPU throttling
                cpu_throttling = annotations.get("run.googleapis.com/cpu-throttling", "true")
                if cpu_throttling == "false" and target["cpu_throttling"]:
                    recommendations.append({
                        "category": "resources",
                        "service": svc_name,
                        "title": "Enable CPU throttling",
                        "description": f"For {env.value}, CPU throttling reduces idle costs",
                        "estimated_savings": 15,
                    })

        except Exception:
            pass

        return {
            "recommendations": recommendations,
            "downgrades": downgrades,
            "current_cost": current_cost,
            "optimized_cost": optimized_cost,
        }

    def _analyze_cloud_sql(self, project_id: str, env: Environment) -> Dict:
        """Analyze Cloud SQL instances"""
        recommendations = []
        current_cost = 0.0
        optimized_cost = 0.0
        should_disable = False

        target = ENVIRONMENT_PROFILES[env]["cloud_sql"]

        if not self._gcloud_path:
            return {"recommendations": [], "current_cost": 0, "optimized_cost": 0, "disable": False}

        try:
            cmd = [self._gcloud_path, "sql", "instances", "list",
                   "--project", project_id, "--format", "json"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                instances = json.loads(result.stdout)
                for instance in instances:
                    tier = instance.get("settings", {}).get("tier", "")
                    name = instance.get("name", "")

                    # Estimate cost based on tier
                    if "custom" in tier:
                        current_cost += 100
                    elif "small" in tier:
                        current_cost += 30
                    elif "micro" in tier:
                        current_cost += 10

                    if not target["enabled"]:
                        recommendations.append({
                            "category": "database",
                            "title": f"Consider disabling Cloud SQL for {env.value}",
                            "description": "Use SQLite or in-memory database for development",
                            "estimated_savings": current_cost,
                        })
                        should_disable = True
                        optimized_cost = 0
                    else:
                        if target["tier"] and tier != target["tier"]:
                            recommendations.append({
                                "category": "database",
                                "instance": name,
                                "title": f"Downgrade SQL tier from {tier} to {target['tier']}",
                                "description": f"Smaller tier is sufficient for {env.value}",
                                "estimated_savings": current_cost - 10,
                            })
                            optimized_cost = 10

        except Exception:
            pass

        return {
            "recommendations": recommendations,
            "current_cost": current_cost,
            "optimized_cost": optimized_cost,
            "disable": should_disable,
        }

    def _analyze_monitoring(self, project_id: str, env: Environment) -> Dict:
        """Analyze monitoring configuration"""
        recommendations = []
        target = ENVIRONMENT_PROFILES[env]["monitoring"]

        current_cost = 50.0  # Assume some monitoring cost
        optimized_cost = current_cost

        if not target["enabled"]:
            recommendations.append({
                "category": "monitoring",
                "title": f"Reduce monitoring for {env.value}",
                "description": "Disable alerting and reduce log retention for development",
                "estimated_savings": 40,
            })
            optimized_cost = 10
        elif not target.get("slo_monitoring"):
            recommendations.append({
                "category": "monitoring",
                "title": "Skip SLO monitoring for non-production",
                "description": "SLO monitoring adds cost and is mainly needed for production",
                "estimated_savings": 20,
            })
            optimized_cost = 30

        return {
            "recommendations": recommendations,
            "current_cost": current_cost,
            "optimized_cost": optimized_cost,
        }

    def _memory_to_mb(self, memory: str) -> int:
        """Convert memory string to MB"""
        memory = memory.lower()
        if "gi" in memory:
            return int(float(memory.replace("gi", "")) * 1024)
        elif "mi" in memory:
            return int(float(memory.replace("mi", "")))
        elif "g" in memory:
            return int(float(memory.replace("g", "")) * 1024)
        elif "m" in memory:
            return int(float(memory.replace("m", "")))
        return 512  # Default


class SecurityLayerTool(BaseTool):
    """
    Configure security layers based on environment.

    Security by environment:
    - Dev: Basic (auth only)
    - Staging: Standard (auth + VPC)
    - Prod: Enterprise (full WAF, DDoS, IAP, audit logging)
    """

    def __init__(self):
        self._gcloud_path = shutil.which("gcloud")
        metadata = ToolMetadata(
            name="security_layer_config",
            description="Configure security layers (WAF, VPC, IAP, audit) based on environment",
            category="security",
            version="1.0.0",
            requires_auth=True,
        )
        super().__init__(metadata)

    def _execute(
        self,
        environment: str,
        project_id: Optional[str] = None,
        service_name: Optional[str] = None,
        region: str = "us-central1",
        dry_run: bool = True,
    ) -> str:
        """
        Configure security layers for the environment.

        Args:
            environment: Target environment
            project_id: GCP project ID
            service_name: Service to configure
            region: GCP region
            dry_run: If True, only show what would be configured

        Returns:
            Security configuration plan or execution result
        """
        try:
            env = Environment(environment.lower())
            profile = ENVIRONMENT_PROFILES[env]["security"]

            security_config = {
                "environment": env.value,
                "layers": [],
                "commands": [],
                "estimated_monthly_cost": 0.0,
            }

            # WAF (Cloud Armor)
            if profile["waf"]:
                security_config["layers"].append({
                    "name": "cloud_armor_waf",
                    "description": "Cloud Armor WAF with OWASP rules",
                    "enabled": True,
                })
                security_config["commands"].append(
                    f"gcloud compute security-policies create {service_name}-policy --project {project_id}"
                )
                security_config["estimated_monthly_cost"] += 75

            # DDoS Protection
            if profile["ddos_protection"]:
                security_config["layers"].append({
                    "name": "ddos_protection",
                    "description": "Cloud Armor DDoS protection",
                    "enabled": True,
                })

            # VPC Connector
            if profile["vpc_connector"]:
                security_config["layers"].append({
                    "name": "vpc_connector",
                    "description": "Serverless VPC Access connector",
                    "enabled": True,
                })
                security_config["commands"].append(
                    f"gcloud compute networks vpc-access connectors create {service_name}-connector "
                    f"--region {region} --network default --range 10.8.0.0/28 --project {project_id}"
                )
                security_config["estimated_monthly_cost"] += 10

            # Binary Authorization
            if profile.get("binary_authorization"):
                security_config["layers"].append({
                    "name": "binary_authorization",
                    "description": "Container image verification",
                    "enabled": True,
                })
                security_config["commands"].append(
                    f"gcloud container binauthz policy import policy.yaml --project {project_id}"
                )

            # Identity-Aware Proxy
            if profile.get("iap"):
                security_config["layers"].append({
                    "name": "identity_aware_proxy",
                    "description": "Google Identity-Aware Proxy",
                    "enabled": True,
                })

            # Audit Logging
            if profile.get("audit_logging"):
                security_config["layers"].append({
                    "name": "audit_logging",
                    "description": "Data access audit logs",
                    "enabled": True,
                })

            # Ingress settings
            security_config["ingress"] = profile["ingress"]
            security_config["ssl_policy"] = profile["ssl_policy"]

            # If not dry run, execute commands
            if not dry_run and self._gcloud_path and project_id:
                execution_results = []
                for cmd in security_config["commands"]:
                    try:
                        result = subprocess.run(
                            cmd.split(),
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        execution_results.append({
                            "command": cmd,
                            "success": result.returncode == 0,
                            "output": result.stdout or result.stderr,
                        })
                    except Exception as e:
                        execution_results.append({
                            "command": cmd,
                            "success": False,
                            "error": str(e),
                        })
                security_config["execution_results"] = execution_results

            return json.dumps({
                "success": True,
                "dry_run": dry_run,
                "security_config": security_config,
            }, indent=2)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
            }, indent=2)
