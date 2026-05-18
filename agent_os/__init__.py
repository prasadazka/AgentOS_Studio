"""
Agent_OS: Lightweight framework for building production-grade AI agents

Eliminates 80% of boilerplate in AI agent development.
Build complex multi-agent systems in 10-20 lines of config instead of 100+ lines of code.
"""

__version__ = "0.1.0"

# Lazy imports using __getattr__ for fast CLI startup
# Heavy dependencies only loaded when actually used


def __getattr__(name):
    """Lazy-load heavy dependencies only when accessed"""
    if name == "BaseTool":
        from agent_os.tools.base import BaseTool
        return BaseTool
    elif name == "ToolMetadata":
        from agent_os.tools.base import ToolMetadata
        return ToolMetadata
    elif name == "ToolRegistry":
        from agent_os.tools.registry import ToolRegistry
        return ToolRegistry
    elif name == "BaseAgent":
        from agent_os.agents.base import BaseAgent
        return BaseAgent
    elif name == "AgentFactory":
        from agent_os.agents.factory import AgentFactory
        return AgentFactory
    elif name == "ConfigLoader":
        from agent_os.config.loader import ConfigLoader
        return ConfigLoader
    elif name == "AgentConfig":
        from agent_os.config.schemas import AgentConfig
        return AgentConfig
    elif name == "WorkflowConfig":
        from agent_os.config.schemas import WorkflowConfig
        return WorkflowConfig
    elif name == "WorkflowBuilder":
        from agent_os.workflows.builder import WorkflowBuilder
        return WorkflowBuilder
    elif name == "cli":
        from agent_os.cli.app import cli
        return cli
    elif name == "ConversationManager":
        from agent_os.cli.core.conversation_manager import ConversationManager
        return ConversationManager
    elif name == "ConfigGenerator":
        from agent_os.cli.core.config_generator import ConfigGenerator
        return ConfigGenerator
    elif name == "IntentParser":
        from agent_os.cli.core.intent_parser import IntentParser
        return IntentParser
    elif name == "create_intent_parser":
        from agent_os.cli.core.intent_parser import create_intent_parser
        return create_intent_parser
    elif name == "ExecutionEngine":
        from agent_os.cli.core.execution_engine import ExecutionEngine
        return ExecutionEngine
    elif name == "ExecutionResult":
        from agent_os.cli.core.execution_engine import ExecutionResult
        return ExecutionResult
    elif name == "ExecutionStatus":
        from agent_os.cli.core.execution_engine import ExecutionStatus
        return ExecutionStatus
    elif name == "Agent":
        from agent_os._api import Agent
        return Agent
    elif name == "Workflow":
        from agent_os._api import Workflow
        return Workflow
    elif name == "ExecutableWorkflow":
        from agent_os._api import ExecutableWorkflow
        return ExecutableWorkflow
    elif name == "Tool":
        from agent_os._api import Tool
        return Tool
    # Testing utilities
    elif name == "testing":
        from agent_os import testing
        return testing
    elif name == "assert_uses_tool":
        from agent_os.testing import assert_uses_tool
        return assert_uses_tool
    elif name == "assert_output_contains":
        from agent_os.testing import assert_output_contains
        return assert_output_contains
    elif name == "assert_output_not_contains":
        from agent_os.testing import assert_output_not_contains
        return assert_output_not_contains
    elif name == "assert_cost_under":
        from agent_os.testing import assert_cost_under
        return assert_cost_under
    elif name == "assert_time_under":
        from agent_os.testing import assert_time_under
        return assert_time_under
    elif name == "AgentTestCase":
        from agent_os.testing import AgentTestCase
        return AgentTestCase
    elif name == "AgentTestError":
        from agent_os.testing import AgentTestError
        return AgentTestError
    elif name == "ReliabilityConfig":
        from agent_os.config.schemas import ReliabilityConfig
        return ReliabilityConfig
    else:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    # Simplified APIs
    "Agent",
    "Workflow",
    "ExecutableWorkflow",
    "Tool",
    # Core components
    "BaseTool",
    "ToolMetadata",
    "ToolRegistry",
    "BaseAgent",
    "AgentFactory",
    "ConfigLoader",
    "AgentConfig",
    "WorkflowConfig",
    "WorkflowBuilder",
    # CLI components
    "cli",
    "ConversationManager",
    "ConfigGenerator",
    "IntentParser",
    "create_intent_parser",
    "ExecutionEngine",
    "ExecutionResult",
    "ExecutionStatus",
    # Testing utilities
    "testing",
    "assert_uses_tool",
    "assert_output_contains",
    "assert_output_not_contains",
    "assert_cost_under",
    "assert_time_under",
    "AgentTestCase",
    "AgentTestError",
    # Configuration
    "ReliabilityConfig",
]
