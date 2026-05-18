"""Agent factory for creating agents from configurations"""

from typing import Dict, List, Any, Optional
from pathlib import Path

from agent_os.agents.base import BaseAgent
from agent_os.tools.registry import ToolRegistry
from agent_os.utils.logging import get_logger

logger = get_logger("agents.factory")


class AgentFactory:
    """Factory for creating agents from configs with shared registry"""

    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        """
        Initialize factory

        Args:
            tool_registry: Shared tool registry (creates new if None)
        """
        self.registry = tool_registry or ToolRegistry()

    def create(self, config: Dict[str, Any]) -> BaseAgent:
        """
        Create agent from config dict

        Args:
            config: Agent configuration

        Returns:
            BaseAgent instance

        Example:
            factory = AgentFactory()
            agent = factory.create({
                "name": "Researcher",
                "tools": ["wikipedia_search", "arxiv_search"],
                "model": "gpt-4o-mini"
            })
        """
        return BaseAgent.from_config(config, tool_registry=self.registry)

    def create_batch(self, configs: List[Dict[str, Any]]) -> Dict[str, BaseAgent]:
        """
        Create multiple agents from config list

        Args:
            configs: List of agent configurations

        Returns:
            Dictionary mapping agent names to instances
        """
        agents = {}
        for config in configs:
            agent = self.create(config)
            agents[agent.name] = agent
            logger.info(f"Created agent: {agent.name}")

        return agents

    def create_specialized(
        self,
        agent_type: str,
        name: Optional[str] = None,
        **kwargs
    ) -> BaseAgent:
        """
        Create pre-configured specialized agents

        Args:
            agent_type: Type of agent (researcher, analyst, coder, support)
            name: Custom name (optional)
            **kwargs: Additional configuration

        Returns:
            BaseAgent instance
        """
        templates = {
            "researcher": {
                "name": name or "Research Agent",
                "tools": ["wikipedia_search", "arxiv_search", "web_scrape", "citation_generate"],
                "system_prompt": (
                    "You are a research assistant specialized in finding and synthesizing information. "
                    "Always cite sources and provide accurate, well-researched answers. "
                    "Use Wikipedia for general knowledge, ArXiv for academic papers, and web scraping for current information."
                ),
                "temperature": 0,
            },
            "analyst": {
                "name": name or "Data Analyst",
                "tools": ["file_read", "json_process", "csv_process", "pdf_extract_text"],
                "system_prompt": (
                    "You are a data analyst. Process and analyze data from various file formats. "
                    "Provide clear insights, identify patterns, and present findings in a structured way."
                ),
                "temperature": 0,
            },
            "coder": {
                "name": name or "Code Assistant",
                "tools": ["file_read", "web_scrape"],
                "system_prompt": (
                    "You are an expert programmer. Help with code review, debugging, and implementation. "
                    "Provide clean, efficient, production-ready code with proper error handling."
                ),
                "temperature": 0.3,
            },
            "support": {
                "name": name or "Support Agent",
                "tools": ["wikipedia_search", "web_scrape", "file_read"],
                "system_prompt": (
                    "You are a customer support assistant. Provide helpful, accurate, and friendly responses. "
                    "Search for relevant information and guide users through solutions step-by-step."
                ),
                "temperature": 0.5,
            },
        }

        if agent_type not in templates:
            raise ValueError(
                f"Unknown agent type '{agent_type}'. "
                f"Available: {', '.join(templates.keys())}"
            )

        config = templates[agent_type]
        config.update(kwargs)

        return self.create(config)

    def auto_register_tools(self, directory: str = "agent_os/tools/library"):
        """Auto-discover and register tools from directory"""
        count = self.registry.auto_discover(directory)
        logger.info(f"Auto-registered {count} tools")
        return count

    def list_available_tools(self) -> List[str]:
        """List all available tools in registry"""
        return self.registry.list_all()

    def get_registry(self) -> ToolRegistry:
        """Get the tool registry"""
        return self.registry
