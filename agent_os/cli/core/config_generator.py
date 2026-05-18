"""
Config Generator with Pydantic Validation

Generates schema-validated YAML configurations with zero invalid files saved.
Validation happens BEFORE file write - prevents corruption.
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from pydantic import ValidationError

from agent_os.config.schemas import AgentConfig, WorkflowConfig, ToolConfig
from agent_os.cli.utils.session import get_config_path, ensure_agent_os_directories
from agent_os.agents.defaults import (
    is_default_agent,
    get_default_agent_names,
    get_canonical_name,
    load_default_agent,
    load_all_default_agents,
    validate_agent_name as validate_default_name,
)


class ConfigValidationError(Exception):
    """Raised when config validation fails"""

    def __init__(self, errors: List[Dict[str, Any]]):
        self.errors = errors
        super().__init__(self._format_errors(errors))

    def _format_errors(self, errors: List[Dict[str, Any]]) -> str:
        """Format validation errors in human-readable format"""
        lines = ["Configuration validation failed:"]

        for error in errors:
            field = " → ".join(str(x) for x in error["loc"])
            message = error["msg"]
            error_type = error["type"]

            lines.append(f"  • {field}: {message} (type: {error_type})")

        return "\n".join(lines)

    def get_field_errors(self) -> Dict[str, str]:
        """Get errors mapped by field name"""
        return {
            " → ".join(str(x) for x in error["loc"]): error["msg"]
            for error in self.errors
        }


class ProtectedResourceError(Exception):
    """Raised when trying to delete or modify a protected resource"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ConfigGenerator:
    """
    Generate and validate YAML configuration files.

    Features:
    - Pydantic validation BEFORE save (zero invalid files)
    - Field-level error messages
    - Dry-run mode for testing
    - Automatic directory creation
    - Thread-safe file writes
    """

    def __init__(self):
        """Initialize config generator and ensure directories exist"""
        ensure_agent_os_directories()

    def generate_agent_config(
        self,
        name: str,
        tools: List[str],
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
        max_iterations: int = 15,
        max_execution_time: Optional[float] = None,
        memory: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> Tuple[str, Optional[str]]:
        """
        Generate and save agent configuration.

        Args:
            name: Agent name
            tools: List of tool names
            model: LLM model name
            temperature: LLM temperature (0-2)
            system_prompt: Custom system prompt
            max_iterations: Maximum agent iterations
            max_execution_time: Max execution time in seconds
            memory: Memory configuration
            dry_run: If True, validate but don't save

        Returns:
            Tuple of (config_yaml_string, file_path or None)

        Raises:
            ConfigValidationError: If validation fails
            ProtectedResourceError: If name conflicts with a default agent
            ValueError: If name format is invalid
        """
        # Validate name format (security: prevents path traversal, special chars)
        is_valid, error_msg = validate_default_name(name)
        if not is_valid:
            raise ValueError(error_msg)

        # Check for name conflict with default agents (case-insensitive)
        if is_default_agent(name):
            canonical = get_canonical_name(name)
            raise ProtectedResourceError(
                f"Cannot create agent '{name}' - this name is reserved for default agent '{canonical}'. "
                f"Please choose a different name."
            )

        # Build config dict
        config_dict = {
            "name": name,
            "tools": tools,
            "model": model,
            "temperature": temperature,
            "max_iterations": max_iterations,
        }

        if system_prompt is not None:
            config_dict["system_prompt"] = system_prompt
        if max_execution_time is not None:
            config_dict["max_execution_time"] = max_execution_time
        if memory is not None:
            config_dict["memory"] = memory

        # Validate with Pydantic
        try:
            validated_config = AgentConfig(**config_dict)
        except ValidationError as e:
            raise ConfigValidationError(e.errors())

        # Convert to YAML
        yaml_content = yaml.dump(
            validated_config.model_dump(exclude_none=True),
            default_flow_style=False,
            sort_keys=False,
        )

        # Save if not dry-run
        file_path = None
        if not dry_run:
            file_path = get_config_path("agents", name)
            self._atomic_write(file_path, yaml_content)

        return yaml_content, str(file_path) if file_path else None

    def generate_workflow_config(
        self,
        name: str,
        agents: List[str],
        workflow_type: str = "chain",
        routing: Optional[Dict[str, Any]] = None,
        memory: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> Tuple[str, Optional[str]]:
        """
        Generate and save workflow configuration.

        Args:
            name: Workflow name
            agents: List of agent names
            workflow_type: Type of workflow ('chain', 'conditional', 'parallel')
            routing: Routing logic for conditional workflows
            memory: Shared memory configuration
            dry_run: If True, validate but don't save

        Returns:
            Tuple of (config_yaml_string, file_path or None)

        Raises:
            ConfigValidationError: If validation fails
        """
        # Build config dict
        config_dict = {
            "name": name,
            "agents": agents,
            "type": workflow_type,
        }

        if routing is not None:
            config_dict["routing"] = routing
        if memory is not None:
            config_dict["memory"] = memory

        # Validate with Pydantic
        try:
            validated_config = WorkflowConfig(**config_dict)
        except ValidationError as e:
            raise ConfigValidationError(e.errors())

        # Convert to YAML
        yaml_content = yaml.dump(
            validated_config.model_dump(exclude_none=True),
            default_flow_style=False,
            sort_keys=False,
        )

        # Save if not dry-run
        file_path = None
        if not dry_run:
            file_path = get_config_path("workflows", name)
            self._atomic_write(file_path, yaml_content)

        return yaml_content, str(file_path) if file_path else None

    def generate_tool_config(
        self,
        name: str,
        module: str,
        class_name: str,
        allowed_roles: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Tuple[str, Optional[str]]:
        """
        Generate and save tool configuration.

        Args:
            name: Tool name
            module: Python module path
            class_name: Tool class name
            allowed_roles: Roles allowed to use this tool
            dry_run: If True, validate but don't save

        Returns:
            Tuple of (config_yaml_string, file_path or None)

        Raises:
            ConfigValidationError: If validation fails
        """
        # Build config dict
        config_dict = {
            "name": name,
            "module": module,
            "class_name": class_name,
        }

        if allowed_roles is not None:
            config_dict["allowed_roles"] = allowed_roles

        # Validate with Pydantic
        try:
            validated_config = ToolConfig(**config_dict)
        except ValidationError as e:
            raise ConfigValidationError(e.errors())

        # Convert to YAML
        yaml_content = yaml.dump(
            validated_config.model_dump(exclude_none=True),
            default_flow_style=False,
            sort_keys=False,
        )

        # Save if not dry-run
        file_path = None
        if not dry_run:
            file_path = get_config_path("tools", name)
            self._atomic_write(file_path, yaml_content)

        return yaml_content, str(file_path) if file_path else None

    def validate_config(
        self,
        config_type: str,
        config_dict: Dict[str, Any],
    ) -> bool:
        """
        Validate a configuration dictionary without saving.

        Args:
            config_type: Type of config ('agent', 'workflow', 'tool')
            config_dict: Configuration dictionary to validate

        Returns:
            True if valid

        Raises:
            ConfigValidationError: If validation fails
            ValueError: If config_type is invalid
        """
        schema_map = {
            "agent": AgentConfig,
            "workflow": WorkflowConfig,
            "tool": ToolConfig,
        }

        if config_type not in schema_map:
            raise ValueError(
                f"Invalid config_type: {config_type}. "
                f"Must be one of: {', '.join(schema_map.keys())}"
            )

        schema = schema_map[config_type]

        try:
            schema(**config_dict)
            return True
        except ValidationError as e:
            raise ConfigValidationError(e.errors())

    def load_and_validate_config(
        self,
        config_type: str,
        name: str,
    ) -> Dict[str, Any]:
        """
        Load and validate an existing config file.

        Args:
            config_type: Type of config ('agents', 'workflows', 'tools')
            name: Config name

        Returns:
            Validated configuration dictionary

        Raises:
            FileNotFoundError: If config file doesn't exist
            ConfigValidationError: If validation fails
            yaml.YAMLError: If YAML parsing fails
        """
        # Check if this is a default agent
        if config_type == "agents" and is_default_agent(name):
            config_dict = load_default_agent(name)
            # Validate
            self.validate_config("agent", config_dict)
            return config_dict

        # Load from user config directory
        file_path = get_config_path(config_type, name)

        if not file_path.exists():
            raise FileNotFoundError(f"Config not found: {file_path}")

        # Load YAML
        with open(file_path, 'r', encoding='utf-8') as f:
            config_dict = yaml.safe_load(f)

        # Validate
        config_type_singular = config_type.rstrip('s')  # Remove trailing 's'
        self.validate_config(config_type_singular, config_dict)

        return config_dict

    def _atomic_write(self, file_path: Path, content: str):
        """
        Atomic write to prevent file corruption.

        Args:
            file_path: Path to write to
            content: Content to write
        """
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first
        temp_path = file_path.with_suffix('.tmp')

        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # Atomic rename
            temp_path.replace(file_path)

        except Exception as e:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            raise RuntimeError(f"Failed to write config: {e}")

    def list_configs(self, config_type: str) -> List[str]:
        """
        List all saved configurations of a type.

        Args:
            config_type: Type of config ('agents', 'workflows', 'tools')

        Returns:
            List of config names (without .yaml extension)
        """
        ensure_agent_os_directories()
        config_dir = Path.home() / ".agent_os" / "configs" / config_type

        # Get user configs
        user_configs = []
        if config_dir.exists():
            user_configs = [p.stem for p in config_dir.glob("*.yaml")]

        # For agents, include default agents
        if config_type == "agents":
            default_names = get_default_agent_names()
            # Combine defaults + user (defaults first)
            return default_names + [n for n in user_configs if n not in default_names]

        return user_configs

    def list_configs_with_metadata(self, config_type: str) -> List[Dict[str, Any]]:
        """
        List all configurations with metadata (including is_default status).

        Args:
            config_type: Type of config ('agents', 'workflows', 'tools')

        Returns:
            List of dicts with 'name', 'is_default', and 'protected' keys
        """
        ensure_agent_os_directories()
        results = []

        # For agents, include defaults first
        if config_type == "agents":
            for name in get_default_agent_names():
                try:
                    config = load_default_agent(name)
                    results.append({
                        "name": name,
                        "is_default": True,
                        "protected": True,
                        "model": config.get("model", "gpt-4o-mini"),
                        "tools": config.get("tools", []),
                    })
                except FileNotFoundError:
                    continue

        # Get user configs
        config_dir = Path.home() / ".agent_os" / "configs" / config_type
        if config_dir.exists():
            for path in config_dir.glob("*.yaml"):
                name = path.stem
                # Skip if already in defaults
                if config_type == "agents" and is_default_agent(name):
                    continue

                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                    results.append({
                        "name": name,
                        "is_default": False,
                        "protected": False,
                        "model": config.get("model", "gpt-4o-mini"),
                        "tools": config.get("tools", []),
                    })
                except Exception:
                    # Skip invalid configs
                    continue

        return results

    def delete_config(self, config_type: str, name: str) -> bool:
        """
        Delete a configuration file.

        Args:
            config_type: Type of config ('agents', 'workflows', 'tools')
            name: Config name

        Returns:
            True if deleted, False if not found

        Raises:
            ProtectedResourceError: If trying to delete a protected/default agent
        """
        # Check if trying to delete a protected default agent
        if config_type == "agents" and is_default_agent(name):
            raise ProtectedResourceError(
                f"Cannot delete '{name}' - this is a protected default agent."
            )

        file_path = get_config_path(config_type, name)

        if file_path.exists():
            file_path.unlink()
            return True

        return False


def create_config_generator() -> ConfigGenerator:
    """Factory function to create config generator"""
    return ConfigGenerator()
