"""Simplified Agent & Workflow API (lazy-loaded)"""

from typing import Optional, List, Dict, Any, Union, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_os.agents.base import BaseAgent
    from agent_os.workflows.builder import WorkflowBuilder as _WorkflowBuilder
    from agent_os.config.schemas import ReliabilityConfig


class Agent:
    """
    Simplified Agent API with auto-registered tools.

    Examples:
        # Pre-configured agent (1 line)
        agent = Agent.researcher()
        result = agent.run("Find papers on RAG")

        # Custom agent (3 lines)
        agent = Agent.create(
            name="MyAgent",
            tools=["wikipedia_search", "arxiv_search"],
            prompt="You are a helpful assistant."
        )
        result = agent.run("Research quantum computing")

        # From YAML config
        agent = Agent.from_file("configs/my_agent.yaml")
    """

    @staticmethod
    def create(
        name: str,
        tools: List[Union[str, Any]],
        model: str = "gpt-4o-mini",
        temperature: float = 0,
        prompt: Optional[str] = None,
        config: Optional["ReliabilityConfig"] = None
    ) -> "BaseAgent":
        """
        Create agent with auto-loaded tools from global registry.

        This is the primary way to create agents. For simple cases, just provide
        name and tools. For advanced control, pass a ReliabilityConfig.

        Args:
            name: Agent name
            tools: List of tool names (strings) from global registry
            model: LLM model name (default: gpt-4o-mini)
            temperature: LLM temperature (default: 0)
            prompt: System prompt (optional)
            config: ReliabilityConfig for advanced options (optional)

        Returns:
            BaseAgent instance ready to use

        Examples:
            # Simple usage (sensible defaults)
            agent = Agent.create(
                name="Researcher",
                tools=["wikipedia_search", "arxiv_search"],
                prompt="You are a research assistant."
            )

            # Advanced usage with config
            from agent_os.config.schemas import ReliabilityConfig

            config = ReliabilityConfig(
                budget_limit=5.0,  # $5 daily budget
                max_execution_time=30.0,  # 30 second timeout
                circuit_breaker=True
            )
            agent = Agent.create(
                name="BudgetAgent",
                tools=["wikipedia_search"],
                config=config
            )

            # Minimal overhead (for testing)
            agent = Agent.create(
                name="TestAgent",
                tools=[],
                config=ReliabilityConfig.minimal()
            )

            # Production-ready with all safety features
            agent = Agent.create(
                name="ProdAgent",
                tools=["wikipedia_search"],
                config=ReliabilityConfig.production(daily_budget=50.0)
            )
        """
        from agent_os.agents.base import BaseAgent
        from agent_os.tools.global_registry import get_global_registry

        # Build kwargs
        kwargs = {
            "name": name,
            "tools": tools,
            "model": model,
            "temperature": temperature,
            "system_prompt": prompt,
            "tool_registry": get_global_registry()
        }

        # Apply config if provided
        if config is not None:
            kwargs.update(config.to_agent_kwargs())

        return BaseAgent(**kwargs)

    @staticmethod
    def from_config(config: Dict[str, Any]) -> "BaseAgent":
        """
        Create agent from config dictionary.

        Args:
            config: Dictionary with agent configuration

        Returns:
            BaseAgent instance

        Example:
            config = {
                "name": "Researcher",
                "tools": ["wikipedia_search"],
                "model": "gpt-4o-mini",
                "prompt": "You are a researcher."
            }
            agent = Agent.from_config(config)
        """
        from agent_os.agents.base import BaseAgent
        from agent_os.tools.global_registry import get_global_registry

        return BaseAgent.from_config(config, tool_registry=get_global_registry())

    @staticmethod
    def from_file(path: str) -> "BaseAgent":
        """
        Create agent from YAML or JSON config file.

        Args:
            path: Path to config file (.yaml, .yml, or .json)

        Returns:
            BaseAgent instance

        Example:
            agent = Agent.from_file("configs/researcher.yaml")
        """
        from agent_os.config.loader import ConfigLoader
        from agent_os.tools.global_registry import get_global_registry

        loader = ConfigLoader(tool_registry=get_global_registry())
        return loader.create_agent_from_file(path)

    @staticmethod
    def researcher(name: str = "Researcher", model: str = "gpt-4o-mini") -> "BaseAgent":
        """
        Pre-configured research agent with Wikipedia, ArXiv, and citation tools.

        Args:
            name: Agent name (default: "Researcher")
            model: LLM model (default: gpt-4o-mini)

        Returns:
            Configured research agent

        Example:
            agent = Agent.researcher()
            result = agent.run("Find papers on transformer architecture")
        """
        return Agent.create(
            name=name,
            tools=["wikipedia_search", "arxiv_search", "citation_generate"],
            model=model,
            prompt="You are a research assistant. Search for information and always cite your sources."
        )

    @staticmethod
    def analyst(name: str = "Analyst", model: str = "gpt-4o-mini") -> "BaseAgent":
        """
        Pre-configured data analyst agent with file processing tools.

        Args:
            name: Agent name (default: "Analyst")
            model: LLM model (default: gpt-4o-mini)

        Returns:
            Configured data analyst agent

        Example:
            agent = Agent.analyst()
            result = agent.run("Analyze the data in report.csv")
        """
        return Agent.create(
            name=name,
            tools=["file_read", "json_process", "csv_process", "pdf_extract_text"],
            model=model,
            prompt="You are a data analyst. Analyze data and provide clear, actionable insights."
        )

    @staticmethod
    def coder(name: str = "Coder", model: str = "gpt-4o-mini") -> "BaseAgent":
        """
        Pre-configured coding assistant with file and code analysis tools.

        Args:
            name: Agent name (default: "Coder")
            model: LLM model (default: gpt-4o-mini)

        Returns:
            Configured coding agent

        Example:
            agent = Agent.coder()
            result = agent.run("Review the code in main.py")
        """
        return Agent.create(
            name=name,
            tools=["file_read", "file_write", "directory_list"],
            model=model,
            prompt="You are a coding assistant. Write clean, well-documented code."
        )

    @staticmethod
    def writer(name: str = "Writer", model: str = "gpt-4o-mini") -> "BaseAgent":
        """
        Pre-configured writing agent (no tools, pure LLM).

        Args:
            name: Agent name (default: "Writer")
            model: LLM model (default: gpt-4o-mini)

        Returns:
            Configured writing agent

        Example:
            agent = Agent.writer()
            result = agent.run("Summarize the following research...")
        """
        return Agent.create(
            name=name,
            tools=[],
            model=model,
            prompt="You are a professional writer. Write clear, engaging, and well-structured content."
        )


class ExecutableWorkflow:
    """
    Wrapper around compiled LangGraph workflow with simple run interface.

    This class provides a clean API for executing workflows without needing
    to understand the underlying LangGraph state management.

    Example:
        workflow = Workflow.chain([agent1, agent2])

        # Simple string in, string out
        result = workflow.run("Research AI trends")

        # Get full state with intermediate results
        state = workflow.run_with_state("Research AI trends")
        print(state["intermediate_results"])
    """

    def __init__(self, compiled_graph, agents: Dict[str, "BaseAgent"]):
        """
        Initialize executable workflow.

        Args:
            compiled_graph: Compiled LangGraph workflow
            agents: Dictionary of agents used in the workflow
        """
        self._graph = compiled_graph
        self._agents = agents

    def run(self, input_text: str) -> str:
        """
        Run workflow with string input, return final output string.

        Args:
            input_text: Input query or text to process

        Returns:
            Final output from the last agent in the workflow

        Example:
            result = workflow.run("Research quantum computing")
            print(result)
        """
        result = self._graph.invoke({"input": input_text})
        return result.get("output", "")

    async def arun(self, input_text: str) -> str:
        """
        Async run workflow.

        Args:
            input_text: Input query or text to process

        Returns:
            Final output from the last agent
        """
        result = await self._graph.ainvoke({"input": input_text})
        return result.get("output", "")

    def run_with_state(self, input_text: str) -> Dict[str, Any]:
        """
        Run workflow and return full state including intermediate results.

        Args:
            input_text: Input query or text to process

        Returns:
            Full workflow state dict with keys:
                - input: Original input
                - output: Final output
                - intermediate_results: Dict of each agent's output
                - error: Error message if any

        Example:
            state = workflow.run_with_state("Research AI")
            for agent_name, output in state["intermediate_results"].items():
                print(f"{agent_name}: {output[:100]}...")
        """
        return self._graph.invoke({"input": input_text})

    async def arun_with_state(self, input_text: str) -> Dict[str, Any]:
        """Async run returning full state."""
        return await self._graph.ainvoke({"input": input_text})

    def stream(self, input_text: str):
        """
        Stream workflow execution, yielding state updates.

        Args:
            input_text: Input query or text to process

        Yields:
            State updates as workflow executes

        Example:
            for step in workflow.stream("Research AI"):
                print(f"Step: {step}")
        """
        for step in self._graph.stream({"input": input_text}):
            yield step

    @property
    def agents(self) -> Dict[str, "BaseAgent"]:
        """Get agents used in this workflow."""
        return self._agents

    @property
    def agent_names(self) -> List[str]:
        """Get list of agent names in this workflow."""
        return list(self._agents.keys())


class WorkflowBuilder:
    """
    Fluent builder for custom workflows.

    Use this when you need more control than Workflow.chain() or Workflow.parallel().

    Example:
        # Custom workflow with conditional routing
        workflow = (
            Workflow.builder([researcher, analyst, writer, editor])
            .chain(["Researcher", "Analyst"])
            .conditional(
                "Analyst",
                router=lambda state: "Writer" if "good" in state["output"] else "Editor",
                routes={"Writer": "Writer", "Editor": "Editor"}
            )
            .build()
        )
        result = workflow.run("Research AI trends")
    """

    def __init__(self, agents: List["BaseAgent"]):
        """
        Initialize builder with list of agents.

        Args:
            agents: List of BaseAgent instances to use in workflow
        """
        from agent_os.workflows.builder import WorkflowBuilder as _WorkflowBuilder

        self._agents_list = agents
        self._agents_dict = {a.name: a for a in agents}
        self._builder = _WorkflowBuilder(self._agents_dict)
        self._has_structure = False

    def chain(self, agent_names: Optional[List[str]] = None) -> "WorkflowBuilder":
        """
        Create linear chain of agents.

        Args:
            agent_names: List of agent names in execution order.
                        If None, chains all agents in the order provided.

        Returns:
            Self for method chaining

        Example:
            builder.chain(["Researcher", "Analyst", "Writer"])
        """
        if agent_names is None:
            agent_names = [a.name for a in self._agents_list]
        self._builder.chain(agent_names)
        self._has_structure = True
        return self

    def parallel(
        self,
        agent_names: List[str],
        merge: Optional[str] = None
    ) -> "WorkflowBuilder":
        """
        Execute agents in parallel.

        Args:
            agent_names: List of agent names to run in parallel
            merge: Optional agent name to merge results

        Returns:
            Self for method chaining

        Example:
            builder.parallel(["WebSearch", "ArxivSearch"], merge="Merger")
        """
        self._builder.parallel(agent_names, merge_node=merge)
        self._has_structure = True
        return self

    def conditional(
        self,
        from_agent: str,
        router: Callable[[Dict[str, Any]], str],
        routes: Dict[str, str]
    ) -> "WorkflowBuilder":
        """
        Add conditional routing after an agent.

        Args:
            from_agent: Agent name to route from
            router: Function that takes state dict and returns route key
            routes: Mapping of route keys to agent names

        Returns:
            Self for method chaining

        Example:
            def quality_router(state):
                return "good" if "success" in state["output"] else "bad"

            builder.conditional(
                "Analyst",
                router=quality_router,
                routes={"good": "Writer", "bad": "Researcher"}
            )
        """
        self._builder.conditional(from_agent, router, routes)
        return self

    def add_edge(self, from_agent: str, to_agent: str) -> "WorkflowBuilder":
        """
        Add custom edge between agents.

        Args:
            from_agent: Source agent name
            to_agent: Destination agent name

        Returns:
            Self for method chaining
        """
        self._builder.add_edge(from_agent, to_agent)
        return self

    def build(self) -> ExecutableWorkflow:
        """
        Build and return executable workflow.

        Returns:
            ExecutableWorkflow ready to run

        Raises:
            ValueError: If no workflow structure defined
        """
        if not self._has_structure:
            raise ValueError(
                "No workflow structure defined. "
                "Call .chain(), .parallel(), or add edges before .build()"
            )

        compiled = self._builder.build()
        return ExecutableWorkflow(compiled, self._agents_dict)


class Workflow:
    """
    Simplified Workflow API for multi-agent orchestration.

    Provides static factory methods for common workflow patterns
    and a builder for custom workflows.

    Examples:
        # Chain workflow (agents run in sequence)
        workflow = Workflow.chain([
            Agent.researcher(),
            Agent.analyst(),
            Agent.writer()
        ])
        result = workflow.run("Research AI trends")

        # Parallel workflow (agents run concurrently)
        workflow = Workflow.parallel(
            agents=[Agent.researcher(), Agent.analyst()],
            merge=Agent.writer()
        )
        result = workflow.run("Research quantum computing")

        # Custom workflow with builder
        workflow = (
            Workflow.builder([agent1, agent2, agent3])
            .chain(["agent1", "agent2"])
            .conditional("agent2", router, routes)
            .build()
        )
    """

    @staticmethod
    def chain(agents: List["BaseAgent"]) -> ExecutableWorkflow:
        """
        Create a chain workflow where agents run in sequence.

        Each agent receives the output of the previous agent as input.

        Args:
            agents: List of agents in execution order

        Returns:
            ExecutableWorkflow ready to run

        Example:
            workflow = Workflow.chain([
                Agent.researcher(),
                Agent.create("Analyst", tools=[], prompt="Analyze the research"),
                Agent.writer()
            ])
            result = workflow.run("Research AI safety")
        """
        from agent_os.workflows.builder import WorkflowBuilder as _WorkflowBuilder

        agents_dict = {agent.name: agent for agent in agents}
        agent_names = [agent.name for agent in agents]

        builder = _WorkflowBuilder(agents_dict)
        compiled = builder.chain(agent_names).build()

        return ExecutableWorkflow(compiled, agents_dict)

    @staticmethod
    def parallel(
        agents: List["BaseAgent"],
        merge: Optional["BaseAgent"] = None
    ) -> ExecutableWorkflow:
        """
        Create a parallel workflow where agents run concurrently.

        All agents receive the same input and run in parallel.
        Optionally, a merge agent combines results.

        Args:
            agents: List of agents to run in parallel
            merge: Optional agent to merge/combine results

        Returns:
            ExecutableWorkflow ready to run

        Example:
            workflow = Workflow.parallel(
                agents=[
                    Agent.create("WikiSearch", tools=["wikipedia_search"]),
                    Agent.create("ArxivSearch", tools=["arxiv_search"])
                ],
                merge=Agent.create("Merger", tools=[], prompt="Combine the research")
            )
            result = workflow.run("quantum computing")
        """
        from agent_os.workflows.builder import WorkflowBuilder as _WorkflowBuilder

        agents_dict = {agent.name: agent for agent in agents}
        agent_names = [agent.name for agent in agents]

        merge_name = None
        if merge is not None:
            agents_dict[merge.name] = merge
            merge_name = merge.name

        builder = _WorkflowBuilder(agents_dict)
        compiled = builder.parallel(agent_names, merge_node=merge_name).build()

        return ExecutableWorkflow(compiled, agents_dict)

    @staticmethod
    def builder(agents: List["BaseAgent"]) -> WorkflowBuilder:
        """
        Create a workflow builder for custom workflows.

        Use this when you need conditional routing, loops, or other
        complex workflow patterns.

        Args:
            agents: List of agents available for the workflow

        Returns:
            WorkflowBuilder for fluent workflow construction

        Example:
            def quality_check(state):
                if "error" in state.get("output", "").lower():
                    return "retry"
                return "continue"

            workflow = (
                Workflow.builder([researcher, analyst, writer])
                .chain(["Researcher", "Analyst"])
                .conditional("Analyst", quality_check, {
                    "retry": "Researcher",
                    "continue": "Writer"
                })
                .build()
            )
        """
        return WorkflowBuilder(agents)

    @staticmethod
    def from_config(
        agents: List["BaseAgent"],
        config: Dict[str, Any]
    ) -> ExecutableWorkflow:
        """
        Create workflow from configuration dictionary.

        Args:
            agents: List of available agents
            config: Workflow configuration with keys:
                - type: "chain" or "parallel"
                - agents: List of agent names in order
                - merge: (parallel only) Agent name to merge results

        Returns:
            ExecutableWorkflow ready to run

        Example:
            config = {
                "type": "chain",
                "agents": ["Researcher", "Analyst", "Writer"]
            }
            workflow = Workflow.from_config(agents, config)
        """
        from agent_os.workflows.builder import WorkflowBuilder as _WorkflowBuilder

        agents_dict = {agent.name: agent for agent in agents}
        builder = _WorkflowBuilder(agents_dict)

        workflow_type = config.get("type", "chain")
        agent_names = config.get("agents", [agent.name for agent in agents])

        if workflow_type == "chain":
            builder.chain(agent_names)
        elif workflow_type == "parallel":
            merge_name = config.get("merge")
            builder.parallel(agent_names, merge_node=merge_name)
        else:
            raise ValueError(f"Unknown workflow type: {workflow_type}")

        compiled = builder.build()
        return ExecutableWorkflow(compiled, agents_dict)


class Tool:
    """
    Tool utilities for discovering and accessing registered tools.

    Examples:
        # List all available tools
        tools = Tool.list()
        print(tools)  # ['wikipedia_search', 'arxiv_search', ...]

        # Get tools by category
        research_tools = Tool.by_category("research")

        # Get specific tool
        wiki_tool = Tool.get("wikipedia_search")
    """

    @staticmethod
    def list() -> List[str]:
        """
        List all available tool names in the global registry.

        Returns:
            List of tool name strings

        Example:
            tools = Tool.list()
            print(f"Available tools: {len(tools)}")
        """
        from agent_os.tools.global_registry import get_global_registry
        return get_global_registry().list_all()

    @staticmethod
    def get(name: str):
        """
        Get a specific tool by name.

        Args:
            name: Tool name

        Returns:
            BaseTool instance or None if not found

        Example:
            tool = Tool.get("wikipedia_search")
            if tool:
                result = tool.execute(query="Python programming")
        """
        from agent_os.tools.global_registry import get_global_registry
        return get_global_registry().get(name)

    @staticmethod
    def by_category(category: str) -> List:
        """
        Get all tools in a category.

        Args:
            category: Category name (e.g., "research", "file", "web")

        Returns:
            List of BaseTool instances in that category

        Example:
            research_tools = Tool.by_category("research")
            for tool in research_tools:
                print(f"  {tool.metadata.name}: {tool.metadata.description}")
        """
        from agent_os.tools.global_registry import get_global_registry
        return get_global_registry().get_by_category(category)

    @staticmethod
    def categories() -> List[str]:
        """
        List all tool categories.

        Returns:
            List of category names

        Example:
            categories = Tool.categories()
            for cat in categories:
                print(f"{cat}: {len(Tool.by_category(cat))} tools")
        """
        from agent_os.tools.global_registry import get_global_registry
        registry = get_global_registry()
        return list(registry._categories.keys())

    @staticmethod
    def search(query: str) -> List:
        """
        Search tools by name or description.

        Args:
            query: Search query string

        Returns:
            List of matching BaseTool instances

        Example:
            tools = Tool.search("search")
            # Returns: wikipedia_search, arxiv_search, web_search, etc.
        """
        from agent_os.tools.global_registry import get_global_registry
        registry = get_global_registry()
        query_lower = query.lower()

        results = []
        for name in registry.list_all():
            tool = registry.get(name)
            if tool:
                if (query_lower in name.lower() or
                    query_lower in tool.metadata.description.lower()):
                    results.append(tool)

        return results
