"""Configuration loading and validation"""

# Lazy imports to avoid loading heavy dependencies at CLI startup
# from agent_os.config.loader import ConfigLoader
from agent_os.config.schemas import AgentConfig, WorkflowConfig

__all__ = ["ConfigLoader", "AgentConfig", "WorkflowConfig"]


def __getattr__(name):
    """Lazy-load ConfigLoader only when accessed"""
    if name == "ConfigLoader":
        from agent_os.config.loader import ConfigLoader
        return ConfigLoader
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
