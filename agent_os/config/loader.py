"""Configuration loading and validation"""

import yaml
import json
from pathlib import Path
from typing import Union, Dict, Any, List, Optional

from agent_os.config.schemas import AgentConfig, WorkflowConfig, ProjectConfig
from agent_os.agents.factory import AgentFactory
from agent_os.agents.base import BaseAgent
from agent_os.tools.registry import ToolRegistry
from agent_os.utils.logging import get_logger
from agent_os.utils.errors import ConfigLoadError

logger = get_logger("config.loader")


class ConfigLoader:
    """Load and validate agent/workflow configurations from files"""

    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        """
        Initialize loader

        Args:
            tool_registry: Shared tool registry
        """
        self.registry = tool_registry or ToolRegistry()
        self.factory = AgentFactory(self.registry)

    @staticmethod
    def load_yaml(path: Union[str, Path]) -> Dict[str, Any]:
        """
        Load YAML file

        Args:
            path: Path to YAML file

        Returns:
            Parsed configuration dictionary
        """
        path = Path(path)

        if not path.exists():
            raise ConfigLoadError(f"Config file not found: {path}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if data is None:
                raise ConfigLoadError(f"Empty YAML file: {path}")

            return data

        except yaml.YAMLError as e:
            raise ConfigLoadError(f"Invalid YAML in {path}: {e}")
        except Exception as e:
            raise ConfigLoadError(f"Error loading {path}: {e}")

    @staticmethod
    def load_json(path: Union[str, Path]) -> Dict[str, Any]:
        """Load JSON file"""
        path = Path(path)

        if not path.exists():
            raise ConfigLoadError(f"Config file not found: {path}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data

        except json.JSONDecodeError as e:
            raise ConfigLoadError(f"Invalid JSON in {path}: {e}")
        except Exception as e:
            raise ConfigLoadError(f"Error loading {path}: {e}")

    @staticmethod
    def load_file(path: Union[str, Path]) -> Dict[str, Any]:
        """
        Load config file (auto-detect format)

        Args:
            path: Path to config file (.yaml, .yml, or .json)

        Returns:
            Parsed configuration
        """
        path = Path(path)
        suffix = path.suffix.lower()

        if suffix in ('.yaml', '.yml'):
            return ConfigLoader.load_yaml(path)
        elif suffix == '.json':
            return ConfigLoader.load_json(path)
        else:
            raise ConfigLoadError(f"Unsupported file format: {suffix}")

    def load_agent_config(self, path: Union[str, Path]) -> AgentConfig:
        """
        Load and validate agent configuration

        Args:
            path: Path to agent config file

        Returns:
            Validated AgentConfig
        """
        data = self.load_file(path)
        try:
            config = AgentConfig(**data)
            logger.info(f"Loaded agent config: {config.name}")
            return config

        except Exception as e:
            raise ConfigLoadError(f"Invalid agent config in {path}: {e}")

    def load_workflow_config(self, path: Union[str, Path]) -> WorkflowConfig:
        """Load and validate workflow configuration"""
        data = self.load_file(path)
        try:
            config = WorkflowConfig(**data)
            logger.info(f"Loaded workflow config: {config.name}")
            return config

        except Exception as e:
            raise ConfigLoadError(f"Invalid workflow config in {path}: {e}")

    def load_project_config(self, path: Union[str, Path]) -> ProjectConfig:
        """Load and validate complete project configuration"""
        data = self.load_file(path)
        try:
            config = ProjectConfig(**data)
            logger.info(f"Loaded project config: {config.project_name}")
            return config

        except Exception as e:
            raise ConfigLoadError(f"Invalid project config in {path}: {e}")

    def create_agent_from_file(self, path: Union[str, Path]) -> BaseAgent:
        """
        Create agent from config file

        Args:
            path: Path to agent config file

        Returns:
            BaseAgent instance
        """
        config = self.load_agent_config(path)
        return self.factory.create(config.model_dump())

    def create_agents_from_directory(self, directory: Union[str, Path]) -> Dict[str, BaseAgent]:
        """
        Load all agent configs from directory

        Args:
            directory: Directory containing agent config files

        Returns:
            Dictionary mapping agent names to instances
        """
        directory = Path(directory)

        if not directory.exists():
            raise ConfigLoadError(f"Directory not found: {directory}")

        agents = {}
        for file_path in directory.glob("*.{yaml,yml,json}"):
            try:
                agent = self.create_agent_from_file(file_path)
                agents[agent.name] = agent
                logger.info(f"Loaded agent from {file_path.name}: {agent.name}")

            except Exception as e:
                logger.error(f"Failed to load {file_path.name}: {e}")

        return agents

    def create_from_project_config(self, path: Union[str, Path]) -> Dict[str, Any]:
        """
        Create agents and workflows from project config

        Args:
            path: Path to project config file

        Returns:
            Dictionary with 'agents' and 'workflows' keys
        """
        config = self.load_project_config(path)

        if config.registry.auto_discover:
            for directory in config.registry.directories:
                self.factory.auto_register_tools(directory)

        for tool_config in config.registry.tools:
            self.registry.register_lazy(
                name=tool_config.name,
                module_path=tool_config.module,
                class_name=tool_config.class_name,
                allowed_roles=tool_config.allowed_roles
            )

        agents = {}
        for agent_config in config.agents:
            agent = self.factory.create(agent_config.model_dump())
            agents[agent.name] = agent

        logger.info(f"Created project '{config.project_name}' with {len(agents)} agents")

        return {
            "project": config.project_name,
            "version": config.version,
            "agents": agents,
            "workflows": config.workflows
        }

    @staticmethod
    def save_config(config: Union[AgentConfig, WorkflowConfig, ProjectConfig], path: Union[str, Path]):
        """
        Save configuration to file

        Args:
            config: Configuration object
            path: Output file path
        """
        path = Path(path)
        data = config.model_dump(exclude_none=True)

        if path.suffix in ('.yaml', '.yml'):
            with open(path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

        elif path.suffix == '.json':
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

        else:
            raise ConfigLoadError(f"Unsupported file format: {path.suffix}")

        logger.info(f"Saved config to {path}")
