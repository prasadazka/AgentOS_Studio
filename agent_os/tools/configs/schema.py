"""
Config-Driven Tool Schema

Industry-standard approach: Define tools in YAML, execute with generic runner.
- LLM picks tools from catalog
- Config defines the command template
- Executor validates params and runs command
"""

from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, Field
from enum import Enum


class ParamType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    FLOAT = "float"
    LIST = "list"
    ENUM = "enum"


class ToolParameter(BaseModel):
    """Definition of a tool parameter"""
    name: str
    type: ParamType = ParamType.STRING
    required: bool = False
    default: Optional[Any] = None
    description: str = ""
    enum_values: Optional[List[str]] = None  # For enum type
    min_value: Optional[float] = None  # For numeric types
    max_value: Optional[float] = None
    pattern: Optional[str] = None  # Regex pattern for validation


class CommandTemplate(BaseModel):
    """Command template with placeholders"""
    base: str  # e.g., "gcloud sql instances create"
    args: List[str] = []  # Fixed args
    flags: Dict[str, str] = {}  # Flag mappings: param_name -> flag_name
    optional_flags: Dict[str, str] = {}  # Only added if param provided
    positional: List[str] = []  # Params that go as positional args


class ToolConfig(BaseModel):
    """Complete tool configuration"""
    name: str
    description: str
    category: str = "gcp"
    version: str = "1.0.0"

    # Command definition
    command: CommandTemplate

    # Parameters
    parameters: List[ToolParameter] = []

    # Execution settings
    timeout_seconds: int = 120
    requires_project: bool = True
    requires_region: bool = False

    # Output parsing
    output_format: Literal["json", "text", "yaml"] = "json"
    success_patterns: List[str] = []  # Patterns that indicate success
    error_patterns: List[str] = []  # Patterns that indicate failure

    # Documentation
    examples: List[Dict[str, Any]] = []
    related_tools: List[str] = []

    # Pricing (optional, for cost estimation)
    pricing_url: Optional[str] = None
    estimated_cost: Optional[str] = None


class ToolConfigRegistry(BaseModel):
    """Registry of all config-driven tools"""
    tools: Dict[str, ToolConfig] = {}
    categories: Dict[str, List[str]] = {}  # category -> tool names

    def register(self, config: ToolConfig):
        """Register a tool config"""
        self.tools[config.name] = config
        if config.category not in self.categories:
            self.categories[config.category] = []
        if config.name not in self.categories[config.category]:
            self.categories[config.category].append(config.name)

    def get(self, name: str) -> Optional[ToolConfig]:
        """Get tool config by name"""
        return self.tools.get(name)

    def list_by_category(self, category: str) -> List[ToolConfig]:
        """List tools in category"""
        return [self.tools[name] for name in self.categories.get(category, [])]

    def search(self, query: str) -> List[ToolConfig]:
        """Search tools by name or description"""
        query = query.lower()
        return [
            config for config in self.tools.values()
            if query in config.name.lower() or query in config.description.lower()
        ]
