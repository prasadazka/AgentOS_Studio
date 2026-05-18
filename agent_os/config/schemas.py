"""Pydantic schemas for configuration validation"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any, Literal, Union
from dataclasses import dataclass, field as dataclass_field


# =============================================================================
# Reliability Configuration (for simplified Agent API)
# =============================================================================

@dataclass
class ReliabilityConfig:
    """
    Configuration for agent reliability features.

    Groups all advanced options into a single object for cleaner API.
    Use with Agent.create() for fine-grained control.

    Example:
        from agent_os import Agent
        from agent_os.config.schemas import ReliabilityConfig

        # Default: all features enabled with sensible defaults
        config = ReliabilityConfig()

        # Custom: disable some features, set budget
        config = ReliabilityConfig(
            circuit_breaker=True,
            cost_tracking=True,
            budget_limit=10.0,  # $10 daily limit
            rate_limiting=False,  # Disable rate limiting
            max_execution_time=30.0  # 30 second timeout
        )

        agent = Agent.create(
            name="MyAgent",
            tools=["wikipedia_search"],
            config=config
        )
    """

    # Circuit breaker (prevents cascading failures)
    circuit_breaker: bool = True
    circuit_breaker_threshold: int = 5  # Failures before circuit opens
    circuit_breaker_timeout: float = 60.0  # Seconds before retry

    # Cost tracking
    cost_tracking: bool = True
    budget_limit: Optional[float] = None  # Budget in dollars
    budget_window: str = "daily"  # "hourly", "daily", "monthly", "total"

    # Rate limiting (prevents API throttling)
    rate_limiting: bool = True
    tokens_per_minute: Optional[int] = None  # TPM limit
    requests_per_minute: Optional[int] = None  # RPM limit

    # Retry with backoff (handles transient failures)
    retry: bool = True
    max_retries: int = 3
    retry_base_delay: float = 1.0  # Base delay in seconds

    # Metrics collection
    metrics: bool = True

    # Execution limits
    max_iterations: int = 15
    max_execution_time: Optional[float] = None  # Seconds

    def to_agent_kwargs(self) -> Dict[str, Any]:
        """Convert config to BaseAgent constructor kwargs."""
        from agent_os.utils.cost_tracker import Budget
        from agent_os.utils.rate_limiter import RateLimitConfig
        from agent_os.utils.retry import RetryConfig

        kwargs = {
            "max_iterations": self.max_iterations,
            "max_execution_time": self.max_execution_time,
            "enable_circuit_breaker": self.circuit_breaker,
            "circuit_breaker_threshold": self.circuit_breaker_threshold,
            "circuit_breaker_timeout": self.circuit_breaker_timeout,
            "enable_cost_tracking": self.cost_tracking,
            "enable_rate_limiting": self.rate_limiting,
            "enable_retry": self.retry,
            "enable_metrics": self.metrics,
        }

        # Budget configuration
        if self.cost_tracking and self.budget_limit is not None:
            kwargs["budget"] = Budget(
                limit=self.budget_limit,
                window=self.budget_window
            )

        # Rate limit configuration
        if self.rate_limiting and (self.tokens_per_minute or self.requests_per_minute):
            kwargs["rate_limit_config"] = RateLimitConfig(
                tokens_per_minute=self.tokens_per_minute or 90000,
                requests_per_minute=self.requests_per_minute or 500
            )

        # Retry configuration
        if self.retry:
            kwargs["retry_config"] = RetryConfig(
                max_retries=self.max_retries,
                base_delay=self.retry_base_delay
            )

        return kwargs

    @classmethod
    def minimal(cls) -> "ReliabilityConfig":
        """
        Create config with minimal overhead (most features disabled).

        Useful for testing or low-latency scenarios.
        """
        return cls(
            circuit_breaker=False,
            cost_tracking=False,
            rate_limiting=False,
            retry=False,
            metrics=False
        )

    @classmethod
    def production(cls, daily_budget: float = 100.0) -> "ReliabilityConfig":
        """
        Create config optimized for production use.

        All safety features enabled with reasonable defaults.
        """
        return cls(
            circuit_breaker=True,
            circuit_breaker_threshold=3,
            circuit_breaker_timeout=120.0,
            cost_tracking=True,
            budget_limit=daily_budget,
            budget_window="daily",
            rate_limiting=True,
            retry=True,
            max_retries=3,
            metrics=True,
            max_iterations=20,
            max_execution_time=60.0
        )


class MemoryConfig(BaseModel):
    """Schema for memory configuration"""

    enabled: bool = Field(default=True, description="Enable memory features")

    # Short-term memory (conversation buffer)
    short_term_max_messages: int = Field(
        default=50,
        ge=10,
        le=500,
        description="Max messages to keep in conversation buffer"
    )
    short_term_persist: bool = Field(
        default=True,
        description="Persist short-term memory to disk"
    )

    # Long-term memory (semantic/vector)
    long_term_enabled: bool = Field(
        default=True,
        description="Enable semantic vector memory (requires ChromaDB)"
    )
    long_term_provider: Literal["chromadb", "qdrant", "pinecone"] = Field(
        default="chromadb",
        description="Vector database provider"
    )
    long_term_collection: Optional[str] = Field(
        default=None,
        description="Collection name (defaults to agent name)"
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model for semantic search"
    )

    # Episodic memory (action history)
    episodic_enabled: bool = Field(
        default=True,
        description="Enable action/tool execution history"
    )
    episodic_retention_days: int = Field(
        default=90,
        ge=1,
        le=365,
        description="Days to retain action history"
    )

    # Storage paths
    persist_path: Optional[str] = Field(
        default=None,
        description="Base path for memory storage (defaults to ~/.agent_os/memory)"
    )

    # Cross-agent sharing
    enable_cross_agent_sharing: bool = Field(
        default=False,
        description="Enable cross-agent context sharing in workflows"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "short_term_max_messages": 50,
                "short_term_persist": True,
                "long_term_enabled": True,
                "long_term_provider": "chromadb",
                "episodic_enabled": True,
                "episodic_retention_days": 90
            }
        }


class AgentConfig(BaseModel):
    """Schema for agent configuration"""

    name: str = Field(..., description="Agent name")
    tools: List[str] = Field(default_factory=list, description="List of tool names (can be empty for general agents)")
    model: str = Field(default="gpt-4o-mini", description="LLM model name")
    temperature: float = Field(default=0, ge=0, le=2, description="LLM temperature")
    system_prompt: Optional[str] = Field(default=None, description="Custom system prompt")
    max_iterations: int = Field(default=15, ge=1, le=50, description="Max agent iterations")
    max_execution_time: Optional[float] = Field(default=None, description="Max execution time in seconds")
    memory: Optional[Union[MemoryConfig, Dict[str, Any]]] = Field(default=None, description="Memory configuration")
    enable_memory: bool = Field(default=True, description="Enable memory features when memory is configured")

    # Protection flags
    is_default: bool = Field(default=False, description="Whether this is a built-in default agent")
    protected: bool = Field(default=False, description="Whether this agent can be deleted/edited")

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        """Ensure model string is not empty"""
        if not v or not v.strip():
            raise ValueError("Model name cannot be empty")
        return v.strip()

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Research Assistant",
                "tools": ["wikipedia_search", "arxiv_search"],
                "model": "gpt-4o-mini",
                "temperature": 0,
                "system_prompt": "You are a helpful research assistant.",
                "max_iterations": 15,
                "is_default": False,
                "protected": False,
                "enable_memory": True,
                "memory": {
                    "enabled": True,
                    "short_term_max_messages": 50,
                    "long_term_enabled": True,
                    "episodic_enabled": True
                }
            }
        }


class SharedMemoryConfig(BaseModel):
    """Schema for shared memory pool configuration in workflows"""

    enabled: bool = Field(default=True, description="Enable shared memory pool")
    persist: bool = Field(default=False, description="Persist shared state across sessions")
    max_age_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Max age of pool before automatic cleanup"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "persist": False,
                "max_age_hours": 24
            }
        }


class WorkflowConfig(BaseModel):
    """Schema for workflow configuration"""

    name: str = Field(..., description="Workflow name")
    agents: List[str] = Field(..., min_length=1, description="List of agent names")
    type: Literal["chain", "conditional", "parallel"] = Field(
        default="chain",
        description="Workflow type"
    )
    routing: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Routing logic for conditional workflows"
    )
    shared_memory: Optional[Union[SharedMemoryConfig, Dict[str, Any]]] = Field(
        default=None,
        description="Shared memory pool configuration for cross-agent communication"
    )
    enable_shared_memory: bool = Field(
        default=True,
        description="Enable shared memory pool for agents in this workflow"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Research Workflow",
                "agents": ["researcher", "analyst", "writer"],
                "type": "chain",
                "enable_shared_memory": True,
                "shared_memory": {
                    "enabled": True,
                    "persist": False
                }
            }
        }


class ToolConfig(BaseModel):
    """Schema for tool configuration"""

    name: str = Field(..., description="Tool name")
    module: str = Field(..., description="Python module path")
    class_name: str = Field(..., description="Tool class name")
    allowed_roles: Optional[List[str]] = Field(
        default=None,
        description="Roles allowed to use this tool"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "wikipedia_search",
                "module": "agent_os.tools.library.wikipedia",
                "class_name": "WikipediaSearchTool",
                "allowed_roles": ["researcher", "admin"]
            }
        }


class RegistryConfig(BaseModel):
    """Schema for tool registry configuration"""

    auto_discover: bool = Field(default=True, description="Auto-discover tools")
    directories: List[str] = Field(
        default_factory=lambda: ["agent_os/tools/library"],
        description="Directories to scan for tools"
    )
    tools: List[ToolConfig] = Field(
        default_factory=list,
        description="Manual tool configurations"
    )


class ProjectConfig(BaseModel):
    """Schema for complete project configuration"""

    project_name: str = Field(..., description="Project name")
    version: str = Field(default="1.0.0", description="Project version")
    registry: RegistryConfig = Field(
        default_factory=RegistryConfig,
        description="Tool registry configuration"
    )
    agents: List[AgentConfig] = Field(
        default_factory=list,
        description="Agent configurations"
    )
    workflows: List[WorkflowConfig] = Field(
        default_factory=list,
        description="Workflow configurations"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "project_name": "MyAgentProject",
                "version": "1.0.0",
                "agents": [
                    {
                        "name": "Researcher",
                        "tools": ["wikipedia_search"],
                        "model": "gpt-4o-mini"
                    }
                ]
            }
        }
