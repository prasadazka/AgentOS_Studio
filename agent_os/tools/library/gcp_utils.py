"""
GCP Tools Utility Functions

Shared utilities for GCP tool implementations following best coding practices.
"""

import re
from typing import Optional, Dict, Any, List, Set
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# GCP Regions
DEFAULT_REGION = "us-central1"
VALID_REGIONS = {
    "us-central1", "us-east1", "us-west1", "us-east4",
    "europe-west1", "europe-west2", "europe-north1",
    "asia-south1", "asia-southeast1", "asia-east1"
}

# Database Configuration
DEFAULT_DB_TIER = "db-f1-micro"
PRODUCTION_DB_TIER = "db-n1-standard-1"
VALID_DB_TIERS = {
    "db-f1-micro", "db-g1-small",
    "db-n1-standard-1", "db-n1-standard-2", "db-n1-standard-4",
    "db-n1-highmem-2", "db-n1-highmem-4"
}

# Service Types
DATABASE_TYPES = {"postgres", "mysql", "cloud_sql", "alloydb", "spanner"}
BACKEND_TYPES = {"fastapi", "flask", "express", "spring", "django"}
FRONTEND_TYPES = {"react", "vue", "angular", "nextjs", "svelte"}

# Framework Environment Variables
FRAMEWORK_ENV_VARS = {
    "react": "REACT_APP_API_URL",
    "vue": "VUE_APP_API_URL",
    "angular": "NG_API_URL",
    "nextjs": "NEXT_PUBLIC_API_URL",
    "svelte": "VITE_API_URL"
}

# Database Versions
DATABASE_VERSIONS = {
    "postgres": ["POSTGRES_15", "POSTGRES_14", "POSTGRES_13", "POSTGRES_12"],
    "mysql": ["MYSQL_8_0", "MYSQL_5_7"]
}


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_project_id(project_id: str) -> None:
    """
    Validate GCP project ID format.

    Args:
        project_id: GCP project ID

    Raises:
        ValueError: If project_id is invalid

    Example:
        >>> validate_project_id("my-project-123")
        >>> validate_project_id("invalid project!")  # Raises ValueError
    """
    if not project_id or not project_id.strip():
        raise ValueError("Project ID cannot be empty")

    # GCP project IDs must be 6-30 characters, lowercase letters, digits, hyphens
    # Must start with a letter, cannot end with a hyphen
    pattern = r'^[a-z][-a-z0-9]{4,28}[a-z0-9]$'

    if not re.match(pattern, project_id):
        raise ValueError(
            f"Invalid project ID '{project_id}'. "
            "Must be 6-30 characters, lowercase letters/digits/hyphens, "
            "start with letter, cannot end with hyphen"
        )


def validate_region(region: str) -> None:
    """
    Validate GCP region.

    Args:
        region: GCP region

    Raises:
        ValueError: If region is invalid
    """
    if not region or not region.strip():
        raise ValueError("Region cannot be empty")

    if region not in VALID_REGIONS:
        logger.warning(f"Region '{region}' not in common regions: {VALID_REGIONS}")


def validate_service_type(service_type: str) -> None:
    """
    Validate service type.

    Args:
        service_type: Service type (frontend/backend/database)

    Raises:
        ValueError: If service type is unknown
    """
    all_types = DATABASE_TYPES | BACKEND_TYPES | FRONTEND_TYPES

    if service_type not in all_types:
        raise ValueError(
            f"Unknown service type '{service_type}'. "
            f"Valid types: {all_types}"
        )


def validate_database_tier(tier: str) -> None:
    """
    Validate database tier.

    Args:
        tier: Database tier

    Raises:
        ValueError: If tier is invalid
    """
    if tier not in VALID_DB_TIERS:
        logger.warning(f"Database tier '{tier}' not in common tiers: {VALID_DB_TIERS}")


# ============================================================================
# PARSING FUNCTIONS
# ============================================================================

def parse_database_version(description: str, db_type: str = "postgres") -> str:
    """
    Extract database version from natural language description.

    Args:
        description: Natural language description
        db_type: Database type (postgres/mysql)

    Returns:
        Database version string (e.g., "POSTGRES_15")

    Example:
        >>> parse_database_version("PostgreSQL 15 database", "postgres")
        'POSTGRES_15'
        >>> parse_database_version("MySQL 8 instance", "mysql")
        'MYSQL_8_0'
    """
    desc_lower = description.lower()

    if db_type == "postgres":
        # Look for "postgres 15" or "postgresql 15"
        match = re.search(r'(?:postgres|postgresql)\s*(\d+)', desc_lower)
        if match:
            version = match.group(1)
            return f"POSTGRES_{version}"
        return "POSTGRES_15"  # Default

    elif db_type == "mysql":
        # Look for "mysql 8" or "mysql 5.7"
        match = re.search(r'mysql\s*(\d+)(?:\.(\d+))?', desc_lower)
        if match:
            major = match.group(1)
            minor = match.group(2) or "0"
            return f"MYSQL_{major}_{minor}"
        return "MYSQL_8_0"  # Default

    return ""


def parse_ip_range(description: str) -> Optional[str]:
    """
    Extract IP CIDR range from description.

    Args:
        description: Text containing IP range

    Returns:
        IP range in CIDR notation or None

    Example:
        >>> parse_ip_range("VPC with subnet 10.0.0.0/24")
        '10.0.0.0/24'
        >>> parse_ip_range("private network")
        None
    """
    # Match IPv4 CIDR notation (e.g., 10.0.0.0/24)
    match = re.search(r'(\d+\.\d+\.\d+\.\d+/\d+)', description)
    return match.group(1) if match else None


def detect_environment(text: str) -> str:
    """
    Detect environment from text (dev/staging/prod).

    Args:
        text: Text to analyze (branch name, service name, etc.)

    Returns:
        Environment string: 'dev', 'staging', or 'prod'

    Example:
        >>> detect_environment("main-branch")
        'prod'
        >>> detect_environment("dev-feature-123")
        'dev'
    """
    text_lower = text.lower()

    if any(keyword in text_lower for keyword in ["prod", "production", "main", "master"]):
        return "prod"
    elif "staging" in text_lower or "stage" in text_lower:
        return "staging"
    else:
        return "dev"


# ============================================================================
# FORMATTING FUNCTIONS
# ============================================================================

def format_connection_string(
    db_type: str,
    instance_name: str,
    project_id: str,
    region: str
) -> str:
    """
    Generate database connection string.

    Args:
        db_type: Database type (postgres/mysql/alloydb)
        instance_name: Instance name
        project_id: GCP project ID
        region: GCP region

    Returns:
        Connection string

    Example:
        >>> format_connection_string("postgres", "mydb", "project-123", "us-central1")
        'postgresql://user:pass@/mydb?host=/cloudsql/project-123:us-central1:mydb'
    """
    if db_type in ["postgres", "cloud_sql"]:
        return (
            f"postgresql://user:pass@/{instance_name}"
            f"?host=/cloudsql/{project_id}:{region}:{instance_name}"
        )
    elif db_type == "mysql":
        return (
            f"mysql://user:pass@/{instance_name}"
            f"?unix_socket=/cloudsql/{project_id}:{region}:{instance_name}"
        )
    elif db_type == "alloydb":
        return f"postgresql://user:pass@{instance_name}.{region}.alloydb:5432/postgres"
    else:
        return f"{db_type}://connection-string-placeholder"


def format_service_url(service_name: str, region: str, platform: str = "run") -> str:
    """
    Generate service URL for deployed service.

    Args:
        service_name: Name of the service
        region: GCP region
        platform: Deployment platform (run/appengine/gke)

    Returns:
        Service URL

    Example:
        >>> format_service_url("my-api", "us-central1", "run")
        'https://my-api-us.run.app'
    """
    if platform == "run":
        # Cloud Run URL format: https://SERVICE-REGION.run.app
        region_abbr = region[:2]  # us-central1 -> us
        return f"https://{service_name}-{region_abbr}.run.app"
    elif platform == "appengine":
        return f"https://{service_name}-dot-PROJECT_ID.appspot.com"
    elif platform == "gke":
        return f"http://{service_name}.{region}.svc.cluster.local"
    else:
        return f"https://{service_name}.example.com"


def sanitize_resource_name(name: str) -> str:
    """
    Sanitize resource name to meet GCP naming requirements.

    Args:
        name: Original name

    Returns:
        Sanitized name (lowercase, alphanumeric and hyphens only)

    Example:
        >>> sanitize_resource_name("My_Service_123")
        'my-service-123'
        >>> sanitize_resource_name("Frontend App!")
        'frontend-app'
    """
    # Convert to lowercase
    name = name.lower()

    # Replace underscores and spaces with hyphens
    name = name.replace('_', '-').replace(' ', '-')

    # Remove non-alphanumeric characters except hyphens
    name = re.sub(r'[^a-z0-9-]', '', name)

    # Remove consecutive hyphens
    name = re.sub(r'-+', '-', name)

    # Remove leading/trailing hyphens
    name = name.strip('-')

    # Ensure it starts with a letter
    if name and not name[0].isalpha():
        name = 'svc-' + name

    return name or "service"


# ============================================================================
# SERVICE CATEGORIZATION
# ============================================================================

def get_service_category(service_type: str) -> str:
    """
    Get category for service type.

    Args:
        service_type: Service type

    Returns:
        Category: 'database', 'backend', 'frontend', or 'unknown'

    Example:
        >>> get_service_category("postgres")
        'database'
        >>> get_service_category("react")
        'frontend'
    """
    if service_type in DATABASE_TYPES:
        return "database"
    elif service_type in BACKEND_TYPES:
        return "backend"
    elif service_type in FRONTEND_TYPES:
        return "frontend"
    else:
        return "unknown"


def get_framework_env_var(framework: str) -> str:
    """
    Get environment variable name for framework.

    Args:
        framework: Frontend framework name

    Returns:
        Environment variable name for API URL

    Example:
        >>> get_framework_env_var("react")
        'REACT_APP_API_URL'
        >>> get_framework_env_var("vue")
        'VUE_APP_API_URL'
    """
    return FRAMEWORK_ENV_VARS.get(framework, "API_URL")


# ============================================================================
# COST ESTIMATION
# ============================================================================

def estimate_monthly_cost(
    services: Dict[str, Dict[str, Any]],
    environment: str = "dev"
) -> Dict[str, Any]:
    """
    Estimate monthly cost for services.

    Args:
        services: Services configuration
        environment: Environment (dev/staging/prod)

    Returns:
        Cost breakdown by service and total

    Example:
        >>> estimate_monthly_cost({"db": {"type": "cloud_sql"}}, "prod")
        {'database': 50, 'total': 50, 'environment': 'prod'}
    """
    costs = {}
    total = 0

    # Base costs by environment (very rough estimates)
    environment_multipliers = {
        "dev": 1.0,
        "staging": 3.0,
        "prod": 10.0
    }
    multiplier = environment_multipliers.get(environment, 1.0)

    for service_name, config in services.items():
        service_type = config.get("type", "")
        category = get_service_category(service_type)

        # Rough monthly cost estimates (USD)
        if category == "database":
            tier = config.get("tier", DEFAULT_DB_TIER)
            if "micro" in tier:
                base_cost = 10
            elif "small" in tier:
                base_cost = 25
            else:
                base_cost = 50
            cost = base_cost * multiplier

        elif category in ["backend", "frontend"]:
            # Cloud Run costs (very rough)
            cost = 15 * multiplier

        else:
            cost = 10 * multiplier

        costs[service_name] = round(cost, 2)
        total += cost

    return {
        **costs,
        "total": round(total, 2),
        "environment": environment,
        "note": "Rough estimates. Actual costs depend on usage."
    }


# ============================================================================
# ERROR HANDLING
# ============================================================================

class GCPToolError(Exception):
    """Base exception for GCP tool errors."""
    pass


class ValidationError(GCPToolError):
    """Raised when input validation fails."""
    pass


class DeploymentError(GCPToolError):
    """Raised when deployment fails."""
    pass


class ConfigurationError(GCPToolError):
    """Raised when configuration is invalid."""
    pass
