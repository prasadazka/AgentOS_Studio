"""Base tool abstraction for Agent_OS"""

import asyncio
import inspect
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Callable
from pydantic import BaseModel, Field

from agent_os.utils.logging import get_logger
from agent_os.utils.errors import ToolExecutionError

logger = get_logger("tools.base")


class ToolMetadata(BaseModel):
    """Metadata for a tool"""
    name: str = Field(..., description="Tool name (unique identifier)")
    description: str = Field(..., description="What the tool does")
    category: str = Field(..., description="Tool category (e.g., research, data, web)")
    version: str = Field(default="1.0.0", description="Tool version")
    requires_auth: bool = Field(default=False, description="Whether tool requires authentication")
    tags: list[str] = Field(default_factory=list, description="Additional tags for discovery")
    supports_async: bool = Field(default=False, description="Whether tool supports async execution")


class BaseTool(ABC):
    """
    Base class for all tools in Agent_OS

    Provides:
    - Automatic error handling
    - Type validation using Pydantic
    - Standardized return format
    - Support for both sync and async execution (Phase 4)
    - Support for LangChain and MCP tool formats

    Execution Modes:
    - Sync-only: Implement only _execute()
    - Async-only: Implement only _aexecute()
    - Dual-mode: Implement both _execute() and _aexecute()

    Example (Sync-only):
        class MyTool(BaseTool):
            def __init__(self):
                metadata = ToolMetadata(
                    name="my_tool",
                    description="Does something useful",
                    category="utilities"
                )
                super().__init__(metadata)

            def _execute(self, param: str) -> str:
                return f"Processed: {param}"

    Example (Async-capable):
        class MyAsyncTool(BaseTool):
            def __init__(self):
                metadata = ToolMetadata(
                    name="my_async_tool",
                    description="Does something async",
                    category="utilities",
                    supports_async=True
                )
                super().__init__(metadata)

            def _execute(self, param: str) -> str:
                return f"Sync: {param}"

            async def _aexecute(self, param: str) -> str:
                await asyncio.sleep(0.1)
                return f"Async: {param}"
    """

    def __init__(self, metadata: ToolMetadata):
        self.metadata = metadata
        self._validate_config()

        # Auto-detect async support if not explicitly set
        if not self.metadata.supports_async:
            self.metadata.supports_async = self._has_async_implementation()

        logger.debug(f"Initialized tool: {metadata.name} v{metadata.version} (async: {self.metadata.supports_async})")

    def _has_async_implementation(self) -> bool:
        """Check if tool has async implementation"""
        try:
            method = getattr(self, '_aexecute', None)
            if method is None:
                return False
            return inspect.iscoroutinefunction(method)
        except Exception:
            return False

    @abstractmethod
    def _execute(self, **kwargs) -> Any:
        """
        Core tool logic - to be implemented by subclasses (sync version)

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            Tool execution result (any type)

        Note:
            If only _aexecute is implemented, this will be auto-generated
            to call _aexecute in a sync wrapper
        """
        pass

    async def _aexecute(self, **kwargs) -> Any:
        """
        Core tool logic - async version (optional)

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            Tool execution result (any type)

        Note:
            Default implementation calls _execute in an async wrapper.
            Override this method for true async execution.
        """
        # Default: run sync version in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self._execute(**kwargs))

    def _validate_config(self):
        """
        Validate tool configuration
        Override in subclasses for custom validation
        """
        pass

    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute tool with error handling and standardized return format (sync)

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            Dict with keys:
                - success: bool
                - result: Any (if success=True)
                - error: str (if success=False)
                - tool: str (tool name)
        """
        try:
            logger.debug(f"Executing tool: {self.metadata.name} with params: {kwargs}")
            result = self._execute(**kwargs)
            logger.debug(f"Tool {self.metadata.name} succeeded")
            return {
                "success": True,
                "result": result,
                "tool": self.metadata.name
            }
        except Exception as e:
            logger.error(f"Tool {self.metadata.name} failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "tool": self.metadata.name
            }

    async def aexecute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute tool with error handling and standardized return format (async)

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            Dict with keys:
                - success: bool
                - result: Any (if success=True)
                - error: str (if success=False)
                - tool: str (tool name)
        """
        try:
            logger.debug(f"Async executing tool: {self.metadata.name} with params: {kwargs}")
            result = await self._aexecute(**kwargs)
            logger.debug(f"Tool {self.metadata.name} async succeeded")
            return {
                "success": True,
                "result": result,
                "tool": self.metadata.name
            }
        except Exception as e:
            logger.error(f"Tool {self.metadata.name} async failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "tool": self.metadata.name
            }

    def to_langchain(self):
        """
        Convert to LangChain tool format (sync version)

        Returns:
            LangChain Tool instance
        """
        from langchain_core.tools import tool as langchain_tool_decorator
        from typing import get_type_hints

        # Get the signature of _execute method
        sig = inspect.signature(self._execute)
        type_hints = get_type_hints(self._execute)

        # Build the wrapper function signature dynamically
        params_no_default = []
        params_with_default = []
        param_annotations = {}

        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue

            # Get type hint
            param_type = type_hints.get(param_name, str)
            param_annotations[param_name] = param_type

            # Create parameter with default if exists
            if param.default != inspect.Parameter.empty:
                params_with_default.append(inspect.Parameter(
                    param_name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=param.default,
                    annotation=param_type
                ))
            else:
                params_no_default.append(inspect.Parameter(
                    param_name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=param_type
                ))

        # Ensure non-default params come before default params (Python requirement)
        params = params_no_default + params_with_default

        # Create wrapper function with dynamic signature
        def tool_fn(*args, **kwargs) -> str:
            """Wrapper for LangChain compatibility"""
            import json

            # Handle ReAct agent passing JSON string as single positional arg
            if len(args) == 1 and isinstance(args[0], str) and not kwargs:
                arg_str = args[0].strip()
                # Check if it looks like JSON
                if arg_str.startswith('{') and arg_str.endswith('}'):
                    try:
                        # Parse JSON string into kwargs
                        kwargs = json.loads(arg_str)
                        args = ()  # Clear args since we've extracted them
                    except json.JSONDecodeError:
                        # Not valid JSON, proceed with normal arg handling
                        pass

            # Convert remaining positional args to kwargs based on parameter order
            if args:
                param_names = [p.name for p in params]
                for i, arg in enumerate(args):
                    if i < len(param_names):
                        kwargs[param_names[i]] = arg

            result = self.execute(**kwargs)

            if result["success"]:
                return str(result["result"])
            else:
                raise ToolExecutionError(f"Tool {self.metadata.name} failed: {result['error']}")

        # Set annotations
        tool_fn.__annotations__ = param_annotations
        tool_fn.__annotations__['return'] = str

        # Set signature
        tool_fn.__signature__ = inspect.Signature(params)

        # Apply LangChain decorator
        lc_tool = langchain_tool_decorator(tool_fn)
        lc_tool.name = self.metadata.name
        lc_tool.description = self.metadata.description

        return lc_tool

    def to_langchain_async(self):
        """
        Convert to LangChain tool format (async version)

        Returns:
            LangChain Tool instance with async support
        """
        from langchain_core.tools import tool as langchain_tool_decorator
        from typing import get_type_hints

        # Get the signature of _aexecute method
        sig = inspect.signature(self._aexecute)
        type_hints = get_type_hints(self._aexecute)

        # Build the wrapper function signature dynamically
        params_no_default = []
        params_with_default = []
        param_annotations = {}

        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue

            # Get type hint
            param_type = type_hints.get(param_name, str)
            param_annotations[param_name] = param_type

            # Create parameter with default if exists
            if param.default != inspect.Parameter.empty:
                params_with_default.append(inspect.Parameter(
                    param_name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=param.default,
                    annotation=param_type
                ))
            else:
                params_no_default.append(inspect.Parameter(
                    param_name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=param_type
                ))

        # Ensure non-default params come before default params (Python requirement)
        params = params_no_default + params_with_default

        # Create async wrapper function with dynamic signature
        async def tool_fn(*args, **kwargs) -> str:
            """Async wrapper for LangChain compatibility"""
            import json

            # Handle ReAct agent passing JSON string as single positional arg
            if len(args) == 1 and isinstance(args[0], str) and not kwargs:
                arg_str = args[0].strip()
                # Check if it looks like JSON
                if arg_str.startswith('{') and arg_str.endswith('}'):
                    try:
                        # Parse JSON string into kwargs
                        kwargs = json.loads(arg_str)
                        args = ()  # Clear args since we've extracted them
                    except json.JSONDecodeError:
                        # Not valid JSON, proceed with normal arg handling
                        pass

            # Convert remaining positional args to kwargs based on parameter order
            if args:
                param_names = [p.name for p in params]
                for i, arg in enumerate(args):
                    if i < len(param_names):
                        kwargs[param_names[i]] = arg

            result = await self.aexecute(**kwargs)
            if result["success"]:
                return str(result["result"])
            else:
                raise ToolExecutionError(f"Tool {self.metadata.name} failed: {result['error']}")

        # Set annotations
        tool_fn.__annotations__ = param_annotations
        tool_fn.__annotations__['return'] = str

        # Set signature
        tool_fn.__signature__ = inspect.Signature(params)

        # Apply LangChain decorator
        lc_tool = langchain_tool_decorator(tool_fn)
        lc_tool.name = self.metadata.name
        lc_tool.description = self.metadata.description

        return lc_tool

    def to_mcp(self, mcp_server):
        """
        Register as MCP tool (sync version)

        Args:
            mcp_server: MCP server instance to register with

        Returns:
            Decorated function registered with MCP server
        """
        @mcp_server.tool()
        def tool_fn(**kwargs) -> str:
            """MCP tool wrapper"""
            result = self.execute(**kwargs)
            if result["success"]:
                return str(result["result"])
            else:
                return f"Error in {self.metadata.name}: {result['error']}"

        # Set proper function metadata
        tool_fn.__name__ = self.metadata.name
        tool_fn.__doc__ = self.metadata.description

        return tool_fn

    def to_mcp_async(self, mcp_server):
        """
        Register as MCP tool (async version)

        Args:
            mcp_server: MCP server instance to register with

        Returns:
            Decorated async function registered with MCP server
        """
        @mcp_server.tool()
        async def tool_fn(**kwargs) -> str:
            """MCP async tool wrapper"""
            result = await self.aexecute(**kwargs)
            if result["success"]:
                return str(result["result"])
            else:
                return f"Error in {self.metadata.name}: {result['error']}"

        # Set proper function metadata
        tool_fn.__name__ = self.metadata.name
        tool_fn.__doc__ = self.metadata.description

        return tool_fn

    def to_openai_schema(self) -> Dict[str, Any]:
        """
        Export tool schema in OpenAI Function Calling format

        Returns:
            Dict compatible with OpenAI's function calling API
        """
        from agent_os.tools.schemas import SchemaBuilder
        return SchemaBuilder.to_openai_schema(self)

    def to_anthropic_schema(self) -> Dict[str, Any]:
        """
        Export tool schema in Anthropic Claude Tool Use format

        Returns:
            Dict compatible with Anthropic's tool use API
        """
        from agent_os.tools.schemas import SchemaBuilder
        return SchemaBuilder.to_anthropic_schema(self)

    def to_mcp_schema(self) -> Dict[str, Any]:
        """
        Export tool schema in MCP (Model Context Protocol) format

        Returns:
            Dict compatible with MCP tool registration
        """
        from agent_os.tools.schemas import SchemaBuilder
        return SchemaBuilder.to_mcp_schema(self)

    def to_json_schema(self) -> Dict[str, Any]:
        """
        Export tool schema as pure JSON Schema

        Returns:
            JSON Schema document
        """
        from agent_os.tools.schemas import SchemaBuilder
        return SchemaBuilder.to_json_schema(self)

    def export_schema(self, format: str = "openai") -> Dict[str, Any]:
        """
        Export tool schema in specified format

        Args:
            format: Schema format - 'openai', 'anthropic', 'mcp', 'json_schema'

        Returns:
            Schema dict in requested format
        """
        from agent_os.tools.schemas import export_tool_schema
        return export_tool_schema(self, format)

    def __repr__(self) -> str:
        async_str = "+async" if self.metadata.supports_async else ""
        return f"<{self.__class__.__name__}(name='{self.metadata.name}', category='{self.metadata.category}'{async_str})>"

    def __str__(self) -> str:
        async_str = " [async]" if self.metadata.supports_async else ""
        return f"{self.metadata.name} ({self.metadata.category}): {self.metadata.description}{async_str}"
