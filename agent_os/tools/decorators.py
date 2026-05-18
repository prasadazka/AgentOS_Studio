"""Tool decorators for simplified tool creation"""

import time
from functools import wraps
from typing import Callable, Optional

from agent_os.utils.logging import get_logger

logger = get_logger("tools.decorators")


def reliable_tool(
    name: str,
    category: str,
    description: str,
    max_retries: int = 0,
    retry_delay: float = 0.5,
    error_format: str = "string"
):
    """
    Decorator to create tools with automatic error handling and retry logic

    Args:
        name: Tool name
        category: Tool category (research, data, web, etc.)
        description: What the tool does
        max_retries: Number of retry attempts (default: 0)
        retry_delay: Delay between retries in seconds (default: 0.5)
        error_format: Return format for errors - "string" or "dict"

    Returns:
        Decorated function with error handling

    Example:
        @reliable_tool(
            name="search_wikipedia",
            category="research",
            description="Search Wikipedia for information",
            max_retries=2
        )
        def search(query: str) -> str:
            # Your implementation
            return results
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            last_error = None

            while attempts <= max_retries:
                try:
                    logger.debug(f"Executing {name}, attempt {attempts + 1}/{max_retries + 1}")
                    result = func(*args, **kwargs)
                    if attempts > 0:
                        logger.info(f"Tool {name} succeeded after {attempts} retries")
                    return result

                except Exception as e:
                    last_error = e
                    attempts += 1
                    logger.warning(f"Tool {name} failed (attempt {attempts}): {e}")

                    # Sleep before retry (except on last attempt)
                    if attempts <= max_retries:
                        time.sleep(retry_delay)

            # All retries failed
            logger.error(f"Tool {name} failed after {attempts} attempts: {last_error}")

            if error_format == "string":
                return f"Error in {name}: {last_error}"
            else:
                return {
                    "error": str(last_error),
                    "tool": name,
                    "attempts": attempts
                }

        # Attach metadata for tool registry discovery
        wrapper._tool_metadata = {
            "name": name,
            "category": category,
            "description": description
        }

        return wrapper

    return decorator


def async_tool(
    name: str,
    category: str,
    description: str,
    timeout: Optional[float] = None
):
    """
    Decorator for async tools with timeout support

    Args:
        name: Tool name
        category: Tool category
        description: Tool description
        timeout: Max execution time in seconds (optional)

    Returns:
        Decorated async function

    Example:
        @async_tool(
            name="fetch_data",
            category="web",
            description="Fetch data from API",
            timeout=30.0
        )
        async def fetch(url: str) -> dict:
            # Your async implementation
            return data
    """
    import asyncio

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                if timeout:
                    result = await asyncio.wait_for(
                        func(*args, **kwargs),
                        timeout=timeout
                    )
                else:
                    result = await func(*args, **kwargs)
                return result

            except asyncio.TimeoutError:
                error_msg = f"Tool {name} timed out after {timeout} seconds"
                logger.error(error_msg)
                return f"Error: {error_msg}"

            except Exception as e:
                logger.error(f"Tool {name} failed: {e}")
                return f"Error in {name}: {e}"

        # Attach metadata
        wrapper._tool_metadata = {
            "name": name,
            "category": category,
            "description": description,
            "async": True
        }

        return wrapper

    return decorator


def cached_tool(
    name: str,
    category: str,
    description: str,
    ttl: int = 3600
):
    """
    Decorator for tools with result caching

    Args:
        name: Tool name
        category: Tool category
        description: Tool description
        ttl: Time to live for cache entries in seconds (default: 3600)

    Returns:
        Decorated function with caching

    Example:
        @cached_tool(
            name="expensive_query",
            category="data",
            description="Expensive database query",
            ttl=300
        )
        def query(sql: str) -> list:
            # Your implementation
            return results
    """
    cache = {}
    cache_times = {}

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from args and kwargs
            cache_key = str((args, tuple(sorted(kwargs.items()))))

            # Check cache
            current_time = time.time()
            if cache_key in cache:
                cached_time = cache_times[cache_key]
                if current_time - cached_time < ttl:
                    logger.debug(f"Cache hit for {name}")
                    return cache[cache_key]
                else:
                    # Expired
                    del cache[cache_key]
                    del cache_times[cache_key]

            # Execute function
            logger.debug(f"Cache miss for {name}, executing")
            result = func(*args, **kwargs)

            # Store in cache
            cache[cache_key] = result
            cache_times[cache_key] = current_time

            return result

        # Attach metadata
        wrapper._tool_metadata = {
            "name": name,
            "category": category,
            "description": description,
            "cached": True,
            "ttl": ttl
        }

        # Add cache management methods
        wrapper.clear_cache = lambda: cache.clear()
        wrapper.get_cache_size = lambda: len(cache)

        return wrapper

    return decorator
