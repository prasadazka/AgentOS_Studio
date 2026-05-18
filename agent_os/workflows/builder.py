"""Multi-agent workflow orchestration using LangGraph"""

from typing import Dict, List, Callable, Any, Optional, TypedDict
from langgraph.graph import StateGraph, START, END

from agent_os.agents.base import BaseAgent
from agent_os.utils.logging import get_logger
from agent_os.utils.errors import WorkflowExecutionError

logger = get_logger("workflows.builder")


class WorkflowState(TypedDict, total=False):
    """Base state for workflows"""
    input: str
    output: str
    intermediate_results: Dict[str, Any]
    error: Optional[str]


class WorkflowBuilder:
    """
    Build and execute multi-agent workflows

    Supports:
    - Linear chains
    - Conditional routing
    - Parallel execution
    - State management

    Example:
        builder = WorkflowBuilder(agents)
        workflow = builder.chain(["researcher", "analyst"]).build()
        result = workflow.invoke({"input": "Research quantum computing"})
    """

    def __init__(self, agents: Dict[str, BaseAgent]):
        """
        Initialize workflow builder

        Args:
            agents: Dictionary mapping agent names to BaseAgent instances
        """
        self.agents = agents
        self.graph = StateGraph(WorkflowState)
        self._nodes_added = set()
        self._compiled = False

    def _create_agent_node(self, agent_name: str) -> Callable:
        """Create a node function for an agent"""

        def agent_node(state: WorkflowState) -> WorkflowState:
            """Execute agent and update state"""
            agent = self.agents[agent_name]

            # === n8n-style data flow ===
            # Every agent gets: (1) previous node output, (2) workflow settings,
            # (3) all previous nodes' outputs by name (like n8n's $node["Name"])

            current_task = state.get("output") or state.get("input", "")
            parts = [current_task]

            # [Workflow Settings] — parsed from Start node input fields
            original_input = state.get("input", "")
            if original_input:
                try:
                    import json as _json
                    fields = _json.loads(original_input)
                    if isinstance(fields, dict):
                        lines = [f"- {k}: {v}" for k, v in fields.items() if v]
                        if lines:
                            parts.append("[Workflow Settings]\n" + "\n".join(lines))
                except (ValueError, Exception):
                    parts.append(f"[Original Input]: {original_input}")

            # [Previous Node Outputs] — like n8n's $node["NodeName"].json
            intermediates = state.get("intermediate_results", {})
            if intermediates:
                node_lines = []
                for node_id, node_output in intermediates.items():
                    # Truncate long outputs to keep context manageable
                    output_str = str(node_output)
                    if len(output_str) > 1000:
                        output_str = output_str[:1000] + "..."
                    node_lines.append(f"- {node_id}: {output_str}")
                if node_lines:
                    parts.append("[Previous Node Outputs]\n" + "\n".join(node_lines))

            input_text = "\n\n".join(parts)

            try:
                logger.debug(f"Executing agent: {agent_name}")
                output = agent.run(input_text)

                if "intermediate_results" not in state:
                    state["intermediate_results"] = {}

                state["intermediate_results"][agent_name] = output
                state["output"] = output

            except Exception as e:
                logger.error(f"Agent {agent_name} failed: {e}")
                state["error"] = f"Agent {agent_name} error: {str(e)}"

            return state

        return agent_node

    def add_node(self, name: str, agent_name: Optional[str] = None) -> "WorkflowBuilder":
        """
        Add a node to the workflow

        Args:
            name: Node name
            agent_name: Agent to use (defaults to name)

        Returns:
            Self for chaining
        """
        if name in self._nodes_added:
            logger.warning(f"Node '{name}' already added")
            return self

        agent_name = agent_name or name

        if agent_name not in self.agents:
            raise WorkflowExecutionError(
                f"Agent '{agent_name}' not found. Available: {list(self.agents.keys())}"
            )

        self.graph.add_node(name, self._create_agent_node(agent_name))
        self._nodes_added.add(name)
        logger.debug(f"Added node: {name}")

        return self

    def chain(self, agent_names: List[str]) -> "WorkflowBuilder":
        """
        Create a linear chain of agents

        Args:
            agent_names: List of agent names in execution order

        Returns:
            Self for chaining

        Example:
            builder.chain(["researcher", "analyst", "writer"])
        """
        if not agent_names:
            raise WorkflowExecutionError("Chain requires at least one agent")

        for name in agent_names:
            self.add_node(name)

        self.graph.add_edge(START, agent_names[0])

        for i in range(len(agent_names) - 1):
            self.graph.add_edge(agent_names[i], agent_names[i + 1])

        self.graph.add_edge(agent_names[-1], END)

        logger.info(f"Created chain workflow with {len(agent_names)} agents")
        return self

    def conditional(
        self,
        from_node: str,
        router: Callable[[WorkflowState], str],
        routes: Dict[str, str]
    ) -> "WorkflowBuilder":
        """
        Add conditional routing

        Args:
            from_node: Source node
            router: Function that returns next node name based on state
            routes: Mapping of router outputs to node names

        Returns:
            Self for chaining

        Example:
            def router(state):
                if "error" in state:
                    return "error_handler"
                return "success_handler"

            builder.conditional(
                "researcher",
                router,
                {"error_handler": "retry", "success_handler": "analyst"}
            )
        """
        if from_node not in self._nodes_added:
            raise WorkflowExecutionError(f"Node '{from_node}' not found")

        for route_name in routes.values():
            if route_name not in self._nodes_added and route_name != END:
                self.add_node(route_name)

        self.graph.add_conditional_edges(from_node, router, routes)
        logger.info(f"Added conditional routing from {from_node}")

        return self

    def parallel(self, agent_names: List[str], merge_node: Optional[str] = None) -> "WorkflowBuilder":
        """
        Execute agents in parallel (fan-out/fan-in pattern)

        Args:
            agent_names: Agents to execute in parallel
            merge_node: Optional node to merge results

        Returns:
            Self for chaining
        """
        if not agent_names:
            raise WorkflowExecutionError("Parallel requires at least one agent")

        for name in agent_names:
            self.add_node(name)

        fanout = f"fanout_{'_'.join(agent_names)}"
        self.graph.add_node(fanout, lambda state: state)
        self.graph.add_edge(START, fanout)

        for name in agent_names:
            self.graph.add_edge(fanout, name)

        if merge_node:
            self.add_node(merge_node)
            for name in agent_names:
                self.graph.add_edge(name, merge_node)
            self.graph.add_edge(merge_node, END)
        else:
            for name in agent_names:
                self.graph.add_edge(name, END)

        logger.info(f"Created parallel workflow with {len(agent_names)} agents")
        return self

    def add_edge(self, from_node: str, to_node: str) -> "WorkflowBuilder":
        """
        Add custom edge between nodes

        Args:
            from_node: Source node
            to_node: Destination node

        Returns:
            Self for chaining
        """
        if from_node not in self._nodes_added:
            raise WorkflowExecutionError(f"Node '{from_node}' not found")

        if to_node != END and to_node not in self._nodes_added:
            self.add_node(to_node)

        self.graph.add_edge(from_node, to_node)
        logger.debug(f"Added edge: {from_node} -> {to_node}")

        return self

    def build(self):
        """
        Compile the workflow graph

        Returns:
            Compiled workflow ready for execution
        """
        if self._compiled:
            logger.warning("Workflow already compiled")

        self._compiled = True
        compiled = self.graph.compile()
        logger.info(f"Compiled workflow with {len(self._nodes_added)} nodes")

        return compiled

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build and run workflow

        Args:
            input_data: Initial state/input

        Returns:
            Final workflow state
        """
        workflow = self.build()
        return workflow.invoke(input_data)

    async def arun(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Async workflow execution"""
        workflow = self.build()
        return await workflow.ainvoke(input_data)

    def stream(self, input_data: Dict[str, Any]):
        """
        Stream workflow execution

        Args:
            input_data: Initial state

        Yields:
            State updates during execution
        """
        workflow = self.build()
        for step in workflow.stream(input_data):
            yield step

    def visualize(self, output_path: Optional[str] = None) -> Optional[bytes]:
        """
        Generate workflow visualization

        Args:
            output_path: Optional path to save image

        Returns:
            Image bytes if output_path is None
        """
        try:
            workflow = self.build()
            graph_image = workflow.get_graph().draw_mermaid_png()

            if output_path:
                with open(output_path, 'wb') as f:
                    f.write(graph_image)
                logger.info(f"Saved workflow diagram to {output_path}")
                return None
            else:
                return graph_image

        except Exception as e:
            logger.error(f"Visualization failed: {e}")
            return None

    @classmethod
    def from_config(cls, agents: Dict[str, BaseAgent], config: Dict[str, Any]) -> "WorkflowBuilder":
        """
        Create workflow from configuration

        Args:
            agents: Available agents
            config: Workflow configuration

        Returns:
            WorkflowBuilder instance
        """
        builder = cls(agents)
        workflow_type = config.get("type", "chain")

        if workflow_type == "chain":
            builder.chain(config["agents"])
        elif workflow_type == "parallel":
            builder.parallel(config["agents"])
        else:
            raise WorkflowExecutionError(f"Unknown workflow type: {workflow_type}")

        return builder
