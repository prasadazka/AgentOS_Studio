"""
Intent Parser for Natural Language Understanding

Parses user input into structured actions using LLM-based classification.
Zero ambiguity through confidence scoring and validation.
"""

import json
from typing import Dict, Any, Optional, List
from enum import Enum
from pydantic import BaseModel, Field, field_validator

from agent_os.cli.utils.tool_discovery import fuzzy_search_tools


class IntentAction(str, Enum):
    """Supported intent actions"""

    CREATE_AGENT = "create_agent"
    CREATE_TOOL = "create_tool"
    CREATE_WORKFLOW = "create_workflow"
    RUN_AGENT = "run_agent"
    EXPORT_AGENT = "export_agent"
    LIST_AGENTS = "list_agents"
    LIST_TOOLS = "list_tools"
    LIST_WORKFLOWS = "list_workflows"
    SHOW_INFO = "show_info"
    MODIFY_AGENT = "modify_agent"
    DELETE_AGENT = "delete_agent"
    ACTIVATE_AGENT = "activate_agent"
    DEACTIVATE_AGENT = "deactivate_agent"
    DEPLOY_APP = "deploy_app"
    ANALYZE_PROJECT = "analyze_project"
    HELP = "help"
    GENERAL_QUERY = "general_query"
    CLARIFY = "clarify"


class Intent(BaseModel):
    """Structured intent parsed from user input"""

    action: IntentAction = Field(..., description="The action to perform")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0-1")
    clarification_needed: bool = Field(False, description="Whether clarification is needed")
    clarification_question: Optional[str] = Field(None, description="Question to ask user")
    reasoning: str = Field(..., description="Why this intent was chosen")

    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence is between 0 and 1"""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class IntentParser:
    """
    Parse natural language to structured intents using LLM.

    Features:
    - Structured output with Pydantic validation
    - Confidence scoring (threshold: 0.7)
    - Fuzzy tool name validation
    - Few-shot examples for accuracy
    - Returns clarification requests for low confidence
    """

    CONFIDENCE_THRESHOLD = 0.6

    SYSTEM_PROMPT = """You are an intent parser for an AI agent creation system.

Your job is to parse user messages into structured actions with high accuracy.

Available actions:
- create_agent: Create a new AI agent
- create_tool: Create a custom tool
- create_workflow: Create a multi-agent workflow
- run_agent: Execute an existing agent
- activate_agent: Activate agent mode (persistent session with file discovery)
- deactivate_agent: Exit agent mode and return to normal
- deploy_app: Deploy application to GCP (Cloud Run, App Engine, etc.)
- analyze_project: Analyze project tech stack without deploying
- list_agents: List all available agents
- list_tools: List all available tools
- list_workflows: List all workflows
- show_info: Show details about an agent/tool/workflow
- modify_agent: Modify an existing agent
- delete_agent: Delete an agent
- help: Show help information
- general_query: Answer general questions about AI, ML, LangChain, agents, etc.
- clarify: Request clarification from user

Return JSON with:
{
    "action": "<action_name>",
    "parameters": {<extracted parameters>},
    "confidence": <0.0-1.0>,
    "clarification_needed": <true/false>,
    "clarification_question": "<question if needed>",
    "reasoning": "<why you chose this>"
}

Parameter extraction guidelines:
- create_agent: {description, suggested_name, tools[], model, system_prompt, temperature}
  - description: ALWAYS include the full user request/description
  - tools: OPTIONAL - only if explicitly mentioned, otherwise leave empty for auto-suggestion
- create_tool: {name, description, category}
- create_workflow: {name, agents[], type}
- run_agent: {agent_name, query}
- activate_agent: {agent_name}
  - agent_name: Name of agent to activate (DataAnalyst, Developer, Researcher, etc.)
- deactivate_agent: {} (no parameters needed)
- show_info: {name, type: 'agent'|'tool'|'workflow'}
- modify_agent: {name, changes: {}}
- delete_agent: {resource_name, resource_type: 'agent'|'tool'|'workflow'}
  - resource_name: The name of the agent/tool/workflow to delete
  - resource_type: Defaults to 'agent' if not specified
- export_agent: {agent_name, as_class: boolean, output_path: optional}
- deploy_app: {project_path, target, region, push_to_git, env_file}
  - project_path: Path to project (default: current directory ".")
  - target: Deployment target (cloud_run, app_engine, cloud_functions)
  - region: GCP region (default: us-central1)
  - push_to_git: Whether to commit and push first (default: true)
  - env_file: Path to .env file for secrets (default: .env)
- analyze_project: {project_path}
  - project_path: Path to analyze (default: current directory ".")

Examples:

User: "Create a research agent that uses Wikipedia and ArXiv"
{
    "action": "create_agent",
    "parameters": {
        "description": "research agent that uses Wikipedia and ArXiv",
        "tools": ["wikipedia_search", "arxiv_search"],
        "suggested_name": "ResearchAgent"
    },
    "confidence": 0.95,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Clear request to create agent with specific tools"
}

User: "can you build a simple agent that can answer my queries just like chatgpt"
{
    "action": "create_agent",
    "parameters": {
        "description": "simple agent that can answer queries like chatgpt",
        "suggested_name": "ChatAgent"
    },
    "confidence": 0.9,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Request for general conversational agent, tools will be auto-suggested"
}

User: "Run the researcher to find papers on transformers"
{
    "action": "run_agent",
    "parameters": {
        "agent_name": "researcher",
        "query": "find papers on transformers"
    },
    "confidence": 0.9,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Clear execution request with agent name and query"
}

User: "Show me stuff"
{
    "action": "clarify",
    "parameters": {},
    "confidence": 0.3,
    "clarification_needed": true,
    "clarification_question": "What would you like me to show? (agents, tools, workflows, or info about a specific item)",
    "reasoning": "Ambiguous request, need to know what to show"
}

User: "List all my agents"
{
    "action": "list_agents",
    "parameters": {},
    "confidence": 1.0,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Clear request to list agents"
}

User: "delete agent HealthcareAssistant"
{
    "action": "delete_agent",
    "parameters": {
        "resource_name": "HealthcareAssistant",
        "resource_type": "agent"
    },
    "confidence": 0.95,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Clear request to delete a specific agent"
}

User: "remove the ChatAgent"
{
    "action": "delete_agent",
    "parameters": {
        "resource_name": "ChatAgent",
        "resource_type": "agent"
    },
    "confidence": 0.9,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Delete request using 'remove' synonym"
}

User: "What is LangChain?"
{
    "action": "general_query",
    "parameters": {
        "query": "What is LangChain?"
    },
    "confidence": 1.0,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "General knowledge question, not agent management"
}

User: "Explain how agents work"
{
    "action": "general_query",
    "parameters": {
        "query": "Explain how agents work"
    },
    "confidence": 0.95,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Educational question about AI concepts"
}

User: "give me the langchain website link"
{
    "action": "general_query",
    "parameters": {
        "query": "give me the langchain website link"
    },
    "confidence": 1.0,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Request for information/link, answer directly"
}

User: "what is the difference between X and Y"
{
    "action": "general_query",
    "parameters": {
        "query": "what is the difference between X and Y"
    },
    "confidence": 1.0,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Comparison question, answer directly"
}

User: "Search Wikipedia for quantum computing"
{
    "action": "general_query",
    "parameters": {
        "query": "Search Wikipedia for quantum computing"
    },
    "confidence": 1.0,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Tool-using query without agent name - chat will auto-select tools"
}

User: "Find papers about transformers on ArXiv"
{
    "action": "general_query",
    "parameters": {
        "query": "Find papers about transformers on ArXiv"
    },
    "confidence": 1.0,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Research query without agent name - chat will use ArXiv tools"
}

User: "Read file.csv and summarize"
{
    "action": "general_query",
    "parameters": {
        "query": "Read file.csv and summarize"
    },
    "confidence": 1.0,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "File operation request - chat will auto-select file tools"
}

User: "Run MyResearchAgent to find papers on AI"
{
    "action": "run_agent",
    "parameters": {
        "agent_name": "MyResearchAgent",
        "query": "find papers on AI"
    },
    "confidence": 0.95,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Explicit agent execution - user named a specific agent"
}

User: "activate DataAnalyst"
{
    "action": "activate_agent",
    "parameters": {
        "agent_name": "DataAnalyst"
    },
    "confidence": 0.95,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Clear request to activate agent mode"
}

User: "enter developer mode"
{
    "action": "activate_agent",
    "parameters": {
        "agent_name": "Developer"
    },
    "confidence": 0.9,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Activation request using 'enter mode' synonym"
}

User: "switch to researcher agent"
{
    "action": "activate_agent",
    "parameters": {
        "agent_name": "Researcher"
    },
    "confidence": 0.9,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Switch/activate agent mode request"
}

User: "deactivate agent"
{
    "action": "deactivate_agent",
    "parameters": {},
    "confidence": 0.95,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Clear request to exit agent mode"
}

User: "exit agent mode"
{
    "action": "deactivate_agent",
    "parameters": {},
    "confidence": 0.95,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Exit agent mode request"
}

User: "deploy my app to Cloud Run"
{
    "action": "deploy_app",
    "parameters": {
        "project_path": ".",
        "target": "cloud_run",
        "region": "us-central1"
    },
    "confidence": 0.95,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Clear deployment request to Cloud Run"
}

User: "deploy to GCP"
{
    "action": "deploy_app",
    "parameters": {
        "project_path": ".",
        "target": "cloud_run"
    },
    "confidence": 0.9,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Deployment request - defaulting to Cloud Run"
}

User: "push my code and deploy it"
{
    "action": "deploy_app",
    "parameters": {
        "project_path": ".",
        "push_to_git": true
    },
    "confidence": 0.9,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Deploy with git push request"
}

User: "analyze this project"
{
    "action": "analyze_project",
    "parameters": {
        "project_path": "."
    },
    "confidence": 0.95,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Project analysis request without deployment"
}

User: "what tech stack is this project using"
{
    "action": "analyze_project",
    "parameters": {
        "project_path": "."
    },
    "confidence": 0.9,
    "clarification_needed": false,
    "clarification_question": null,
    "reasoning": "Tech stack analysis request"
}

CRITICAL RULES:
- Use 'general_query' for:
  * Questions (what/how/why/when/where)
  * Requests for information/links, explanations, comparisons
  * Tool-using queries WITHOUT agent names (Search Wikipedia, Find papers, Read file, etc.)
  * File operations (read, analyze, summarize files)
- Use 'run_agent' ONLY when:
  * User explicitly says "Run [AgentName]" or "Execute [AgentName]"
  * A specific agent name is mentioned for execution
- Use 'activate_agent' when:
  * User says "activate [AgentName]", "enter [AgentName] mode", "switch to [AgentName]"
  * User wants to enter persistent agent mode for data analysis, development, research
- Use 'deactivate_agent' when:
  * User says "deactivate", "exit agent mode", "stop agent", "return to normal"
- Use 'deploy_app' when:
  * User says "deploy", "push and deploy", "deploy to Cloud Run/GCP/cloud"
  * User wants to deploy their application to cloud infrastructure
- Use 'analyze_project' when:
  * User says "analyze project", "what tech stack", "scan dependencies"
  * User wants project analysis WITHOUT deployment
- Use agent management actions ONLY when user explicitly wants to CREATE, LIST, MODIFY, DELETE agents/tools/workflows IN THIS SYSTEM
- DON'T ask for clarification on obvious questions - just answer with general_query
- Confidence < 0.6 = clarify, >= 0.6 = proceed"""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
        tool_registry=None,
    ):
        """
        Initialize intent parser.

        Args:
            model: LLM model to use
            temperature: Temperature for LLM (0 = deterministic)
            tool_registry: Optional ToolRegistry for validating tool names
        """
        self.model = model
        self.temperature = temperature
        self.tool_registry = tool_registry
        self._llm = None  # Lazy-loaded

    def _get_llm(self):
        """Lazy-load LLM only when needed"""
        if self._llm is None:
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(model=self.model, temperature=self.temperature)
        return self._llm

    def parse(self, user_input: str) -> Intent:
        """
        Parse user input into structured intent.

        Args:
            user_input: Natural language input from user

        Returns:
            Structured Intent object

        Raises:
            ValueError: If LLM response is invalid
            RuntimeError: If LLM call fails
        """
        if not user_input or not user_input.strip():
            return Intent(
                action=IntentAction.CLARIFY,
                parameters={},
                confidence=0.0,
                clarification_needed=True,
                clarification_question="I didn't receive any input. How can I help you?",
                reasoning="Empty input received",
            )

        try:
            # Lazy-load LangChain dependencies
            from langchain_core.messages import SystemMessage, HumanMessage

            # Call LLM
            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=user_input),
            ]

            response = self._get_llm().invoke(messages)
            response_text = response.content.strip()

            # Parse JSON (handle code blocks)
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            data = json.loads(response_text)

            # Validate and create Intent
            intent = Intent(**data)

            # Post-process: Validate tool names if registry available
            if self.tool_registry and intent.action == IntentAction.CREATE_AGENT:
                intent = self._validate_tools(intent)

            # Post-process: Check confidence threshold
            if intent.confidence < self.CONFIDENCE_THRESHOLD and not intent.clarification_needed:
                intent.clarification_needed = True
                if not intent.clarification_question:
                    intent.clarification_question = (
                        f"I'm not confident about this request (confidence: {intent.confidence:.1%}). "
                        f"Could you rephrase or provide more details?"
                    )

            return intent

        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}")
        except Exception as e:
            raise RuntimeError(f"Intent parsing failed: {e}")

    def _validate_tools(self, intent: Intent) -> Intent:
        """
        Validate tool names in intent parameters using fuzzy search.

        Args:
            intent: Intent to validate

        Returns:
            Updated intent with validated/corrected tool names
        """
        if "tools" not in intent.parameters:
            return intent

        tools = intent.parameters["tools"]
        if not isinstance(tools, list):
            return intent

        available_tools = self.tool_registry.list_all()
        validated_tools = []
        suggestions = []

        for tool in tools:
            if tool in available_tools:
                validated_tools.append(tool)
            else:
                # Fuzzy search for similar tools
                matches = fuzzy_search_tools(tool, available_tools, threshold=0.6, max_results=1)

                if matches:
                    best_match, score = matches[0]
                    validated_tools.append(best_match)
                    suggestions.append(f"'{tool}' → '{best_match}' (similarity: {score:.1%})")
                else:
                    # Tool not found, need clarification
                    intent.clarification_needed = True
                    intent.clarification_question = (
                        f"Tool '{tool}' not found. Available tools: {', '.join(available_tools[:10])}. "
                        f"Use 'agent_os list tools' to see all tools."
                    )
                    intent.confidence = min(intent.confidence, 0.5)
                    return intent

        # Update intent with validated tools
        intent.parameters["tools"] = validated_tools

        # Add note about corrections if any
        if suggestions:
            intent.parameters["_tool_corrections"] = suggestions

        return intent

    def parse_batch(self, user_inputs: List[str]) -> List[Intent]:
        """
        Parse multiple inputs (useful for testing).

        Args:
            user_inputs: List of user input strings

        Returns:
            List of parsed intents
        """
        return [self.parse(input_text) for input_text in user_inputs]


def create_intent_parser(tool_registry=None) -> IntentParser:
    """
    Factory function to create intent parser.

    Args:
        tool_registry: Optional ToolRegistry instance

    Returns:
        Configured IntentParser
    """
    return IntentParser(
        model="gpt-4o-mini",
        temperature=0.0,
        tool_registry=tool_registry,
    )
