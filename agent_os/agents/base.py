"""Base agent with minimal configuration"""

import os
import time
from typing import List, Optional, Dict, Any, Union, TYPE_CHECKING
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    ChatGoogleGenerativeAI = None

load_dotenv()
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage

from agent_os.tools.base import BaseTool
from agent_os.tools.registry import ToolRegistry
from agent_os.utils.logging import get_logger
from agent_os.utils.errors import AgentConfigError
from agent_os.utils.circuit_breaker import get_circuit_breaker_manager, CircuitBreakerError
from agent_os.utils.cost_tracker import get_cost_tracker_manager, Budget, BudgetExceededError
from agent_os.utils.token_counter import extract_token_usage_from_response, estimate_tokens
from agent_os.utils.rate_limiter import get_rate_limiter_manager, RateLimitConfig, RateLimitExceeded
from agent_os.utils.retry import RetryHandler, RetryConfig, MaxRetriesExceeded
from agent_os.utils.timeout import execute_with_timeout, TimeoutError
from agent_os.utils.metrics import get_metrics_manager

# Memory imports (optional - graceful fallback)
if TYPE_CHECKING:
    from agent_os.memory import MemoryManager, SharedMemoryPool

logger = get_logger("agents.base")


class BaseAgent:
    """
    Lightweight agent with automatic tool binding and execution

    Example:
        registry = ToolRegistry()
        registry.register(WikipediaSearchTool())

        agent = BaseAgent(
            name="Research Assistant",
            tools=["wikipedia_search"],
            model="gpt-4o-mini",
            tool_registry=registry
        )

        result = agent.run("Tell me about quantum computing")
    """

    __slots__ = (
        'name', 'llm', 'tools', 'system_prompt', 'registry',
        'agent', 'model_name', 'temperature', 'max_iterations', 'max_execution_time',
        'circuit_breaker', 'enable_circuit_breaker',
        'cost_tracker', 'enable_cost_tracking',
        'rate_limiter', 'enable_rate_limiting',
        'retry_handler', 'enable_retry',
        'metrics_collector', 'enable_metrics',
        'memory', 'enable_memory', 'shared_pool',  # Memory system
        '_cleanup_done'  # Track cleanup state to prevent memory leaks
    )

    def __init__(
        self,
        name: str,
        tools: List[Union[str, BaseTool]],
        model: str = "gpt-4o-mini",
        temperature: float = 0,
        system_prompt: Optional[str] = None,
        tool_registry: Optional[ToolRegistry] = None,
        max_iterations: int = 15,
        max_execution_time: Optional[float] = None,
        enable_circuit_breaker: bool = True,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: float = 60.0,
        enable_cost_tracking: bool = True,
        budget: Optional[Budget] = None,
        enable_rate_limiting: bool = True,
        rate_limit_config: Optional[RateLimitConfig] = None,
        enable_retry: bool = True,
        retry_config: Optional[RetryConfig] = None,
        enable_metrics: bool = True,
        memory: Optional["MemoryManager"] = None,
        enable_memory: bool = True,
        shared_pool: Optional["SharedMemoryPool"] = None,
        **llm_kwargs
    ):
        """
        Initialize agent

        Args:
            name: Agent name
            tools: List of tool names (str) or tool instances (BaseTool)
            model: Model name (default: gpt-4o-mini)
            temperature: LLM temperature (default: 0)
            system_prompt: Custom system prompt (optional)
            tool_registry: Tool registry instance (creates new if None)
            max_iterations: Max agent iterations (default: 15)
            max_execution_time: Max execution time in seconds (optional)
            enable_circuit_breaker: Enable circuit breaker protection (default: True)
            circuit_breaker_threshold: Failures before circuit opens (default: 5)
            circuit_breaker_timeout: Timeout before retry attempt in seconds (default: 60)
            enable_cost_tracking: Enable cost tracking (default: True)
            budget: Budget configuration (optional)
            enable_rate_limiting: Enable rate limiting (default: True)
            rate_limit_config: Rate limit configuration (optional)
            enable_retry: Enable retry with exponential backoff (default: True)
            retry_config: Retry configuration (optional)
            enable_metrics: Enable performance metrics collection (default: True)
            memory: MemoryManager instance for conversation/semantic memory (optional)
            enable_memory: Enable memory features when memory is provided (default: True)
            shared_pool: SharedMemoryPool for cross-agent communication (optional)
            **llm_kwargs: Additional LLM parameters
        """
        self.name = name
        self.model_name = model
        self.temperature = temperature
        self.max_execution_time = max_execution_time
        self.registry = tool_registry or ToolRegistry()
        self.enable_circuit_breaker = enable_circuit_breaker

        # Setup circuit breaker
        if enable_circuit_breaker:
            cb_manager = get_circuit_breaker_manager()
            self.circuit_breaker = cb_manager.get_or_create(
                name=f"{name}_{model}",
                failure_threshold=circuit_breaker_threshold,
                timeout_duration=circuit_breaker_timeout,
                success_threshold=2,
                expected_exception=Exception
            )
            logger.info(f"Circuit breaker enabled for agent '{name}' (threshold={circuit_breaker_threshold}, timeout={circuit_breaker_timeout}s)")
        else:
            self.circuit_breaker = None
            logger.info(f"Circuit breaker disabled for agent '{name}'")

        # Setup cost tracking
        self.enable_cost_tracking = enable_cost_tracking
        if enable_cost_tracking:
            ct_manager = get_cost_tracker_manager()
            self.cost_tracker = ct_manager.get_or_create(
                agent_name=name,
                model=model,
                budget=budget
            )
            if budget:
                logger.info(f"Cost tracking enabled for agent '{name}' with budget: ${budget.limit} per {budget.window}")
            else:
                logger.info(f"Cost tracking enabled for agent '{name}' (no budget limit)")
        else:
            self.cost_tracker = None
            logger.info(f"Cost tracking disabled for agent '{name}'")

        # Setup rate limiting
        self.enable_rate_limiting = enable_rate_limiting
        if enable_rate_limiting:
            rl_manager = get_rate_limiter_manager()
            self.rate_limiter = rl_manager.get_or_create(
                model=model,
                config=rate_limit_config,
                enable_throttling=True
            )
            config = self.rate_limiter.config
            logger.info(
                f"Rate limiting enabled for agent '{name}': "
                f"TPM={config.tokens_per_minute:,}, RPM={config.requests_per_minute:,}"
            )
        else:
            self.rate_limiter = None
            logger.info(f"Rate limiting disabled for agent '{name}'")

        # Setup retry with exponential backoff
        self.enable_retry = enable_retry
        if enable_retry:
            if retry_config is None:
                retry_config = RetryConfig()  # Use defaults
            self.retry_handler = RetryHandler(config=retry_config)
            logger.info(
                f"Retry enabled for agent '{name}': "
                f"max_retries={retry_config.max_retries}, base_delay={retry_config.base_delay}s"
            )
        else:
            self.retry_handler = None
            logger.info(f"Retry disabled for agent '{name}'")

        # Setup performance metrics collection
        self.enable_metrics = enable_metrics
        if enable_metrics:
            metrics_manager = get_metrics_manager()
            self.metrics_collector = metrics_manager.get_or_create(
                name=f"{name}_{model}"
            )
            logger.info(f"Performance metrics enabled for agent '{name}'")
        else:
            self.metrics_collector = None
            logger.info(f"Performance metrics disabled for agent '{name}'")

        # Setup memory system
        self.memory = memory
        self.enable_memory = enable_memory and memory is not None
        self.shared_pool = shared_pool
        if self.enable_memory and self.memory:
            logger.info(f"Memory enabled for agent '{name}'")
        if self.shared_pool:
            logger.info(f"Shared memory pool attached to agent '{name}'")

        self.llm = self._create_llm(model, temperature, **llm_kwargs)

        # Process tools: handle both string names and tool instances
        self.tools = self._process_tools(tools)

        # Set default prompt based on whether agent has tools
        if system_prompt:
            self.system_prompt = system_prompt
        elif self.tools:
            self.system_prompt = (
                f"You are {name}, an AI assistant. "
                "Use the available tools to help answer questions accurately. "
                "Always cite sources when using external information."
            )
        else:
            self.system_prompt = (
                f"You are {name}, an AI assistant. "
                "Provide clear, accurate, and helpful responses."
            )

        # Resolve {{tool:name}} placeholders in system prompt
        self.system_prompt = self._resolve_tool_variables(self.system_prompt)

        # Allow agents without tools (reasoning-only agents in workflows)
        if not self.tools:
            logger.info(f"Initialized reasoning-only agent: {name} (no tools)")
        else:
            logger.info(f"Initialized agent: {name} with {len(self.tools)} tools")

        self._setup_agent(max_iterations, max_execution_time)

        # Initialize cleanup state tracker (memory leak prevention)
        self._cleanup_done = False

    def _process_tools(self, tools: List[Union[str, BaseTool]]) -> List:
        """
        Process tools - handle both string names and tool instances

        Args:
            tools: List of tool names (str) or tool instances (BaseTool)

        Returns:
            List of LangChain tool instances
        """
        langchain_tools = []

        for tool in tools:
            if isinstance(tool, str):
                # String name - lookup from registry
                tool_obj = self.registry.get(tool)
                if tool_obj is None:
                    raise AgentConfigError(
                        f"Tool '{tool}' not found in registry. "
                        f"Available: {self.registry.list_all()}"
                    )
                langchain_tools.append(tool_obj.to_langchain())
            elif isinstance(tool, BaseTool):
                # Tool instance - use directly
                langchain_tools.append(tool.to_langchain())
            else:
                raise AgentConfigError(
                    f"Invalid tool type: {type(tool)}. "
                    f"Expected str or BaseTool instance."
                )

        return langchain_tools

    def _create_llm(self, model: str, temperature: float, **kwargs) -> BaseChatModel:
        """Create LLM based on model string"""
        model_lower = model.lower()

        if "gpt" in model_lower or "o1" in model_lower or "o3" in model_lower:
            return ChatOpenAI(model=model, temperature=temperature, **kwargs)
        elif "claude" in model_lower:
            return ChatAnthropic(model=model, temperature=temperature, **kwargs)
        elif "gemini" in model_lower:
            if ChatGoogleGenerativeAI is None:
                raise AgentConfigError(
                    "Gemini model requested but langchain-google-genai is not installed. "
                    "Run: pip install langchain-google-genai"
                )
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            return ChatGoogleGenerativeAI(
                model=model, temperature=temperature,
                google_api_key=api_key, **kwargs
            )
        else:
            logger.warning(f"Unknown model '{model}', defaulting to ChatOpenAI")
            return ChatOpenAI(model=model, temperature=temperature, **kwargs)

    def _setup_agent(self, max_iterations: int, max_execution_time: Optional[float]):
        """Setup ReAct agent using LangGraph"""
        self.max_iterations = max_iterations
        self.max_execution_time = max_execution_time

        # Create agent without state_modifier (not supported in this version)
        self.agent = create_react_agent(
            model=self.llm,
            tools=self.tools
        )

    def _record_metrics(self, start_time: float, success: bool, token_usage=None, error_type: Optional[str] = None):
        """Record performance metrics for request"""
        if not (self.enable_metrics and self.metrics_collector):
            return

        latency_ms = (time.time() - start_time) * 1000
        tokens_used = token_usage.total_tokens if token_usage else 0
        cost = token_usage.calculate_cost() if token_usage else 0.0

        self.metrics_collector.record_request(
            latency_ms=latency_ms,
            success=success,
            error_type=error_type,
            tokens_used=tokens_used,
            cost=cost
        )

    def run(self, query: str, **kwargs) -> str:
        """
        Execute agent synchronously with graceful degradation

        Reliability layers (in order):
        1. Retry with exponential backoff
        2. Circuit breaker
        3. Direct execution (fallback)

        If any reliability layer fails, gracefully degrade to next layer.

        Args:
            query: User query
            **kwargs: Additional execution parameters

        Returns:
            Agent response
        """
        # Try retry layer first (if enabled)
        if self.enable_retry and self.retry_handler:
            try:
                return self.retry_handler.execute(
                    self._run_with_circuit_breaker,
                    query,
                    **kwargs
                )
            except (MaxRetriesExceeded, BudgetExceededError, TimeoutError) as e:
                # Expected errors - do not retry, propagate immediately
                logger.error(f"Agent '{self.name}' error (no retry): {e}")
                raise
            except Exception as e:
                # Unexpected error in retry system - gracefully degrade
                logger.error(
                    f"Retry system failed for agent '{self.name}': {e}. "
                    f"Falling back to circuit breaker execution."
                )
                # Fall through to circuit breaker

        # Try circuit breaker layer (if enabled)
        try:
            return self._run_with_circuit_breaker(query, **kwargs)
        except Exception as e:
            # Unexpected error in circuit breaker - gracefully degrade
            if self.enable_circuit_breaker and self.circuit_breaker:
                logger.error(
                    f"Circuit breaker failed for agent '{self.name}': {e}. "
                    f"Falling back to direct execution."
                )
            # Fall through to direct execution

        # Last resort: direct execution without any protection
        logger.warning(
            f"All reliability layers bypassed for agent '{self.name}'. "
            f"Executing directly."
        )
        return self._execute_agent(query, **kwargs)

    def _run_with_circuit_breaker(self, query: str, **kwargs) -> str:
        """
        Execute with circuit breaker protection

        Raises:
            CircuitBreakerError: When circuit is OPEN (expected behavior)
            Exception: Other exceptions from agent execution
        """
        if self.enable_circuit_breaker and self.circuit_breaker:
            try:
                return self.circuit_breaker.call(self._execute_agent, query, **kwargs)
            except CircuitBreakerError as e:
                # Circuit is OPEN - this is expected behavior
                logger.error(f"Circuit breaker OPEN for agent '{self.name}': {e}")
                raise  # Re-raise for retry to handle
            except Exception as e:
                # Unexpected error from circuit breaker itself
                logger.exception(
                    f"Circuit breaker internal error for agent '{self.name}': {e}"
                )
                raise  # Re-raise - will be caught by graceful degradation in run()
        else:
            return self._execute_agent(query, **kwargs)

    def _execute_agent(self, query: str, **kwargs) -> str:
        """
        Internal execution logic without circuit breaker

        Args:
            query: User query
            **kwargs: Additional execution parameters

        Returns:
            Agent response
        """
        start_time = time.time()

        try:
            logger.debug(f"Agent '{self.name}' executing: {query[:50]}...")

            # Rate limiting check (throttle if needed)
            if self.enable_rate_limiting and self.rate_limiter:
                # Estimate tokens for query
                estimated_tokens = estimate_tokens(query)
                if self.system_prompt:
                    estimated_tokens += estimate_tokens(self.system_prompt)

                # Wait if rate limited
                try:
                    self.rate_limiter.wait_if_needed(tokens=estimated_tokens)
                except RateLimitExceeded as e:
                    logger.error(f"Rate limit exceeded for agent '{self.name}': {e}")
                    raise

            # Build context from memory if enabled
            memory_context = ""
            if self.enable_memory and self.memory:
                try:
                    # Get recent conversation context
                    context_str = self.memory.get_context_string(limit=5)
                    if context_str:
                        memory_context = f"\n\n[Recent conversation context:\n{context_str}]\n"

                    # Search for semantically relevant past content
                    semantic_matches = self.memory.search_semantic(query, limit=3, threshold=0.5)
                    if semantic_matches:
                        relevant = "\n".join([f"- {m.content[:200]}..." for m in semantic_matches[:3]])
                        memory_context += f"\n[Relevant past context:\n{relevant}]\n"
                except Exception as e:
                    logger.warning(f"Memory context retrieval failed: {e}")

            # Build context from shared pool if available
            shared_context = ""
            if self.shared_pool:
                try:
                    pool_context = self.shared_pool.get_context_for_agent(self.name)
                    if pool_context.get("other_agent_outputs"):
                        outputs = pool_context["other_agent_outputs"]
                        shared_context = f"\n\n[Outputs from other agents:\n"
                        for agent, output in outputs.items():
                            output_str = str(output)[:500]
                            shared_context += f"- {agent}: {output_str}\n"
                        shared_context += "]\n"
                except Exception as e:
                    logger.warning(f"Shared pool context retrieval failed: {e}")

            # Inject system prompt as a system message
            messages = []
            enhanced_prompt = self.system_prompt or ""
            if memory_context or shared_context:
                enhanced_prompt += memory_context + shared_context

            if enhanced_prompt:
                from langchain_core.messages import SystemMessage
                messages.append(SystemMessage(content=enhanced_prompt))
            messages.append(HumanMessage(content=query))

            # Execute with timeout enforcement (if configured)
            # Limit recursion to prevent infinite loops (2 iterations = 1 search + 1 read)
            config = {"recursion_limit": self.max_iterations * 2 + 1}

            result = execute_with_timeout(
                self.agent.invoke,
                timeout=self.max_execution_time,
                operation_name=f"agent_{self.name}_execution",
                input={"messages": messages},
                config=config,
                **kwargs
            )

            # Record actual token usage with rate limiter
            if self.enable_rate_limiting and self.rate_limiter:
                try:
                    token_usage = extract_token_usage_from_response(result, self.model_name)
                    if token_usage:
                        self.rate_limiter.record_request(tokens=token_usage.total_tokens)
                except Exception as e:
                    logger.warning(f"Failed to record rate limit usage: {e}")
                    # Fall back to recording just the request
                    self.rate_limiter.record_request(tokens=0)

            # Extract and record token usage
            token_usage = None
            if self.enable_cost_tracking and self.cost_tracker:
                try:
                    token_usage = extract_token_usage_from_response(result, self.model_name)
                    if token_usage:
                        self.cost_tracker.record_usage(token_usage)
                        logger.debug(
                            f"Agent '{self.name}' token usage: "
                            f"{token_usage.input_tokens} input, {token_usage.output_tokens} output, "
                            f"cost: ${token_usage.calculate_cost():.6f}"
                        )
                except BudgetExceededError as e:
                    logger.error(f"Budget exceeded for agent '{self.name}': {e}")
                    raise
                except Exception as e:
                    logger.warning(f"Failed to record token usage: {e}")

            # Record performance metrics (success case)
            self._record_metrics(start_time, success=True, token_usage=token_usage)

            output_messages = result.get("messages", [])
            response = "No response generated"
            if output_messages:
                content = output_messages[-1].content
                # Gemini models may return content as a list of parts — flatten to string
                if isinstance(content, list):
                    response = "\n".join(
                        part.get("text", str(part)) if isinstance(part, dict) else str(part)
                        for part in content
                    )
                else:
                    response = content

            # Save to memory if enabled
            if self.enable_memory and self.memory:
                try:
                    # Log user query
                    self.memory.add_message(
                        role="user",
                        content=query,
                        agent=self.name
                    )
                    # Log assistant response
                    self.memory.add_message(
                        role="assistant",
                        content=response,
                        agent=self.name
                    )
                except Exception as e:
                    logger.warning(f"Failed to save to memory: {e}")

            # Share output with pool if available
            if self.shared_pool:
                try:
                    self.shared_pool.set(
                        f"{self.name}_last_output",
                        response,
                        agent=self.name
                    )
                    self.shared_pool.record_output(
                        agent=self.name,
                        output=response
                    )
                except Exception as e:
                    logger.warning(f"Failed to share with pool: {e}")

            return response

        except BudgetExceededError:
            # Re-raise budget errors
            self._record_metrics(start_time, success=False, error_type="BudgetExceededError")
            raise
        except TimeoutError as e:
            # Re-raise timeout errors (don't let circuit breaker retry these)
            logger.error(f"Agent '{self.name}' timed out: {e}")
            self._record_metrics(start_time, success=False, error_type="TimeoutError")
            raise
        except Exception as e:
            logger.error(f"Agent execution error: {e}")
            self._record_metrics(start_time, success=False, error_type=type(e).__name__)
            raise  # Re-raise to let circuit breaker track failures

    async def arun(self, query: str, **kwargs) -> str:
        """
        Execute agent asynchronously

        Args:
            query: User query
            **kwargs: Additional execution parameters

        Returns:
            Agent response
        """
        if self.enable_circuit_breaker and self.circuit_breaker:
            try:
                return await self.circuit_breaker.acall(self._execute_agent_async, query, **kwargs)
            except CircuitBreakerError as e:
                logger.error(f"Circuit breaker OPEN for agent '{self.name}': {e}")
                return f"Service temporarily unavailable: {str(e)}"
        else:
            return await self._execute_agent_async(query, **kwargs)

    async def _execute_agent_async(self, query: str, **kwargs) -> str:
        """
        Internal async execution logic without circuit breaker

        Args:
            query: User query
            **kwargs: Additional execution parameters

        Returns:
            Agent response
        """
        start_time = time.time()

        try:
            logger.debug(f"Agent '{self.name}' async executing: {query[:50]}...")

            # Rate limiting check (throttle if needed)
            if self.enable_rate_limiting and self.rate_limiter:
                # Estimate tokens for query
                estimated_tokens = estimate_tokens(query)
                if self.system_prompt:
                    estimated_tokens += estimate_tokens(self.system_prompt)

                # Wait if rate limited
                try:
                    self.rate_limiter.wait_if_needed(tokens=estimated_tokens)
                except RateLimitExceeded as e:
                    logger.error(f"Rate limit exceeded for agent '{self.name}': {e}")
                    raise

            # Inject system prompt as a system message
            messages = []
            if self.system_prompt:
                from langchain_core.messages import SystemMessage
                messages.append(SystemMessage(content=self.system_prompt))
            messages.append(HumanMessage(content=query))

            result = await self.agent.ainvoke({"messages": messages}, **kwargs)

            # Record actual token usage with rate limiter
            if self.enable_rate_limiting and self.rate_limiter:
                try:
                    token_usage = extract_token_usage_from_response(result, self.model_name)
                    if token_usage:
                        self.rate_limiter.record_request(tokens=token_usage.total_tokens)
                except Exception as e:
                    logger.warning(f"Failed to record rate limit usage: {e}")
                    # Fall back to recording just the request
                    self.rate_limiter.record_request(tokens=0)

            # Extract and record token usage
            token_usage = None
            if self.enable_cost_tracking and self.cost_tracker:
                try:
                    token_usage = extract_token_usage_from_response(result, self.model_name)
                    if token_usage:
                        self.cost_tracker.record_usage(token_usage)
                        logger.debug(
                            f"Agent '{self.name}' token usage: "
                            f"{token_usage.input_tokens} input, {token_usage.output_tokens} output, "
                            f"cost: ${token_usage.calculate_cost():.6f}"
                        )
                except BudgetExceededError as e:
                    logger.error(f"Budget exceeded for agent '{self.name}': {e}")
                    raise
                except Exception as e:
                    logger.warning(f"Failed to record token usage: {e}")

            # Record performance metrics (success case)
            self._record_metrics(start_time, success=True, token_usage=token_usage)

            output_messages = result.get("messages", [])
            if output_messages:
                content = output_messages[-1].content
                # Gemini models may return content as a list of parts — flatten to string
                if isinstance(content, list):
                    return "\n".join(
                        part.get("text", str(part)) if isinstance(part, dict) else str(part)
                        for part in content
                    )
                return content

            return "No response generated"

        except BudgetExceededError:
            # Re-raise budget errors
            self._record_metrics(start_time, success=False, error_type="BudgetExceededError")
            raise
        except Exception as e:
            logger.error(f"Agent async execution error: {e}")
            self._record_metrics(start_time, success=False, error_type=type(e).__name__)
            raise  # Re-raise to let circuit breaker track failures

    def stream(self, query: str):
        """
        Stream agent execution

        Args:
            query: User query

        Yields:
            Execution steps and final output
        """
        try:
            messages = [HumanMessage(content=query)]
            for chunk in self.agent.stream({"messages": messages}, stream_mode="values"):
                yield chunk

        except (RuntimeError, ValueError, TypeError) as e:
            # Expected streaming errors
            logger.error(f"Agent streaming error: {e}")
            yield {"error": str(e)}
        except Exception as e:
            # Unexpected error - log with full traceback
            logger.exception(f"Unexpected streaming error for agent '{self.name}': {e}")
            yield {"error": str(e)}

    def add_tools(self, tools: List[Union[str, BaseTool]]):
        """Add tools to agent dynamically"""
        new_tools = self._process_tools(tools)
        self.tools.extend(new_tools)
        self._setup_agent(self.max_iterations, None)
        logger.info(f"Added {len(new_tools)} tools to agent '{self.name}'")

    def remove_tools(self, tool_names: List[str]):
        """Remove tools from agent"""
        self.tools = [t for t in self.tools if t.name not in tool_names]
        self._setup_agent(self.max_iterations, None)
        logger.info(f"Removed tools from agent '{self.name}'")

    def _resolve_tool_variables(self, prompt: str) -> str:
        """Resolve {{tool:name}} placeholders in the prompt with actual tool names.

        This allows system prompts to reference tools as variables instead of
        hardcoding tool names. The UI lets users drag-and-drop tools into
        the prompt which inserts {{tool:name}} placeholders.
        """
        import re
        tool_map = {t.name: t.name for t in self.tools}

        def _replace(match: re.Match) -> str:
            tool_name = match.group(1)
            if tool_name in tool_map:
                return tool_map[tool_name]
            logger.warning(f"Tool variable '{{{{tool:{tool_name}}}}}' not found in agent tools")
            return match.group(0)  # leave as-is if not found

        return re.sub(r"\{\{tool:([^}]+)\}\}", _replace, prompt)

    def update_system_prompt(self, prompt: str):
        """Update system prompt and reinitialize agent"""
        self.system_prompt = self._resolve_tool_variables(prompt)
        self._setup_agent(self.max_iterations, None)
        logger.info(f"Updated system prompt for '{self.name}'")

    def get_info(self) -> Dict[str, Any]:
        """Get agent metadata"""
        info = {
            "name": self.name,
            "model": self.model_name,
            "temperature": self.temperature,
            "tools": [t.name for t in self.tools],
            "max_iterations": self.max_iterations,
            "system_prompt": self.system_prompt[:100] + "..." if len(self.system_prompt) > 100 else self.system_prompt
        }

        # Add circuit breaker metrics if enabled
        if self.enable_circuit_breaker and self.circuit_breaker:
            info["circuit_breaker"] = self.circuit_breaker.get_metrics()

        # Add cost tracking metrics if enabled
        if self.enable_cost_tracking and self.cost_tracker:
            info["cost_tracking"] = self.cost_tracker.get_metrics()

        # Add rate limiting metrics if enabled
        if self.enable_rate_limiting and self.rate_limiter:
            info["rate_limiting"] = self.rate_limiter.get_metrics()

        # Add retry metrics if enabled
        if self.enable_retry and self.retry_handler:
            info["retry"] = self.retry_handler.get_metrics()

        # Add performance metrics if enabled
        if self.enable_metrics and self.metrics_collector:
            metrics = self.metrics_collector.get_metrics()
            info["performance_metrics"] = {
                "total_requests": metrics.total_requests,
                "successful_requests": metrics.successful_requests,
                "failed_requests": metrics.failed_requests,
                "avg_latency_ms": metrics.avg_latency_ms,
                "p50_latency_ms": metrics.p50_latency_ms,
                "p95_latency_ms": metrics.p95_latency_ms,
                "p99_latency_ms": metrics.p99_latency_ms,
                "requests_per_second": metrics.requests_per_second,
                "error_rate": metrics.error_rate
            }

        # Add memory stats if enabled
        if self.enable_memory and self.memory:
            try:
                info["memory"] = self.memory.get_stats()
            except Exception:
                info["memory"] = {"enabled": True, "error": "Failed to get stats"}

        # Add shared pool info if attached
        if self.shared_pool:
            try:
                info["shared_pool"] = self.shared_pool.get_stats()
            except Exception:
                info["shared_pool"] = {"attached": True, "error": "Failed to get stats"}

        return info

    @classmethod
    def from_config(cls, config: Dict[str, Any], tool_registry: Optional[ToolRegistry] = None, memory: Optional["MemoryManager"] = None, shared_pool: Optional["SharedMemoryPool"] = None):
        """Create agent from configuration dictionary"""
        # Handle budget configuration
        budget = None
        if "budget" in config:
            budget_config = config["budget"]
            if isinstance(budget_config, dict):
                budget = Budget(**budget_config)
            elif isinstance(budget_config, Budget):
                budget = budget_config

        # Handle rate limit configuration
        rate_limit_config = None
        if "rate_limit_config" in config:
            rl_config = config["rate_limit_config"]
            if isinstance(rl_config, dict):
                rate_limit_config = RateLimitConfig(**rl_config)
            elif isinstance(rl_config, RateLimitConfig):
                rate_limit_config = rl_config

        # Handle retry configuration
        retry_config = None
        if "retry_config" in config:
            r_config = config["retry_config"]
            if isinstance(r_config, dict):
                retry_config = RetryConfig(**r_config)
            elif isinstance(r_config, RetryConfig):
                retry_config = r_config

        # Handle memory configuration
        if memory is None and config.get("memory"):
            try:
                from agent_os.memory import create_memory_manager
                memory_config = config["memory"]
                if isinstance(memory_config, dict):
                    memory = create_memory_manager(
                        namespace=config.get("name", "default"),
                        config=memory_config
                    )
            except ImportError:
                logger.warning("Memory module not available, skipping memory initialization")

        return cls(
            name=config["name"],
            tools=config["tools"],
            model=config.get("model", "gpt-4o-mini"),
            temperature=config.get("temperature", 0),
            system_prompt=config.get("system_prompt"),
            tool_registry=tool_registry,
            max_iterations=config.get("max_iterations", 15),
            max_execution_time=config.get("max_execution_time"),
            enable_circuit_breaker=config.get("enable_circuit_breaker", True),
            circuit_breaker_threshold=config.get("circuit_breaker_threshold", 5),
            circuit_breaker_timeout=config.get("circuit_breaker_timeout", 60.0),
            enable_cost_tracking=config.get("enable_cost_tracking", True),
            budget=budget,
            enable_rate_limiting=config.get("enable_rate_limiting", True),
            rate_limit_config=rate_limit_config,
            enable_retry=config.get("enable_retry", True),
            retry_config=retry_config,
            enable_metrics=config.get("enable_metrics", True),
            memory=memory,
            enable_memory=config.get("enable_memory", True),
            shared_pool=shared_pool
        )

    def cleanup(self):
        """
        Clean up agent resources including LLM connections

        Performs graceful cleanup of all agent resources including:
        - LLM HTTP client connections (OpenAI, Anthropic)
        - Tool resources
        - Manager references (circuit breakers, cost trackers, rate limiters)

        This method is idempotent and safe to call multiple times.
        Prevents memory leaks from unclosed HTTP connections.
        """
        # Skip if already cleaned up (idempotent)
        if self._cleanup_done:
            logger.debug(f"Agent '{self.name}' already cleaned up, skipping")
            return

        try:
            logger.debug(f"Cleaning up agent '{self.name}'...")

            # Cleanup LLM client connections (CRITICAL FIX - prevents connection leaks)
            if hasattr(self, 'llm') and self.llm is not None:
                try:
                    # Try to close the HTTP client if available
                    if hasattr(self.llm, 'client'):
                        client = self.llm.client
                        # OpenAI and Anthropic clients have different close methods
                        if hasattr(client, 'close'):
                            client.close()
                            logger.debug(f"Closed LLM client for agent '{self.name}'")
                        elif hasattr(client, '__exit__'):
                            # Try context manager exit
                            client.__exit__(None, None, None)
                            logger.debug(f"Exited LLM client context for agent '{self.name}'")
                except Exception as e:
                    logger.warning(f"Could not close LLM client for agent '{self.name}': {e}")

            # Cleanup tools if they have cleanup methods
            if hasattr(self, 'tools') and self.tools:
                for tool in self.tools:
                    if hasattr(tool, 'cleanup'):
                        try:
                            tool.cleanup()
                        except Exception as e:
                            logger.warning(f"Error cleaning up tool in agent '{self.name}': {e}")

            # Clear references to managers (they handle their own cleanup)
            self.circuit_breaker = None
            self.cost_tracker = None
            self.rate_limiter = None
            self.retry_handler = None
            self.metrics_collector = None

            # Cleanup memory resources
            if hasattr(self, 'memory') and self.memory:
                try:
                    self.memory.close()
                except Exception as e:
                    logger.warning(f"Error closing memory for agent '{self.name}': {e}")
                self.memory = None

            # Clear shared pool reference (don't destroy - might be shared)
            self.shared_pool = None

            # Mark as cleaned up
            self._cleanup_done = True
            logger.debug(f"Agent '{self.name}' cleaned up successfully")

        except Exception as e:
            logger.error(f"Error during agent cleanup: {e}", exc_info=True)

    def __enter__(self):
        """Context manager entry - returns self"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit - performs cleanup

        Args:
            exc_type: Exception type (if any)
            exc_val: Exception value (if any)
            exc_tb: Exception traceback (if any)

        Returns:
            False to propagate exceptions
        """
        try:
            self.cleanup()
        except Exception as e:
            logger.error(f"Error during context manager cleanup: {e}")

        # Return False to propagate any exceptions that occurred
        return False

    def __del__(self):
        """
        Destructor - ensures cleanup on garbage collection

        Automatically called when agent is garbage collected.
        Prevents memory leaks from unclosed connections.
        """
        try:
            if not self._cleanup_done:
                self.cleanup()
        except Exception:
            # Suppress all errors in destructor to avoid issues during shutdown
            pass

    def __repr__(self) -> str:
        return f"<BaseAgent(name='{self.name}', model='{self.model_name}', tools={len(self.tools)})>"

    def __str__(self) -> str:
        return f"Agent '{self.name}' ({self.model_name}) with {len(self.tools)} tools"
