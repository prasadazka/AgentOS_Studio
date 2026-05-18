"""
Default Agent Templates

Built-in agents that come pre-installed with AgentOS.
These agents cannot be deleted or edited by users.

Available default agents:
- DataAnalyst: CSV, JSON, SQL data analysis
- Researcher: Wikipedia, ArXiv academic research
- Developer: Git operations, code review
- SupportAgent: Customer support, FAQ handling
- CodeReviewer: Code analysis and review
- Deployer: GCP deployment automation
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from functools import lru_cache

import yaml

# Directory containing default agent YAML files
DEFAULTS_DIR = Path(__file__).parent

# Canonical names (case-sensitive storage)
DEFAULT_AGENT_NAMES = [
    "DataAnalyst",
    "Researcher",
    "Developer",
    "SupportAgent",
    "CodeReviewer",
    "Deployer",
]

# Case-insensitive lookup map for security
_NAME_LOOKUP: Dict[str, str] = {name.lower(): name for name in DEFAULT_AGENT_NAMES}

# Precompiled regex for name conversion
_CAMEL_PATTERN1 = re.compile(r'(.)([A-Z][a-z]+)')
_CAMEL_PATTERN2 = re.compile(r'([a-z0-9])([A-Z])')

# Valid name pattern (alphanumeric + underscore, no path traversal)
_VALID_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*$')


def get_default_agent_names() -> List[str]:
    """Get list of all default agent names (canonical casing)"""
    return DEFAULT_AGENT_NAMES.copy()


def is_default_agent(name: str) -> bool:
    """
    Check if an agent name matches a default agent (case-insensitive).

    Security: Prevents bypass via case variations (e.g., 'dataanalyst' vs 'DataAnalyst')
    """
    if not name or not isinstance(name, str):
        return False
    return name.lower() in _NAME_LOOKUP


def get_canonical_name(name: str) -> Optional[str]:
    """Get canonical (properly cased) name for a default agent"""
    if not name:
        return None
    return _NAME_LOOKUP.get(name.lower())


def validate_agent_name(name: str) -> tuple[bool, Optional[str]]:
    """
    Validate agent name for security and format.

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, "Agent name cannot be empty"

    if not isinstance(name, str):
        return False, "Agent name must be a string"

    # Length check
    if len(name) > 64:
        return False, "Agent name too long (max 64 characters)"

    # Path traversal prevention
    if '..' in name or '/' in name or '\\' in name:
        return False, "Agent name contains invalid characters"

    # Format validation
    if not _VALID_NAME_PATTERN.match(name):
        return False, "Agent name must start with a letter and contain only alphanumeric characters and underscores"

    return True, None


@lru_cache(maxsize=16)
def load_default_agent(name: str) -> Dict[str, Any]:
    """
    Load a default agent configuration by name (cached).

    Args:
        name: Agent name (case-insensitive)

    Returns:
        Agent configuration dictionary (deep copy)

    Raises:
        FileNotFoundError: If agent doesn't exist
        ValueError: If name is invalid
    """
    # Validate input
    if not name or not isinstance(name, str):
        raise ValueError("Invalid agent name")

    # Get canonical name (case-insensitive lookup)
    canonical = get_canonical_name(name)
    if not canonical:
        raise FileNotFoundError(f"Default agent '{name}' not found")

    # Convert to filename
    filename = _name_to_filename(canonical)
    filepath = DEFAULTS_DIR / filename

    # Security: Ensure path is within DEFAULTS_DIR
    try:
        filepath = filepath.resolve()
        if not str(filepath).startswith(str(DEFAULTS_DIR.resolve())):
            raise ValueError(f"Invalid agent path: {filepath}")
    except (OSError, ValueError) as e:
        raise FileNotFoundError(f"Invalid agent path: {e}")

    if not filepath.exists():
        raise FileNotFoundError(f"Default agent file not found: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # Return a copy to prevent cache mutation
    return dict(config) if config else {}


def load_all_default_agents() -> List[Dict[str, Any]]:
    """Load all default agent configurations"""
    agents = []
    for name in DEFAULT_AGENT_NAMES:
        try:
            config = load_default_agent(name)
            agents.append(config)
        except (FileNotFoundError, ValueError):
            # Log but don't crash - missing defaults shouldn't break the system
            continue
    return agents


def clear_cache():
    """Clear the default agent cache (useful for testing)"""
    load_default_agent.cache_clear()


def _name_to_filename(name: str) -> str:
    """Convert agent name to filename (CamelCase to snake_case.yaml)"""
    s1 = _CAMEL_PATTERN1.sub(r'\1_\2', name)
    filename = _CAMEL_PATTERN2.sub(r'\1_\2', s1).lower()
    return f"{filename}.yaml"
