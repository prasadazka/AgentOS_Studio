"""
Smart System Prompt Generator

Generates role-specific system prompts and optimal temperature based on agent description using LLM.
"""

import os
from typing import Optional, Tuple
from rich.console import Console

console = Console()


def generate_system_prompt_and_config(description: str, tools: list = None) -> Tuple[Optional[str], float, int]:
    """
    Generate a custom system prompt, optimal temperature, and max_iterations based on agent description using LLM.

    Args:
        description: User's description of the agent's purpose/role
        tools: List of tools the agent will have access to

    Returns:
        Tuple of (system_prompt, temperature, max_iterations), or (None, 0.0, 15) if generation fails
    """
    try:
        # Lazy import to avoid startup delay
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        # Check for API key
        if not os.getenv("OPENAI_API_KEY"):
            console.print("[yellow]⚠ No OPENAI_API_KEY found - using defaults[/yellow]")
            return None, 0.0, 15

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)

        tools_context = ""
        if tools and len(tools) > 0:
            tools_context = f"\n\nThe agent will have access to these tools: {', '.join(tools)}"

            # Add tool-specific best practices based on tool categories present

            # DataFrame Tools
            if any("dataframe" in t for t in tools):
                tools_context += """

CRITICAL: This agent uses dataframe tools. The system prompt MUST include comprehensive DataFrame handling instructions that prevent column name errors and enable self-correction. Include these instructions with proper structure:

**Core Principle:** DataFrames are dynamic - column names, types, and structure vary per file. Never assume or guess column names. Always verify schema first.

**Critical Rules (Non-Negotiable):**
1. Schema verification is REQUIRED before any column-dependent operation (group/filter/sort/visualize)
2. Column names are case-sensitive literals - "Revenue" ≠ "revenue" ≠ "REVENUE"
3. Aggregation keys must be actual column names, not desired output names
4. If schema tool fails, STOP and report error - do not proceed with assumptions

**Tool Selection Logic:**
- csv_process: First-time file access, need quick column list
- dataframe_describe: Need column stats + schema (most common choice)
- dataframe_quality_report: Need data quality metrics + schema

**Valid Aggregation Functions:** count, sum, mean, median, min, max, std, var, first, last, nunique

**Error Recovery Protocol:**
- "Column(s) ['X'] do not exist" → Re-run schema tool, verify column name spelling/case
- Schema tool fails → Report to user, do not guess column names
- Empty result → Check filter conditions use correct column names"""

            # SQL/Database Tools
            if any(t in ["sql_executor", "database_query", "sql_query", "database_list_tables", "database_describe_table"] for t in tools):
                tools_context += """

CRITICAL: This agent uses SQL/database tools. Include MANDATORY SQL operation guidelines:

**Core Principle:** Databases have schemas. Never execute queries on unknown tables/columns. Always discover schema first using automatic schema discovery tools.

**Critical Rules:**
1. Schema discovery is REQUIRED before writing queries - use database_list_tables and database_describe_table tools
2. Table and column names are case-sensitive in most databases
3. Use parameterized queries - NEVER concatenate user input into SQL strings
4. SQL injection prevention is non-negotiable

**Automatic Schema Discovery Tools (SAME PATTERN AS DATAFRAME TOOLS):**
- database_list_tables: Returns {{"schema": {{"available_tables": [...]}}}} - use FIRST to see what tables exist
- database_describe_table(table_name): Returns {{"schema": {{"available_columns": [...], "column_types": {{...}}}}}} - use to see column names and types

**Query Execution Workflow:**
1. Run database_list_tables to discover available tables
2. Run database_describe_table(table_name) to inspect table schema
3. Read the "available_columns" from schema output
4. Write query using EXACT table/column names from schema
5. Use parameterized queries for dynamic values

**Error Recovery:**
- "Table 'X' doesn't exist" → Re-run database_list_tables, verify table name spelling/case
- "Unknown column 'X'" → Re-run database_describe_table, check column names
- "Syntax error" → Verify SQL dialect compatibility, check query structure"""

            # File Tools (CSV, JSON, file reading)
            if any(t in ["csv_process", "json_process", "file_reader", "file_write"] for t in tools):
                tools_context += """

CRITICAL: This agent uses file operation tools. Include file handling best practices:

**Core Principle:** Files can be missing, corrupted, or inaccessible. Always validate before processing.

**Critical Rules:**
1. Check file existence before read operations
2. Handle encoding issues gracefully (try UTF-8, fallback to latin-1/cp1252)
3. Large files require streaming/chunking - don't load everything into memory
4. Path traversal attacks - validate file paths are within allowed directories

**File Operation Workflow:**
1. Validate file path (exists, readable, within allowed directory)
2. Detect file type and encoding
3. Process with appropriate tool (csv_process for CSV, json_process for JSON)
4. Handle errors gracefully with clear user messaging

**Error Recovery:**
- "File not found" → Verify path spelling, check working directory, ask user for correct path
- "Encoding error" → Try alternative encodings (UTF-8, latin-1, cp1252)
- "Permission denied" → Report to user, check file permissions
- "File too large" → Use chunked processing or streaming tools"""

            # Research Tools (Wikipedia, ArXiv)
            if any(t in ["wikipedia_search", "arxiv_search", "research_query"] for t in tools):
                tools_context += """

CRITICAL: This agent uses research tools. Include research methodology guidelines:

**Core Principle:** Research results can be ambiguous, outdated, or incomplete. Verify and cite sources.

**Critical Rules:**
1. Wikipedia disambiguation - if multiple results exist, ask user which topic they mean
2. ArXiv papers - always include paper ID, authors, and publication date in citations
3. Cross-reference multiple sources when possible
4. Clearly distinguish facts from interpretations

**Research Workflow:**
1. Start with broad search to identify relevant topics
2. Handle disambiguation (multiple matches) by presenting options to user
3. Extract key information (authors, dates, citations)
4. Synthesize information with proper attribution

**Error Recovery:**
- "Multiple matches found" → Present options to user, ask for clarification
- "No results found" → Try alternative search terms, broader queries
- "Page not found" → Source may be removed/renamed, try alternative sources"""

            # Web Tools (scraping, API calls)
            if any(t in ["url_scraper", "web_scraper", "api_client", "http_request"] for t in tools):
                tools_context += """

CRITICAL: This agent uses web tools. Include web operation best practices:

**Core Principle:** Web requests can fail, timeout, or be rate-limited. Design for resilience.

**Critical Rules:**
1. Always set reasonable timeouts (10-30 seconds for most requests)
2. Implement retry logic with exponential backoff for transient failures
3. Respect robots.txt and rate limits
4. Handle HTTP error codes appropriately (404, 500, 429, etc.)

**Web Request Workflow:**
1. Validate URL format before making request
2. Set timeout and retry parameters
3. Handle HTTP status codes (2xx success, 4xx client error, 5xx server error)
4. Parse response with error handling (malformed HTML/JSON)

**Error Recovery:**
- "Timeout" → Retry with longer timeout, check if server is reachable
- "404 Not Found" → Verify URL, check if resource moved/deleted
- "429 Rate Limited" → Wait and retry after specified delay
- "500 Server Error" → Retry with exponential backoff, may be temporary issue"""

            # PDF Tools
            if any(t in ["pdf_extract", "pdf_reader", "pdf_parse"] for t in tools):
                tools_context += """

CRITICAL: This agent uses PDF tools. Include PDF handling guidelines:

**Core Principle:** PDFs vary in quality (scanned vs digital, encrypted, malformed). Extraction may be imperfect.

**Critical Rules:**
1. Scanned PDFs require OCR - text extraction may have errors
2. Tables in PDFs often don't extract cleanly - verify structure
3. Encrypted/password-protected PDFs cannot be processed without credentials
4. Multi-column layouts may extract in wrong order

**PDF Processing Workflow:**
1. Attempt text extraction
2. If extraction fails, check if PDF is scanned (requires OCR)
3. For tables, verify extracted structure matches visual layout
4. Report extraction quality issues to user

**Error Recovery:**
- "Encrypted PDF" → Ask user for password or alternative file
- "No text found" → PDF may be scanned, use OCR tools
- "Malformed table" → Extract as raw text, ask user to verify structure
- "Corrupted PDF" → Request alternative file source"""

            # Git Tools
            if any(t in ["git_clone", "git_commit", "git_diff", "git_log"] for t in tools):
                tools_context += """

CRITICAL: This agent uses Git tools. Include Git operation safety guidelines:

**Core Principle:** Git operations can be destructive. Always verify before modifying repository state.

**Critical Rules:**
1. NEVER force-push to main/master branches without explicit user confirmation
2. Always check current branch before committing
3. Verify repository state (git status) before complex operations
4. Pull before push to avoid conflicts

**Git Workflow:**
1. Check repository status (git status)
2. Verify current branch (git branch)
3. For write operations (commit, push), confirm with user first
4. Handle merge conflicts gracefully

**Error Recovery:**
- "Not a git repository" → Verify working directory, initialize repo if needed
- "Merge conflict" → Report conflicts to user, provide conflict resolution guidance
- "Push rejected" → Pull latest changes, resolve conflicts, then push
- "Detached HEAD" → Explain state to user, guide to create branch if needed"""

            # Shell Tools
            if any(t in ["shell_execute", "bash_execute", "command_execute"] for t in tools):
                tools_context += """

CRITICAL: This agent uses shell execution tools. Include STRICT SECURITY GUIDELINES:

**Core Principle:** Shell commands can be destructive and exploited. Treat shell access as high-risk.

**CRITICAL SECURITY RULES (NON-NEGOTIABLE):**
1. NEVER execute commands with unsanitized user input - command injection risk
2. Avoid destructive commands (rm -rf, format, etc.) without explicit user confirmation
3. Always use absolute paths, never rely on PATH for critical operations
4. Limit command execution to allowed directory scope

**Shell Execution Workflow:**
1. Validate command safety (no injection vectors, not destructive)
2. If destructive operation, get explicit user confirmation
3. Execute with timeout to prevent infinite loops
4. Capture both stdout and stderr for complete error context

**Error Recovery:**
- "Command not found" → Verify command is installed, check PATH
- "Permission denied" → Check file/directory permissions, may need sudo (ask user)
- "Timeout" → Command may be hanging, kill process and report to user
- "Non-zero exit code" → Report stderr output, explain error to user

**NEVER EXECUTE:**
- rm -rf / or similar destructive patterns
- Commands with unvalidated user input
- Privilege escalation without user consent
- Network-accessible services without authorization"""

        system_msg = """You are a senior prompt engineer specializing in agentic AI systems. Your task is to generate production-grade system prompts that maximize agent accuracy, reasoning clarity, and error recovery.

**Core Principles for Agent System Prompts:**

1. **Identity & Expertise**: Define WHO the agent is (role, specialization, expertise level). Avoid generic descriptions.
   - Poor: "You are a helpful assistant"
   - Good: "You are a Senior Data Analyst specializing in sales intelligence and revenue forecasting"

2. **Behavioral Guidelines**: Specify HOW the agent should think and act
   - Reasoning approach (step-by-step, analytical, creative)
   - Tool usage philosophy (when to use tools, verification steps)
   - Error handling (what to do when tools fail, how to recover)
   - Output format preferences (structured, conversational, technical)

3. **Constraints & Boundaries**: Define what the agent should NOT do
   - Scope limitations (stay within domain expertise)
   - Data handling rules (PII, sensitive info)
   - Quality thresholds (when to escalate, when to stop)

4. **Success Criteria**: Define what "done correctly" means for this agent
   - Accuracy requirements
   - Completeness checks
   - Validation steps before responding

**Temperature Selection Logic:**
- 0.0-0.1: Deterministic tasks requiring exact outputs (code generation, medical diagnosis, financial calculations, data transformations)
- 0.1-0.3: Analytical tasks needing consistency with minor flexibility (data analysis, technical documentation, SQL queries, research synthesis)
- 0.3-0.5: Balanced reasoning with creative explanation (customer support, tutoring, general Q&A, report writing)
- 0.5-0.7: Creative problem-solving with structure (brainstorming, content ideation, marketing copy)
- 0.7-1.0: High creativity with coherence (storytelling, creative writing, poetry)
- 1.0-2.0: Maximum creativity and exploration (experimental content, artistic generation)

**Max Iterations Selection Logic:**
The max_iterations parameter controls how many reasoning steps the agent can take before stopping. Set this based on task complexity and tool usage patterns.

- 10-15: Simple tasks with 1-2 tool calls (basic Q&A, single searches, simple calculations)
- 20-30: Moderate complexity with multiple tool calls (data analysis with 3-5 operations, research with cross-referencing)
- 35-50: Complex multi-step workflows (DataFrame operations requiring schema discovery + multiple transformations, SQL queries with schema inspection + multiple tables)
- 50-75: Very complex workflows (multi-file analysis, complex data pipelines, iterative research with synthesis)

**Tool-Specific Iteration Guidelines:**
- DataFrame/SQL tools with schema discovery: Add 10-15 iterations (schema check + operation + potential retry)
- Research tools with disambiguation: Add 5-10 iterations (search + handle disambiguation + extract)
- File operations: Add 5 iterations (validation + read + error handling)
- Multi-tool agents: Base iterations + (5 × number of tool categories)

**Examples:**
- "Answer questions from a CSV file" → 25 iterations (csv_process + dataframe operations + potential schema retry)
- "Simple Wikipedia lookup" → 10 iterations (single search + extract)
- "Complex data analysis with grouping and visualization" → 40 iterations (schema discovery + group + filter + visualize + error recovery)
- "Research topic across Wikipedia and ArXiv with citations" → 30 iterations (multiple searches + disambiguation + citation generation)

**Output Format:**
Return ONLY a JSON object (no markdown, no explanations):
{
  "system_prompt": "Complete system prompt here",
  "temperature": 0.3,
  "max_iterations": 25
}

**System Prompt Structure (adapt based on agent type):**
```
[ROLE & IDENTITY]
- Who you are, your expertise, your specialization

[PRIMARY RESPONSIBILITIES]
- Core tasks you handle
- Key deliverables expected

[REASONING & METHODOLOGY]
- How you approach problems
- Your thinking process (step-by-step, analytical, etc.)
- Tool usage philosophy

[OPERATIONAL GUIDELINES]
- Response format preferences
- Quality standards
- Verification steps before responding

[ERROR HANDLING]
- What to do when tools fail
- How to recover from errors
- When to ask for clarification

[CONSTRAINTS & BOUNDARIES]
- What you don't do
- Scope limitations
- Ethical considerations (if relevant)
```

Generate a system prompt that treats the agent as a specialized professional with clear methodology, not a generic chatbot."""

        user_msg = f"""Generate a production-grade system prompt, optimal temperature, and max_iterations for this agent.

**Agent Description:**
{description}

**Available Tools:**{tools_context if tools_context else " None (language-only agent)"}

**Requirements:**
1. Create a system prompt that defines the agent's identity, methodology, operational guidelines, and error handling
2. Select temperature based on the task type (factual vs creative)
3. Select max_iterations based on task complexity and tool usage patterns (see guidelines above)
4. If tools are provided, include specific guidance on when and how to use them
5. Include error recovery instructions for common failure scenarios
6. Define success criteria and quality standards

Return ONLY the JSON object with system_prompt, temperature, and max_iterations fields."""

        messages = [
            SystemMessage(content=system_msg),
            HumanMessage(content=user_msg)
        ]

        response = llm.invoke(messages)
        content = response.content.strip()

        # Parse JSON response
        import json
        import re

        # Remove markdown code blocks if present
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first line (```json) and last line (```)
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # Try parsing JSON with multiple strategies
        config = None
        parse_errors = []

        # Strategy 1: Direct parse
        try:
            config = json.loads(content)
        except json.JSONDecodeError as e:
            parse_errors.append(f"Direct parse: {e}")

        # Strategy 2: Fix unescaped backslashes by double-escaping all backslashes first,
        # then restoring valid JSON escapes
        if config is None:
            try:
                # Double all backslashes
                fixed_content = content.replace('\\', '\\\\')
                # Restore valid JSON escapes (now they're quadruple-escaped, fix to double)
                for escape in ['\\\\n', '\\\\r', '\\\\t', '\\\\b', '\\\\f', '\\\\"', '\\\\\\\\']:
                    valid_escape = escape.replace('\\\\\\\\', '\\\\').replace('\\\\', '\\')
                    fixed_content = fixed_content.replace(escape, valid_escape)
                config = json.loads(fixed_content)
            except json.JSONDecodeError as e:
                parse_errors.append(f"Backslash fix: {e}")

        # Strategy 3: Use strict=False for more lenient parsing
        if config is None:
            try:
                config = json.loads(content, strict=False)
            except json.JSONDecodeError as e:
                parse_errors.append(f"Lenient parse: {e}")

        # Strategy 4: Extract just the essential fields with regex
        if config is None:
            try:
                # Extract temperature
                temp_match = re.search(r'"temperature"\s*:\s*([\d.]+)', content)
                iter_match = re.search(r'"max_iterations"\s*:\s*(\d+)', content)

                # Extract system_prompt (everything between first "system_prompt": " and the closing ")
                prompt_match = re.search(r'"system_prompt"\s*:\s*"(.*?)"(?=\s*,\s*"(?:temperature|max_iterations))', content, re.DOTALL)

                if temp_match and prompt_match:
                    config = {
                        "system_prompt": prompt_match.group(1).replace('\\"', '"').replace('\\n', '\n'),
                        "temperature": float(temp_match.group(1)),
                        "max_iterations": int(iter_match.group(1)) if iter_match else 25
                    }
            except Exception as e:
                parse_errors.append(f"Regex extract: {e}")

        # If all strategies failed, raise with context
        if config is None:
            raise ValueError(f"Failed to parse LLM response as JSON. Errors: {'; '.join(parse_errors)}")
        system_prompt = config.get("system_prompt", "")
        temperature = float(config.get("temperature", 0.0))
        max_iterations = int(config.get("max_iterations", 15))

        # Force-append DataFrame protocol if dataframe tools are present
        has_dataframe_tools = tools and any("dataframe" in t for t in tools)

        if has_dataframe_tools:
            dataframe_protocol = """

## DataFrame Operations: Schema-First Methodology

### Core Mental Model
DataFrames are dynamic data structures. Column names, data types, and structure vary between files. You cannot predict what columns exist - you must discover them through schema inspection. Treating column names as variables to guess leads to errors. Treat them as constants to discover.

### Schema Verification Requirement
**Before any column-dependent operation, verify the schema.** Column-dependent operations include:
- dataframe_group_aggregate (uses column names as aggregation keys)
- dataframe_filter_rows (uses column names in filter expressions)
- dataframe_sort (uses column names for sorting)
- dataframe_visualize (uses column names for axes)

**Schema tools available (choose based on need):**
- `csv_process`: Fast column list extraction, use for initial file access
- `dataframe_describe`: Column statistics + schema, best for analysis workflows
- `dataframe_quality_report`: Data quality metrics + schema, use when checking data integrity

### Operation-Specific Guidance

**1. Group & Aggregate Operations**
The aggregations parameter is a dictionary where:
- **Keys = Column names that exist in the DataFrame** (source columns to aggregate)
- **Values = Aggregation function names** (count, sum, mean, median, min, max, std, var, first, last, nunique)

✓ Correct pattern:
```
Schema shows: ["order_id", "customer_id", "total_amount", "quantity"]
Aggregation: {"order_id": "count", "total_amount": "sum", "quantity": "mean"}
Reasoning: All keys (order_id, total_amount, quantity) exist in schema
```

✗ Common error:
```
Aggregation: {"num_orders": "count"}
Error: "Column(s) ['num_orders'] do not exist"
Reason: "num_orders" is what you WANT to call it, not what the column IS called
```

**2. Filter Operations**
Filter expressions are SQL-like strings using actual column names.
- Column names are case-sensitive: "Revenue" ≠ "revenue"
- Use schema to verify exact spelling and case
- Valid operators: =, !=, <, >, <=, >=, AND, OR, IN, LIKE

✓ Example: If schema has "total_amount", use: "total_amount > 1000"
✗ Error: If schema has "total_amount", don't use: "amount > 1000" (wrong column name)

**3. Visualization Operations**
x_column and y_column parameters must exactly match column names from schema.
- Verify both columns exist before calling tool
- Check data types are compatible with visualization type

### Error Recovery Protocol

**If you encounter: "Column(s) ['X'] do not exist"**
1. Re-examine schema tool output for "available_columns" or "schema" section
2. Verify spelling and case sensitivity (columns are case-sensitive)
3. Confirm you're using the column name AS IT APPEARS in schema, not what you want to call it
4. Retry operation with corrected column name

**If schema tool fails or returns no data:**
1. Report error to user immediately
2. Do NOT attempt to guess column names
3. Do NOT proceed with operations that require column names

### Self-Check Before Executing Column Operations
Ask yourself:
1. Have I run a schema tool (csv_process/dataframe_describe/dataframe_quality_report) for this file?
2. Did I read the "available_columns" or "schema" output?
3. Are the column names I'm using EXACTLY as they appear in schema (case-sensitive)?
4. For aggregations: Are my dictionary keys actual column names, not desired output names?

**Remember:** The most common error is using descriptive names (what you want) instead of actual column names (what exists). Always verify against schema output."""

            system_prompt += dataframe_protocol

        # Force-append SQL/Database protocol if SQL tools are present
        has_sql_tools = tools and any(t in ["sql_executor", "database_query", "sql_query", "database_list_tables", "database_describe_table"] for t in tools)
        if has_sql_tools:
            sql_protocol = """

## SQL/Database Operations: Schema-First Query Development

### Core Mental Model
Databases are structured systems with predefined schemas. Table and column names are fixed artifacts that must be discovered, not assumed. Writing queries without schema knowledge is the equivalent of coding against an unknown API. **SQL tools now follow the SAME PATTERN as DataFrame tools: automatic schema discovery with structured output.**

### Automatic Schema Discovery Tools
**Before writing any SQL query, use these tools to discover schema:**

1. **database_list_tables**: Returns structured output matching DataFrame pattern
   ```json
   {
     "schema": {
       "available_tables": ["users", "orders", "products"],
       "total_tables": 3
     }
   }
   ```
   - Use this FIRST to see what tables exist
   - Similar to csv_process for files

2. **database_describe_table(table_name)**: Returns column schema
   ```json
   {
     "schema": {
       "available_columns": ["user_id", "email", "created_at"],
       "column_types": {"user_id": "integer", "email": "varchar", "created_at": "timestamp"}
     }
   }
   ```
   - Use this BEFORE writing queries involving that table
   - Similar to dataframe_describe for files

### Query Development Workflow
1. **Schema Discovery**: Run `database_list_tables` to see available tables
2. **Table Inspection**: Run `database_describe_table(table_name)` for each table you'll query
3. **Read Schema Output**: Look for "available_columns" and "column_types" in the schema section
4. **Query Construction**: Write SQL using EXACT names from schema (case-sensitive in many databases)
5. **Parameterization**: Use parameterized queries for dynamic values (prevents SQL injection)
6. **Validation**: Test with LIMIT clause first

### Self-Check Before Writing Queries
Ask yourself:
1. Have I run `database_list_tables` to see what tables exist?
2. Have I run `database_describe_table` for each table I'm querying?
3. Did I read the "available_columns" from schema output?
4. Are my table/column names EXACTLY as they appear in schema (case-sensitive)?

### Error Recovery
- **"Table 'X' doesn't exist"**: Re-run `database_list_tables`, verify table name (check case sensitivity)
- **"Unknown column 'X' in 'field list'"**: Re-run `database_describe_table`, check column names
- **"Syntax error near..."**: Check SQL dialect compatibility (MySQL vs PostgreSQL vs SQLite)
- **"Access denied"**: Verify database permissions, may need different credentials

**Remember:** The most common error is guessing table/column names instead of using automatic schema discovery tools."""

            system_prompt += sql_protocol

        # Force-append File handling protocol if file tools are present
        has_file_tools = tools and any(t in ["csv_process", "json_process", "file_reader", "file_write"] for t in tools)
        if has_file_tools:
            file_protocol = """

## File Operations: Defensive Reading and Writing

### Core Mental Model
Files are external resources that can fail in multiple ways: missing, corrupted, wrong encoding, insufficient permissions, or incompatible format. Always validate before trusting file operations.

### File Access Workflow
1. **Path Validation**: Verify file exists and path is within allowed directories (prevent path traversal)
2. **Encoding Detection**: Try UTF-8 first, fallback to latin-1/cp1252 for legacy files
3. **Size Check**: Large files (>100MB) should use streaming/chunked processing
4. **Format Verification**: Validate file format matches expected type (CSV, JSON, etc.)

### Error Recovery
- **"File not found"**: Verify path spelling, check working directory with pwd/cd, ask user for correct path
- **"UnicodeDecodeError"**: Try alternative encodings (UTF-8 → latin-1 → cp1252), or report as binary file
- **"Permission denied"**: Check file permissions (ls -l on Unix), may need read/write access
- **"File too large"**: Use streaming tools or chunked processing, don't load entire file into memory"""

            system_prompt += file_protocol

        # Force-append Research protocol if research tools are present
        has_research_tools = tools and any(t in ["wikipedia_search", "arxiv_search", "research_query"] for t in tools)
        if has_research_tools:
            research_protocol = """

## Research Operations: Source Verification and Attribution

### Core Mental Model
Research sources can be ambiguous (multiple topics with same name), outdated (information changes), or incomplete (missing context). Always verify, cross-reference, and properly attribute sources.

### Research Workflow
1. **Broad Search First**: Start with general queries to identify relevant topics
2. **Disambiguation Handling**: If multiple results exist, present options to user for clarification
3. **Information Extraction**: Capture key metadata (authors, dates, publication venue, DOI/URL)
4. **Attribution**: Always cite sources clearly with proper formatting

### Error Recovery
- **"Multiple matches found" (Wikipedia)**: Present topic options to user, don't assume which they meant
- **"No results found"**: Try alternative search terms, broader queries, or different sources
- **"Page not found"**: Source may be removed/renamed, try Internet Archive or alternative sources"""

            system_prompt += research_protocol

        # Force-append Web operations protocol if web tools are present
        has_web_tools = tools and any(t in ["url_scraper", "web_scraper", "api_client", "http_request"] for t in tools)
        if has_web_tools:
            web_protocol = """

## Web Operations: Resilient Request Handling

### Core Mental Model
Web requests are inherently unreliable: servers can be down, networks can timeout, rate limits can block you. Design for failure and retry intelligently.

### Web Request Workflow
1. **URL Validation**: Verify URL format is correct before making request
2. **Timeout Configuration**: Set reasonable timeouts (10-30s for most requests)
3. **Retry Logic**: Implement exponential backoff for transient failures (500, 502, 503 errors)
4. **Response Handling**: Check HTTP status codes, parse errors gracefully

### HTTP Status Codes
- **2xx (Success)**: Request succeeded, parse response
- **4xx (Client Error)**: 404 = Not Found, 429 = Rate Limited (wait and retry)
- **5xx (Server Error)**: Temporary issue, retry with exponential backoff

### Error Recovery
- **"Timeout"**: Increase timeout, verify server is reachable, may be slow endpoint
- **"429 Rate Limited"**: Wait specified duration (check Retry-After header), then retry
- **"SSL Certificate Error"**: Certificate may be expired/invalid, report to user"""

            system_prompt += web_protocol

        # Force-append Shell execution protocol if shell tools are present
        has_shell_tools = tools and any(t in ["shell_execute", "bash_execute", "command_execute"] for t in tools)
        if has_shell_tools:
            shell_protocol = """

## Shell Command Execution: Security-First Approach

### ⚠️ CRITICAL SECURITY WARNING ⚠️
Shell execution is HIGH-RISK. Commands can delete data, expose secrets, or compromise system security. Treat every shell command as potentially destructive.

### Security Rules (NON-NEGOTIABLE)
1. **Input Validation**: NEVER execute commands with unsanitized user input (command injection risk)
2. **Destructive Commands**: Require explicit user confirmation for rm, format, dd, etc.
3. **Path Safety**: Use absolute paths, validate paths are within allowed scope
4. **Privilege Escalation**: Never use sudo without explicit user authorization

### Command Execution Workflow
1. **Safety Check**: Validate command is not destructive or injection vector
2. **User Confirmation**: If modifying files/system, get explicit user approval
3. **Timeout Configuration**: Set timeout to prevent infinite loops/hangs
4. **Output Capture**: Capture both stdout and stderr for complete context

### NEVER EXECUTE
- `rm -rf /` or similar recursive deletion patterns
- Commands with unescaped user input variables
- `eval` or similar code execution with dynamic input
- Network-accessible services without authorization"""

            system_prompt += shell_protocol

        # Clamp temperature and max_iterations to valid ranges
        temperature = max(0.0, min(2.0, temperature))
        max_iterations = max(5, min(100, max_iterations))  # Reasonable bounds: 5-100 iterations

        return system_prompt, temperature, max_iterations

    except Exception as e:
        console.print(f"[yellow]⚠ Failed to generate config: {e}[/yellow]")
        return None, 0.0, 15
