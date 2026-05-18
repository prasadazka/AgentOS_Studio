"""Agent abstractions and factory"""

# Lazy imports to avoid loading heavy LangChain dependencies at CLI startup
# from agent_os.agents.base import BaseAgent
# from agent_os.agents.factory import AgentFactory

__all__ = ["BaseAgent", "AgentFactory"]


def __getattr__(name):
    """Lazy-load agent modules only when accessed"""
    if name == "BaseAgent":
        from agent_os.agents.base import BaseAgent
        return BaseAgent
    elif name == "AgentFactory":
        from agent_os.agents.factory import AgentFactory
        return AgentFactory
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
