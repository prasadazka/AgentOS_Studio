"""
Config-Driven Tool Executor

Generic executor that reads YAML tool configs and executes commands.
This is the industry-standard approach used by Terraform, Pulumi, etc.

Usage:
    executor = ConfigExecutor()
    executor.load_configs("path/to/configs")  # Load all YAML configs
    result = executor.execute("cloud_sql", action="create", instance_name="mydb", ...)
"""

import subprocess
import sys
import json
import re
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List

from agent_os.tools.configs.schema import (
    ToolConfig, ToolParameter, ParamType, ToolConfigRegistry
)
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


class ConfigExecutor:
    """Execute tools defined in YAML configs"""

    def __init__(self):
        self.registry = ToolConfigRegistry()
        self._configs_loaded = False

    def load_configs(self, config_dir: str) -> int:
        """
        Load all YAML configs from directory.

        Args:
            config_dir: Path to directory containing .yaml files

        Returns:
            Number of configs loaded
        """
        path = Path(config_dir)
        if not path.exists():
            logger.error(f"Config directory not found: {config_dir}")
            return 0

        loaded = 0
        for yaml_file in path.rglob("*.yaml"):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)

                if data and 'name' in data:
                    config = ToolConfig(**data)
                    self.registry.register(config)
                    loaded += 1
                    logger.debug(f"Loaded config: {config.name}")

            except Exception as e:
                logger.warning(f"Failed to load {yaml_file}: {e}")

        self._configs_loaded = True
        logger.info(f"Loaded {loaded} tool configs from {config_dir}")
        return loaded

    def list_tools(self) -> List[Dict[str, str]]:
        """List all available tools"""
        return [
            {
                "name": config.name,
                "description": config.description,
                "category": config.category
            }
            for config in self.registry.tools.values()
        ]

    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get tool schema for LLM function calling"""
        config = self.registry.get(tool_name)
        if not config:
            return None

        properties = {}
        required = []

        for param in config.parameters:
            prop = {
                "type": self._param_type_to_json(param.type),
                "description": param.description
            }

            if param.enum_values:
                prop["enum"] = param.enum_values

            if param.default is not None:
                prop["default"] = param.default

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "name": config.name,
            "description": config.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }

    def _param_type_to_json(self, param_type: ParamType) -> str:
        """Convert param type to JSON schema type"""
        mapping = {
            ParamType.STRING: "string",
            ParamType.INTEGER: "integer",
            ParamType.BOOLEAN: "boolean",
            ParamType.FLOAT: "number",
            ParamType.LIST: "array",
            ParamType.ENUM: "string"
        }
        return mapping.get(param_type, "string")

    def validate_params(
        self,
        config: ToolConfig,
        params: Dict[str, Any]
    ) -> tuple[bool, List[str]]:
        """
        Validate parameters against config.

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []

        # Check required params
        for param_def in config.parameters:
            if param_def.required and param_def.name not in params:
                if param_def.default is None:
                    errors.append(f"Missing required parameter: {param_def.name}")

        # Validate each provided param
        for name, value in params.items():
            param_def = next(
                (p for p in config.parameters if p.name == name),
                None
            )

            if not param_def:
                # Unknown param - warn but allow
                logger.warning(f"Unknown parameter '{name}' for tool '{config.name}'")
                continue

            # Type validation
            if param_def.type == ParamType.ENUM and param_def.enum_values:
                if value not in param_def.enum_values:
                    errors.append(
                        f"Invalid value for {name}: '{value}'. "
                        f"Must be one of: {param_def.enum_values}"
                    )

            elif param_def.type == ParamType.INTEGER:
                if not isinstance(value, int):
                    try:
                        value = int(value)
                    except:
                        errors.append(f"{name} must be an integer")

                if param_def.min_value and value < param_def.min_value:
                    errors.append(f"{name} must be >= {param_def.min_value}")
                if param_def.max_value and value > param_def.max_value:
                    errors.append(f"{name} must be <= {param_def.max_value}")

            elif param_def.type == ParamType.STRING and param_def.pattern:
                if not re.match(param_def.pattern, str(value)):
                    errors.append(
                        f"Invalid format for {name}: '{value}'. "
                        f"Must match pattern: {param_def.pattern}"
                    )

        return len(errors) == 0, errors

    def build_command(
        self,
        config: ToolConfig,
        params: Dict[str, Any]
    ) -> List[str]:
        """Build command list from config and params"""

        # Get action to determine subcommand
        action = params.get('action', 'create')

        # Start with base command
        cmd_parts = config.command.base.split()

        # Add action as subcommand
        cmd_parts.append(action.replace('_', '-'))

        # Add positional args
        for pos_param in config.command.positional:
            if pos_param in params:
                cmd_parts.append(str(params[pos_param]))

        # Special handling for resource name (usually first positional)
        name_params = ['instance_name', 'bucket_name', 'topic_name', 'subscription_name']
        for np in name_params:
            if np in params and np not in config.command.positional:
                cmd_parts.append(str(params[np]))
                break

        # Add required flags
        for param_name, flag in config.command.flags.items():
            if param_name in params:
                value = params[param_name]
                if isinstance(value, bool):
                    if value:
                        cmd_parts.append(flag)
                else:
                    cmd_parts.extend([flag, str(value)])

        # Add optional flags
        for param_name, flag in config.command.optional_flags.items():
            if param_name in params and params[param_name] is not None:
                value = params[param_name]
                if isinstance(value, bool):
                    if value:
                        cmd_parts.append(flag)
                else:
                    cmd_parts.extend([flag, str(value)])

        # Add format flag for JSON output
        if config.output_format == 'json':
            cmd_parts.extend(['--format', 'json'])

        return cmd_parts

    def execute(
        self,
        tool_name: str,
        dry_run: bool = False,
        **params
    ) -> Dict[str, Any]:
        """
        Execute a tool with given parameters.

        Args:
            tool_name: Name of tool to execute
            dry_run: If True, return command without executing
            **params: Tool parameters

        Returns:
            Dict with success, output, and metadata
        """
        # Get config
        config = self.registry.get(tool_name)
        if not config:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}",
                "available_tools": list(self.registry.tools.keys())
            }

        # Apply defaults
        for param_def in config.parameters:
            if param_def.name not in params and param_def.default is not None:
                params[param_def.name] = param_def.default

        # Validate
        is_valid, errors = self.validate_params(config, params)
        if not is_valid:
            return {
                "success": False,
                "error": "Validation failed",
                "validation_errors": errors
            }

        # Build command
        cmd = self.build_command(config, params)

        # Dry run - just return command
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "command": " ".join(cmd),
                "tool": tool_name,
                "params": params
            }

        # Execute
        try:
            logger.info(f"Executing: {' '.join(cmd)}")

            if sys.platform == "win32":
                # Windows: use shell=True for gcloud
                result = subprocess.run(
                    " ".join(cmd),
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=config.timeout_seconds
                )
            else:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=config.timeout_seconds
                )

            # Check success
            if result.returncode == 0:
                output = result.stdout.strip()

                # Try to parse JSON output
                parsed_output = output
                if config.output_format == 'json' and output:
                    try:
                        parsed_output = json.loads(output)
                    except json.JSONDecodeError:
                        pass

                return {
                    "success": True,
                    "tool": tool_name,
                    "action": params.get('action'),
                    "output": parsed_output,
                    "command": " ".join(cmd)
                }

            else:
                # Check for "already exists" - often not a real error
                stderr = result.stderr.strip()
                if "already exists" in stderr.lower():
                    return {
                        "success": True,
                        "already_exists": True,
                        "tool": tool_name,
                        "message": stderr
                    }

                return {
                    "success": False,
                    "tool": tool_name,
                    "error": stderr,
                    "command": " ".join(cmd)
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {config.timeout_seconds}s",
                "tool": tool_name
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "tool": tool_name
            }

    def get_examples(self, tool_name: str) -> List[Dict[str, Any]]:
        """Get usage examples for a tool"""
        config = self.registry.get(tool_name)
        if not config:
            return []
        return config.examples

    def estimate_cost(self, tool_name: str) -> Optional[str]:
        """Get cost estimate for a tool"""
        config = self.registry.get(tool_name)
        if not config:
            return None
        return config.estimated_cost


# Singleton instance
_executor: Optional[ConfigExecutor] = None


def get_executor() -> ConfigExecutor:
    """Get or create singleton executor"""
    global _executor
    if _executor is None:
        _executor = ConfigExecutor()
        # Auto-load configs from default location
        config_dir = Path(__file__).parent / "gcp"
        if config_dir.exists():
            _executor.load_configs(str(config_dir))
    return _executor


def execute_tool(tool_name: str, **params) -> Dict[str, Any]:
    """Convenience function to execute a tool"""
    return get_executor().execute(tool_name, **params)


def list_tools() -> List[Dict[str, str]]:
    """Convenience function to list tools"""
    return get_executor().list_tools()


def get_tool_schema(tool_name: str) -> Optional[Dict[str, Any]]:
    """Convenience function to get tool schema"""
    return get_executor().get_tool_schema(tool_name)
