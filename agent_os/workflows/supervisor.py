"""
Supervisor Pattern for Multi-Agent Workflows

A supervisor agent that intelligently routes tasks to specialized worker agents
based on the task requirements and worker capabilities.
"""

import uuid
from typing import Dict, List, Optional, Any, Literal, TYPE_CHECKING
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agent_os.agents.base import BaseAgent
from agent_os.utils.logging import get_logger
from agent_os.utils.errors import WorkflowExecutionError

# Memory imports (optional)
if TYPE_CHECKING:
    from agent_os.memory import SharedMemoryPool

logger = get_logger("workflows.supervisor")


class AgentCapability(BaseModel):
    """Description of an agent's capabilities"""
    name: str = Field(..., description="Agent identifier")
    description: str = Field(..., description="What the agent can do")
    tools: List[str] = Field(default_factory=list, description="Available tools")
    specialization: str = Field(..., description="Domain expertise")


class SupervisorDecision(BaseModel):
    """Supervisor's routing decision"""
    next_agent: str = Field(..., description="Name of next agent to execute, or 'FINISH' to end")
    reasoning: str = Field(..., description="Why this agent was chosen")
    instructions: Optional[str] = Field(None, description="Specific instructions for the agent")


class SupervisorState(BaseModel):
    """State managed by supervisor"""
    query: str = Field(..., description="Original user query")
    history: List[Dict[str, str]] = Field(default_factory=list, description="Execution history")
    current_result: str = Field(default="", description="Current result")
    iterations: int = Field(default=0, description="Number of iterations")
    completed: bool = Field(default=False, description="Whether task is complete")
    error: Optional[str] = Field(None, description="Error if any")


class SupervisorAgent:
    """
    Supervisor pattern implementation using LLM for intelligent routing.

    The supervisor analyzes the task and agent capabilities to dynamically
    decide which agent to execute next, continuing until the task is complete.

    Features:
    - LLM-based routing decisions
    - Iterative task decomposition
    - Error handling and recovery
    - Max iteration safety limit
    - Full execution tracing

    Example:
        supervisor = SupervisorAgent(
            worker_agents={
                "researcher": research_agent,
                "analyst": analyst_agent,
                "writer": writer_agent
            },
            model="gpt-4o-mini"
        )

        result = supervisor.run("Research and analyze quantum computing trends")
    """

    def __init__(
        self,
        worker_agents: Dict[str, BaseAgent],
        model: str = "gpt-4o-mini",
        temperature: float = 0,
        max_iterations: int = 10,
        system_prompt: Optional[str] = None,
        enable_shared_memory: bool = True,
        workflow_id: Optional[str] = None
    ):
        """
        Initialize supervisor agent

        Args:
            worker_agents: Dictionary of worker agents {name: agent}
            model: LLM model for routing decisions
            temperature: LLM temperature (0 for deterministic)
            max_iterations: Maximum workflow iterations (safety limit)
            system_prompt: Custom system prompt (optional)
            enable_shared_memory: Enable shared memory pool for cross-agent communication
            workflow_id: Unique identifier for this workflow (auto-generated if not provided)
        """
        if not worker_agents:
            raise WorkflowExecutionError("Supervisor requires at least one worker agent")

        self.worker_agents = worker_agents
        self.model = model
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.enable_shared_memory = enable_shared_memory
        self.workflow_id = workflow_id or f"workflow_{uuid.uuid4().hex[:8]}"

        # Setup shared memory pool for cross-agent communication
        self.shared_pool: Optional["SharedMemoryPool"] = None
        if enable_shared_memory:
            try:
                from agent_os.memory import get_shared_pool
                self.shared_pool = get_shared_pool(self.workflow_id)

                # Inject shared pool into all worker agents
                for name, agent in self.worker_agents.items():
                    if hasattr(agent, 'shared_pool'):
                        agent.shared_pool = self.shared_pool
                        logger.debug(f"Injected shared pool into agent '{name}'")

                logger.info(f"Shared memory pool enabled for workflow '{self.workflow_id}'")
            except ImportError:
                logger.warning("Memory module not available, shared memory disabled")
                self.shared_pool = None

        # Extract agent capabilities
        self.capabilities = self._extract_capabilities()

        # Create routing LLM
        self.llm = ChatOpenAI(model=model, temperature=temperature)

        # System prompt
        self.system_prompt = system_prompt or self._default_system_prompt()

        logger.info(
            f"Supervisor initialized with {len(worker_agents)} workers, "
            f"max_iterations={max_iterations}, shared_memory={enable_shared_memory}"
        )

    def _extract_capabilities(self) -> List[AgentCapability]:
        """Extract capabilities from worker agents"""
        capabilities = []

        for name, agent in self.worker_agents.items():
            # Extract tool names
            tool_names = [tool.name for tool in agent.tools] if hasattr(agent, 'tools') else []

            # Get agent prompt to infer specialization
            specialization = self._infer_specialization(agent)

            capability = AgentCapability(
                name=name,
                description=f"Agent: {name}",
                tools=tool_names,
                specialization=specialization
            )

            capabilities.append(capability)

        return capabilities

    def _infer_specialization(self, agent: BaseAgent) -> str:
        """Infer agent specialization from its configuration"""
        # Use system prompt if available
        if hasattr(agent, 'system_prompt') and agent.system_prompt:
            # Extract first sentence as specialization
            prompt = agent.system_prompt.strip()
            first_sentence = prompt.split('.')[0]
            return first_sentence

        # Fallback to tool-based inference
        if not hasattr(agent, 'tools') or not agent.tools:
            return "General purpose assistant"

        tool_names = [tool.name for tool in agent.tools]

        if any('wikipedia' in t or 'arxiv' in t for t in tool_names):
            return "Research specialist"
        elif any('csv' in t or 'json' in t or 'sql' in t for t in tool_names):
            return "Data analysis specialist"
        elif any('email' in t or 'slack' in t for t in tool_names):
            return "Communication specialist"
        elif any('text' in t or 'grammar' in t for t in tool_names):
            return "Writing and editing specialist"
        else:
            return f"Specialist with tools: {', '.join(tool_names[:3])}"

    def _default_system_prompt(self) -> str:
        """Generate default system prompt for supervisor"""
        capabilities_desc = "\n".join([
            f"- {cap.name}: {cap.specialization} (tools: {', '.join(cap.tools) if cap.tools else 'none'})"
            for cap in self.capabilities
        ])

        return f"""You are a supervisor coordinating a team of specialized AI agents.

Available agents:
{capabilities_desc}

Your role:
1. Analyze the user's request
2. Decide which agent should handle the next step
3. Continue routing until the task is fully complete
4. Return 'FINISH' when the task is done

Guidelines:
- Break complex tasks into steps
- Route each step to the most appropriate specialist
- Use agent outputs to inform next steps
- Always provide clear reasoning for your decisions
- Signal completion with next_agent='FINISH'

Be efficient - don't over-delegate. If the task is simple, use one agent and finish."""

    def _make_routing_decision(self, state: SupervisorState) -> SupervisorDecision:
        """
        Make intelligent routing decision using LLM

        Args:
            state: Current supervisor state

        Returns:
            Routing decision with next agent and reasoning
        """
        # Build decision prompt
        history_text = "\n".join([
            f"Step {i+1} - {entry['agent']}: {entry['result'][:200]}..."
            for i, entry in enumerate(state.history)
        ])

        available_agents = [cap.name for cap in self.capabilities]

        prompt = f"""Task: {state.query}

Execution History:
{history_text if history_text else "(No steps executed yet)"}

Current iteration: {state.iterations}/{self.max_iterations}

Available agents: {', '.join(available_agents)}

Decide the next step. If task is complete, return next_agent='FINISH'.
Provide your decision in JSON format:
{{
    "next_agent": "agent_name or FINISH",
    "reasoning": "explanation of why this agent is chosen",
    "instructions": "specific instructions for the agent (optional)"
}}"""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt)
        ]

        try:
            # Get LLM decision
            response = self.llm.invoke(messages)
            content = response.content.strip()

            # Parse JSON response
            import json

            # Extract JSON from markdown code blocks if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            decision_dict = json.loads(content)
            decision = SupervisorDecision(**decision_dict)

            logger.info(
                f"Routing decision: {decision.next_agent} - {decision.reasoning}"
            )

            return decision

        except Exception as e:
            logger.error(f"Routing decision failed: {e}")
            # Fallback: finish workflow
            return SupervisorDecision(
                next_agent="FINISH",
                reasoning=f"Error in routing: {str(e)}"
            )

    def run(self, query: str) -> Dict[str, Any]:
        """
        Execute supervised workflow

        Args:
            query: User query/task

        Returns:
            Final result with execution history
        """
        state = SupervisorState(query=query)

        # Initialize shared pool state if enabled
        if self.shared_pool:
            try:
                self.shared_pool.set("query", query, agent="supervisor")
                self.shared_pool.set_phase("initialization")
            except Exception as e:
                logger.warning(f"Failed to initialize shared pool state: {e}")

        logger.info(f"Starting supervised workflow: {query}")

        while not state.completed and state.iterations < self.max_iterations:
            state.iterations += 1

            # Get routing decision
            decision = self._make_routing_decision(state)

            # Check for completion
            if decision.next_agent == "FINISH":
                state.completed = True
                logger.info(f"Workflow completed after {state.iterations} iterations")
                break

            # Validate agent exists
            if decision.next_agent not in self.worker_agents:
                error_msg = f"Unknown agent: {decision.next_agent}"
                logger.error(error_msg)
                state.error = error_msg
                state.completed = True
                break

            # Execute agent
            agent = self.worker_agents[decision.next_agent]

            try:
                # Update shared pool phase
                if self.shared_pool:
                    try:
                        self.shared_pool.set_phase(f"executing_{decision.next_agent}")
                        self.shared_pool.set("current_agent", decision.next_agent, agent="supervisor")
                        self.shared_pool.set("iteration", state.iterations, agent="supervisor")
                    except Exception as e:
                        logger.warning(f"Failed to update shared pool phase: {e}")

                # Prepare agent input
                agent_input = state.current_result if state.current_result else query
                if decision.instructions:
                    agent_input = f"{decision.instructions}\n\n{agent_input}"

                logger.debug(f"Executing agent: {decision.next_agent}")
                result = agent.run(agent_input)

                # Update state
                state.current_result = result
                state.history.append({
                    "agent": decision.next_agent,
                    "reasoning": decision.reasoning,
                    "result": result
                })

                # Record to shared pool
                if self.shared_pool:
                    try:
                        self.shared_pool.record_output(
                            agent=decision.next_agent,
                            output=result,
                            phase=f"step_{state.iterations}"
                        )
                        self.shared_pool.set("current_result", result, agent="supervisor")
                    except Exception as e:
                        logger.warning(f"Failed to record to shared pool: {e}")

            except Exception as e:
                error_msg = f"Agent {decision.next_agent} failed: {str(e)}"
                logger.error(error_msg)
                state.error = error_msg
                state.completed = True

                # Record error to shared pool
                if self.shared_pool:
                    try:
                        self.shared_pool.set("error", error_msg, agent="supervisor")
                        self.shared_pool.set_phase("error")
                    except Exception:
                        pass
                break

        # Check for max iterations
        if state.iterations >= self.max_iterations and not state.completed:
            logger.warning(f"Reached max iterations ({self.max_iterations})")
            state.error = f"Max iterations ({self.max_iterations}) exceeded"
            state.completed = True

        # Update shared pool with completion status
        if self.shared_pool:
            try:
                self.shared_pool.set_phase("completed" if not state.error else "error")
                self.shared_pool.set("final_result", state.current_result, agent="supervisor")
                self.shared_pool.set("completed", state.completed, agent="supervisor")
            except Exception as e:
                logger.warning(f"Failed to update shared pool completion: {e}")

        # Build final result
        result = {
            "query": state.query,
            "result": state.current_result,
            "iterations": state.iterations,
            "history": state.history,
            "completed": state.completed,
            "error": state.error,
            "workflow_id": self.workflow_id
        }

        # Include shared pool stats if available
        if self.shared_pool:
            try:
                result["shared_pool_stats"] = self.shared_pool.get_stats()
            except Exception:
                pass

        return result

    async def arun(self, query: str) -> Dict[str, Any]:
        """Async version of run (executes agents synchronously in async context)"""
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(None, self.run, query)

    def get_execution_summary(self, result: Dict[str, Any]) -> str:
        """
        Generate human-readable summary of execution

        Args:
            result: Result from run()

        Returns:
            Formatted summary string
        """
        summary = f"Supervised Workflow Execution\n{'='*60}\n\n"
        summary += f"Query: {result['query']}\n"
        summary += f"Status: {'✅ Completed' if result['completed'] else '❌ Failed'}\n"
        summary += f"Iterations: {result['iterations']}\n"

        if result.get('error'):
            summary += f"Error: {result['error']}\n"

        summary += f"\nExecution Steps:\n{'-'*60}\n"

        for i, step in enumerate(result['history'], 1):
            summary += f"\nStep {i}: {step['agent']}\n"
            summary += f"Reasoning: {step['reasoning']}\n"
            summary += f"Result: {step['result'][:200]}...\n"

        summary += f"\n{'='*60}\n"
        summary += f"Final Result:\n{result['result']}\n"

        return summary

    def cleanup(self) -> None:
        """
        Cleanup supervisor resources including shared memory pool.

        Call this when the workflow is complete to free resources.
        """
        if self.shared_pool:
            try:
                from agent_os.memory import SharedMemoryPool
                SharedMemoryPool.destroy_pool(self.workflow_id)
                logger.info(f"Cleaned up shared pool for workflow '{self.workflow_id}'")
            except Exception as e:
                logger.warning(f"Error cleaning up shared pool: {e}")
            self.shared_pool = None

        # Clear shared pool references from worker agents
        for name, agent in self.worker_agents.items():
            if hasattr(agent, 'shared_pool'):
                agent.shared_pool = None

    def get_shared_context(self) -> Dict[str, Any]:
        """
        Get current shared context from the memory pool.

        Returns:
            Dict with current workflow context or empty dict if not available
        """
        if self.shared_pool:
            try:
                return self.shared_pool.get_workflow_context()
            except Exception as e:
                logger.warning(f"Failed to get shared context: {e}")
        return {}

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - performs cleanup"""
        self.cleanup()
        return False

    def __repr__(self) -> str:
        return f"<SupervisorAgent(workers={len(self.worker_agents)}, max_iterations={self.max_iterations}, workflow_id='{self.workflow_id}')>"
