"""
Smart tool selection for chat queries.

Analyzes user queries to determine if tools are needed and selects appropriate tools.
Uses LLM-based classification with caching for performance.
"""

from typing import List, Dict, Optional
from enum import Enum
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
import json
from functools import lru_cache


class QueryType(str, Enum):
    SIMPLE_QA = "simple_qa"
    RESEARCH = "research"
    FILE_OPERATION = "file_operation"
    DATA_ANALYSIS = "data_analysis"
    WEB_REQUEST = "web_request"
    CODE_OPERATION = "code_operation"
    SECURITY_SCAN = "security_scan"


class ToolSelection(BaseModel):
    requires_tools: bool
    query_type: QueryType
    selected_tools: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: Optional[str] = None


class ToolSelector:
    """Analyzes queries and selects appropriate tools."""

    def __init__(
        self,
        tool_registry=None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0
    ):
        self.llm = ChatOpenAI(model=model, temperature=temperature)
        self._cache: Dict[str, ToolSelection] = {}
        self.tool_registry = tool_registry
        self._available_tools: List[str] = []

        if tool_registry:
            self._available_tools = tool_registry.list_all()

    def analyze(self, query: str, file_path: Optional[str] = None) -> ToolSelection:
        """Analyze query and select tools."""
        import structlog
        logger = structlog.get_logger()

        cache_key = self._get_cache_key(query, file_path)

        if cache_key in self._cache:
            cached_result = self._cache[cache_key]
            logger.debug(
                "tool_selector_cache_hit",
                cache_key=cache_key[:80],
                requires_tools=cached_result.requires_tools,
                confidence=cached_result.confidence,
                selected_tools=cached_result.selected_tools
            )
            return cached_result

        if file_path:
            selection = self._analyze_file_operation(query, file_path)
            logger.debug(
                "tool_selector_fast_path",
                query=query[:80],
                file_path=file_path,
                requires_tools=selection.requires_tools,
                confidence=selection.confidence,
                selected_tools=selection.selected_tools,
                reasoning=selection.reasoning
            )
        else:
            selection = self._analyze_query(query)
            logger.debug(
                "tool_selector_llm_analysis",
                query=query[:80],
                requires_tools=selection.requires_tools,
                confidence=selection.confidence,
                selected_tools=selection.selected_tools,
                reasoning=selection.reasoning
            )

        self._cache[cache_key] = selection
        return selection

    def _analyze_query(self, query: str) -> ToolSelection:
        """Use LLM to classify query and select tools."""
        system_prompt = self._build_system_prompt()

        response = self.llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=query)
        ])

        try:
            content = response.content.strip()

            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            result = json.loads(content)

            if "selected_tools" in result and result["selected_tools"]:
                valid_tools = [
                    t for t in result["selected_tools"]
                    if t in self._available_tools
                ]
                result["selected_tools"] = valid_tools

            return ToolSelection(**result)

        except (json.JSONDecodeError, ValueError, Exception) as e:
            return ToolSelection(
                requires_tools=False,
                query_type=QueryType.SIMPLE_QA,
                confidence=1.0,
                reasoning=f"Failed to parse tool selection: {str(e)[:50]}"
            )

    def _analyze_file_operation(self, query: str, file_path: str) -> ToolSelection:
        """Fast path for file operations."""
        from pathlib import Path

        ext = Path(file_path).suffix.lower()

        ext_to_tool_pattern = {
            ".pdf": "pdf",
            ".csv": "csv",
            ".json": "json",
            ".txt": "file_read",
            ".md": "file_read",
            ".py": "file_read",
        }

        pattern = ext_to_tool_pattern.get(ext, "file_read")

        tools = [t for t in self._available_tools if pattern in t.lower()]
        if not tools:
            tools = ["file_read"] if "file_read" in self._available_tools else []

        return ToolSelection(
            requires_tools=True,
            query_type=QueryType.FILE_OPERATION,
            selected_tools=tools[:1],
            confidence=1.0,
            reasoning=f"File operation on {ext} file"
        )

    def _build_system_prompt(self) -> str:
        tools_list = "\n".join([f"  - {tool}" for tool in self._available_tools]) if self._available_tools else "  (No tools registered)"

        return f"""Analyze the user query and determine if tools are needed.

Return JSON with this structure:
{{
    "requires_tools": true/false,
    "query_type": "simple_qa|research|file_operation|data_analysis|web_request|code_operation|security_scan",
    "selected_tools": ["tool1", "tool2"],
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}

Available Tools:
{tools_list}

Query Type Guidelines:
- research: Wikipedia searches, ArXiv papers, academic citations
- file_operation: Read, write, list files/directories, PDF extraction
- data_analysis: CSV, JSON, DataFrame operations
- web_request: Web scraping, HTTP requests
- code_operation: Git commands, database queries, SQL execution
- security_scan: PII detection, injection detection, content moderation
- simple_qa: General knowledge questions (no tools needed)

Tool Selection Examples:
- "Search Wikipedia for X" → ["wikipedia_search"]
- "Find papers on Y" → ["arxiv_search"]
- "Read file.csv and analyze" → ["csv_process"]
- "Analyze data.json" → ["json_process"]
- "Check git status" → ["git_status"]
- "Scan text for PII" → ["pii_detect"]

Simple Q&A (no tools):
- "What is X?" - general knowledge
- "How does Y work?" - explanations
- "Explain Z" - concepts

Confidence Scoring:
- 1.0: Explicit tool request (e.g., "search Wikipedia")
- 0.8-0.9: Implied tool need (e.g., "what's on Wikipedia about X")
- 0.5-0.7: Ambiguous (could use tools or not)
- <0.5: Likely doesn't need tools

If confidence < 0.7, set requires_tools=false."""

    @staticmethod
    def _get_cache_key(query: str, file_path: Optional[str]) -> str:
        """Generate cache key for query."""
        key = query.lower().strip()[:100]
        if file_path:
            key += f"|{file_path}"
        return key

    def clear_cache(self):
        """Clear the analysis cache."""
        self._cache.clear()
