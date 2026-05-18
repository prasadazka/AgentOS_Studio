"""
Lightweight ReAct agent wrapper for chat queries with tool access.

Executes queries with selected tools, manages context, handles errors gracefully.
"""

from typing import List, Dict, Optional, Any
from langchain_openai import ChatOpenAI
from langchain.agents import create_react_agent, AgentExecutor
from agent_os.tools.registry import ToolRegistry
import structlog

logger = structlog.get_logger()


class ChatAgent:
    """Temporary agent for tool-using chat queries."""

    def __init__(
        self,
        tools: List[str],
        tool_registry: ToolRegistry,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        max_iterations: int = 10,
        timeout: int = 30
    ):
        self.tool_names = tools
        self.model = model
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.timeout = timeout

        self.tools = tool_registry.to_langchain(tools)
        self.llm = ChatOpenAI(model=model, temperature=temperature)
        self.executor = self._build_executor()

        logger.info(
            "chat_agent_initialized",
            tools=tools,
            model=model,
            max_iterations=max_iterations
        )

    def _build_executor(self) -> AgentExecutor:
        """Build AgentExecutor with proper configuration."""
        from langchain_core.prompts import PromptTemplate

        template = """You are a helpful AI assistant with access to tools.

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought:{agent_scratchpad}"""

        prompt = PromptTemplate.from_template(template)

        agent = create_react_agent(self.llm, self.tools, prompt)

        return AgentExecutor(
            agent=agent,
            tools=self.tools,
            max_iterations=self.max_iterations,
            max_execution_time=self.timeout,
            verbose=False,
            handle_parsing_errors=True,
            return_intermediate_steps=True  # Return tool outputs for schema extraction
        )

    def run(
        self,
        query: str,
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """Execute query with tools.

        Returns:
            Dict with 'output' (str) and 'intermediate_steps' (list of tuples)
        """
        try:
            logger.info(
                "chat_agent_executing",
                query=query[:100],
                tools=self.tool_names
            )

            full_query = query
            if chat_history and len(chat_history) > 0:
                history_text = "\n".join([
                    f"{msg['role'].title()}: {msg['content']}"
                    for msg in chat_history[-5:]
                ])
                full_query = f"Context:\n{history_text}\n\nCurrent Query: {query}"

            result = self.executor.invoke({"input": full_query})

            output = result.get("output", "")
            intermediate_steps = result.get("intermediate_steps", [])

            logger.info(
                "chat_agent_success",
                output_length=len(output),
                tools=self.tool_names,
                tool_calls=len(intermediate_steps)
            )

            return {
                "output": output,
                "intermediate_steps": intermediate_steps
            }

        except TimeoutError as e:
            logger.error("chat_agent_timeout", query=query, tools=self.tool_names)
            return {
                "output": "Tool execution timed out. Try a simpler query or check if files exist.",
                "intermediate_steps": []
            }

        except Exception as e:
            logger.error(
                "chat_agent_execution_failed",
                query=query,
                error=str(e),
                error_type=type(e).__name__,
                tools=self.tool_names
            )
            return {
                "output": self._format_error(e),
                "intermediate_steps": []
            }

    async def arun(
        self,
        query: str,
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Async execution."""
        try:
            full_query = query
            if chat_history and len(chat_history) > 0:
                history_text = "\n".join([
                    f"{msg['role'].title()}: {msg['content']}"
                    for msg in chat_history[-5:]
                ])
                full_query = f"Context:\n{history_text}\n\nCurrent Query: {query}"

            result = await self.executor.ainvoke({"input": full_query})

            return result.get("output", "")

        except Exception as e:
            logger.error(
                "chat_agent_async_execution_failed",
                query=query,
                error=str(e),
                tools=self.tool_names
            )
            return self._format_error(e)

    @staticmethod
    def _format_error(error: Exception) -> str:
        """Format error message for user."""
        error_type = type(error).__name__

        if "timeout" in str(error).lower():
            return "Tool execution timed out. Try a simpler query or check the file path."

        if "not found" in str(error).lower():
            return f"Resource not found: {error}. Please verify the path or name."

        if "permission" in str(error).lower():
            return f"Permission denied: {error}. Check file access rights."

        return f"Tool execution failed ({error_type}). Please rephrase your request."
