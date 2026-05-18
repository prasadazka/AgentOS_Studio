"""Tool registry with RBAC and auto-discovery"""

import importlib
import inspect
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Type, Any, Callable
from collections import defaultdict
from dataclasses import dataclass, field

from agent_os.tools.base import BaseTool
from agent_os.utils.logging import get_logger
from agent_os.utils.errors import ToolNotFoundError

logger = get_logger("tools.registry")


@dataclass
class ToolStats:
    """Tool usage statistics for cost/latency tracking"""
    tool_name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float('inf')
    max_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    last_called: Optional[float] = None
    error_messages: List[str] = field(default_factory=list)

    def record_call(self, success: bool, latency_ms: float, error: Optional[str] = None):
        """Record a tool call"""
        self.total_calls += 1
        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1
            if error and len(self.error_messages) < 10:  # Keep last 10 errors
                self.error_messages.append(error)

        self.total_latency_ms += latency_ms
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
        self.avg_latency_ms = self.total_latency_ms / self.total_calls
        self.last_called = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Export stats as dict"""
        return {
            "tool_name": self.tool_name,
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "success_rate": self.successful_calls / self.total_calls if self.total_calls > 0 else 0.0,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "min_latency_ms": round(self.min_latency_ms, 2) if self.min_latency_ms != float('inf') else 0.0,
            "max_latency_ms": round(self.max_latency_ms, 2),
            "last_called": self.last_called,
            "recent_errors": self.error_messages[-5:]  # Last 5 errors
        }


class ToolRegistry:
    """Central registry for tool management with RBAC, lazy loading, and telemetry"""

    __slots__ = ('_tools', '_categories', '_tags', '_permissions', '_lazy_imports', '_stats', '_enable_telemetry')

    def __init__(self, enable_telemetry: bool = True):
        self._tools: Dict[str, BaseTool] = {}
        self._categories: Dict[str, Set[str]] = defaultdict(set)
        self._tags: Dict[str, Set[str]] = defaultdict(set)
        self._permissions: Dict[str, Set[str]] = {}
        self._lazy_imports: Dict[str, tuple] = {}
        self._stats: Dict[str, ToolStats] = {}
        self._enable_telemetry = enable_telemetry

    def register(
        self,
        tool: BaseTool,
        allowed_roles: Optional[List[str]] = None,
        replace: bool = False
    ) -> None:
        """Register a tool instance"""
        name = tool.metadata.name

        if name in self._tools and not replace:
            logger.warning(f"Tool '{name}' already registered, use replace=True to override")
            return

        self._tools[name] = tool
        self._categories[tool.metadata.category].add(name)

        for tag in tool.metadata.tags:
            self._tags[tag].add(name)

        if allowed_roles:
            self._permissions[name] = set(allowed_roles)

        logger.debug(f"Registered tool: {name}")

    def register_lazy(
        self,
        name: str,
        module_path: str,
        class_name: str,
        allowed_roles: Optional[List[str]] = None
    ) -> None:
        """Register a tool for lazy loading"""
        self._lazy_imports[name] = (module_path, class_name)
        if allowed_roles:
            self._permissions[name] = set(allowed_roles)
        logger.debug(f"Lazy registered: {name}")

    def _load_lazy(self, name: str) -> BaseTool:
        """Load a lazily registered tool"""
        if name not in self._lazy_imports:
            raise ToolNotFoundError(f"Tool '{name}' not found")

        module_path, class_name = self._lazy_imports[name]
        try:
            module = importlib.import_module(module_path)
            tool_class = getattr(module, class_name)
            tool = tool_class()
            self.register(tool, replace=True)
            del self._lazy_imports[name]
            return tool
        except Exception as e:
            logger.error(f"Failed to load tool '{name}': {e}")
            raise

    def unregister(self, name: str) -> bool:
        """Remove a tool"""
        if name not in self._tools:
            return False

        tool = self._tools[name]
        del self._tools[name]

        self._categories[tool.metadata.category].discard(name)
        for tag in tool.metadata.tags:
            self._tags[tag].discard(name)

        self._permissions.pop(name, None)
        self._lazy_imports.pop(name, None)

        logger.debug(f"Unregistered: {name}")
        return True

    def get(self, name: str) -> Optional[BaseTool]:
        """Get tool by name, load if lazy"""
        if name in self._tools:
            return self._tools[name]
        if name in self._lazy_imports:
            return self._load_lazy(name)
        return None

    def get_or_error(self, name: str) -> BaseTool:
        """Get tool or raise"""
        tool = self.get(name)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{name}' not found")
        return tool

    def get_by_category(self, category: str) -> List[BaseTool]:
        """Get all tools in category"""
        return [self.get_or_error(name) for name in self._categories.get(category, set())]

    def get_by_tag(self, tag: str) -> List[BaseTool]:
        """Get all tools with tag"""
        return [self.get_or_error(name) for name in self._tags.get(tag, set())]

    def get_by_role(self, role: str) -> List[BaseTool]:
        """Get tools accessible to role"""
        tools = []
        all_names = set(self._tools.keys()) | set(self._lazy_imports.keys())

        for name in all_names:
            if name not in self._permissions or role in self._permissions[name]:
                tool = self.get(name)
                if tool:
                    tools.append(tool)

        return tools

    def has_permission(self, tool_name: str, role: str) -> bool:
        """Check role permission"""
        if tool_name not in self._permissions:
            return True
        return role in self._permissions[tool_name]

    def to_langchain(
        self,
        tool_names: Optional[List[str]] = None,
        role: Optional[str] = None
    ) -> List[Any]:
        """Convert to LangChain format"""
        if tool_names is None:
            tool_names = list(set(self._tools.keys()) | set(self._lazy_imports.keys()))

        lc_tools = []
        for name in tool_names:
            if role and not self.has_permission(name, role):
                continue

            tool = self.get(name)
            if tool:
                lc_tools.append(tool.to_langchain())

        return lc_tools

    def to_mcp(self, mcp_server, tool_names: Optional[List[str]] = None) -> List[str]:
        """Register with MCP server"""
        if tool_names is None:
            tool_names = list(set(self._tools.keys()) | set(self._lazy_imports.keys()))

        registered = []
        for name in tool_names:
            tool = self.get(name)
            if tool:
                tool.to_mcp(mcp_server)
                registered.append(name)

        return registered

    def auto_discover(
        self,
        directory: str,
        package_prefix: str = "agent_os.tools.library",
        pattern: str = "*.py"
    ) -> int:
        """Auto-discover tools from directory"""
        path = Path(directory)
        if not path.exists():
            logger.error(f"Directory not found: {directory}")
            return 0

        discovered = 0
        for py_file in path.glob(pattern):
            if py_file.stem.startswith('_'):
                continue

            module_name = f"{package_prefix}.{py_file.stem}"
            try:
                module = importlib.import_module(module_name)

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BaseTool) and
                        obj is not BaseTool and
                        obj.__module__ == module_name):

                        try:
                            tool = obj()
                            self.register(tool)
                            discovered += 1
                        except Exception as e:
                            logger.error(f"Failed to instantiate {name}: {e}")

            except ImportError as e:
                logger.warning(f"Could not import {module_name}: {e}")

        logger.info(f"Discovered {discovered} tools from {directory}")
        return discovered

    def list_all(self) -> List[str]:
        """List all tool names"""
        return sorted(set(self._tools.keys()) | set(self._lazy_imports.keys()))

    def list_categories(self) -> List[str]:
        """List all categories"""
        return sorted(self._categories.keys())

    def list_tags(self) -> List[str]:
        """List all tags"""
        return sorted(self._tags.keys())

    def execute_with_telemetry(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        Execute tool with automatic telemetry tracking

        Args:
            tool_name: Name of tool to execute
            **kwargs: Tool parameters

        Returns:
            Tool execution result dict
        """
        tool = self.get_or_error(tool_name)

        # Initialize stats if not exists
        if tool_name not in self._stats:
            self._stats[tool_name] = ToolStats(tool_name=tool_name)

        start_time = time.time()
        result = tool.execute(**kwargs)
        latency_ms = (time.time() - start_time) * 1000

        # Record telemetry
        if self._enable_telemetry:
            self._stats[tool_name].record_call(
                success=result.get("success", False),
                latency_ms=latency_ms,
                error=result.get("error")
            )

        return result

    async def aexecute_with_telemetry(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        Execute tool async with automatic telemetry tracking

        Args:
            tool_name: Name of tool to execute
            **kwargs: Tool parameters

        Returns:
            Tool execution result dict
        """
        tool = self.get_or_error(tool_name)

        # Initialize stats if not exists
        if tool_name not in self._stats:
            self._stats[tool_name] = ToolStats(tool_name=tool_name)

        start_time = time.time()
        result = await tool.aexecute(**kwargs)
        latency_ms = (time.time() - start_time) * 1000

        # Record telemetry
        if self._enable_telemetry:
            self._stats[tool_name].record_call(
                success=result.get("success", False),
                latency_ms=latency_ms,
                error=result.get("error")
            )

        return result

    def get_stats(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get telemetry stats for a tool"""
        if tool_name in self._stats:
            return self._stats[tool_name].to_dict()
        return None

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get telemetry stats for all tools"""
        return {name: stats.to_dict() for name, stats in self._stats.items()}

    def get_slowest_tools(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get slowest tools by average latency"""
        all_stats = [(name, stats) for name, stats in self._stats.items() if stats.total_calls > 0]
        all_stats.sort(key=lambda x: x[1].avg_latency_ms, reverse=True)
        return [stats.to_dict() for _, stats in all_stats[:limit]]

    def get_most_used_tools(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most frequently called tools"""
        all_stats = [(name, stats) for name, stats in self._stats.items()]
        all_stats.sort(key=lambda x: x[1].total_calls, reverse=True)
        return [stats.to_dict() for _, stats in all_stats[:limit]]

    def search(
        self,
        query: str,
        search_in: List[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        requires_auth: Optional[bool] = None,
        supports_async: Optional[bool] = None
    ) -> List[BaseTool]:
        """
        Advanced tool search with multiple filters

        Args:
            query: Search string (searches name and description)
            search_in: Fields to search in ['name', 'description', 'category', 'tags']
            category: Filter by category
            tags: Filter by tags (any match)
            requires_auth: Filter by auth requirement
            supports_async: Filter by async support

        Returns:
            List of matching tools
        """
        if search_in is None:
            search_in = ['name', 'description']

        query_lower = query.lower()
        results = []

        for name in self.list_all():
            tool = self.get(name)
            if not tool:
                continue

            # Apply filters
            if category and tool.metadata.category != category:
                continue

            if tags and not any(tag in tool.metadata.tags for tag in tags):
                continue

            if requires_auth is not None and tool.metadata.requires_auth != requires_auth:
                continue

            if supports_async is not None and tool.metadata.supports_async != supports_async:
                continue

            # Text search
            matches = False
            if 'name' in search_in and query_lower in tool.metadata.name.lower():
                matches = True
            if 'description' in search_in and query_lower in tool.metadata.description.lower():
                matches = True
            if 'category' in search_in and query_lower in tool.metadata.category.lower():
                matches = True
            if 'tags' in search_in and any(query_lower in tag.lower() for tag in tool.metadata.tags):
                matches = True

            if matches:
                results.append(tool)

        return results

    def find_similar(self, tool_name: str, limit: int = 5) -> List[BaseTool]:
        """
        Find tools similar to the given tool (by category and tags)

        Args:
            tool_name: Reference tool name
            limit: Maximum number of similar tools to return

        Returns:
            List of similar tools
        """
        tool = self.get_or_error(tool_name)

        candidates = []
        for name in self.list_all():
            if name == tool_name:
                continue

            other = self.get(name)
            if not other:
                continue

            # Calculate similarity score
            score = 0
            if other.metadata.category == tool.metadata.category:
                score += 3

            common_tags = set(other.metadata.tags) & set(tool.metadata.tags)
            score += len(common_tags)

            if score > 0:
                candidates.append((score, other))

        # Sort by score and return top N
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [tool for _, tool in candidates[:limit]]

    def export_metadata(self, include_stats: bool = False) -> Dict[str, Any]:
        """
        Export registry metadata

        Args:
            include_stats: Include telemetry statistics

        Returns:
            Dict with registry metadata
        """
        all_tools = []
        for name in self.list_all():
            tool = self.get(name)
            if tool:
                tool_data = {
                    "name": tool.metadata.name,
                    "description": tool.metadata.description,
                    "category": tool.metadata.category,
                    "version": tool.metadata.version,
                    "tags": tool.metadata.tags,
                    "requires_auth": tool.metadata.requires_auth,
                    "supports_async": tool.metadata.supports_async,
                    "permissions": list(self._permissions.get(name, []))
                }

                if include_stats and name in self._stats:
                    tool_data["stats"] = self._stats[name].to_dict()

                all_tools.append(tool_data)

        return {
            "total": len(all_tools),
            "categories": {k: len(v) for k, v in self._categories.items()},
            "telemetry_enabled": self._enable_telemetry,
            "tools": all_tools
        }

    def clear(self, clear_stats: bool = False) -> None:
        """
        Clear all registered tools and break circular references

        Args:
            clear_stats: Also clear telemetry statistics
        """
        # Break circular references to prevent memory leaks
        for tool in self._tools.values():
            if hasattr(tool, 'metadata'):
                tool.metadata = None

        self._tools.clear()
        self._categories.clear()
        self._tags.clear()
        self._permissions.clear()
        self._lazy_imports.clear()

        if clear_stats:
            self._stats.clear()

    def __len__(self) -> int:
        return len(self._tools) + len(self._lazy_imports)

    def __contains__(self, name: str) -> bool:
        return name in self._tools or name in self._lazy_imports

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={len(self)}, categories={len(self._categories)})"
