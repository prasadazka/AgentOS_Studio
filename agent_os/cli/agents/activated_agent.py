"""
Activated Agent Wrapper

Wraps agents in activated mode with:
- File context injection
- Safety controls for destructive operations
- Enhanced system prompt with discovered files
"""

from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from datetime import datetime

from pydantic import BaseModel, Field

from agent_os.agents.base import BaseAgent
from agent_os.tools.registry import ToolRegistry
from agent_os.cli.core.agent_activation import (
    DiscoveredFile,
    AgentActivationManager,
    AgentSessionMemory,
    save_session,
)
from agent_os.agents.defaults import is_default_agent, load_default_agent
from agent_os.cli.core.config_generator import ConfigGenerator
from agent_os.utils.logging import get_logger

logger = get_logger("cli.agents.activated_agent")


class SafetyViolation(Exception):
    """Raised when a safety rule is violated"""
    pass


class DestructiveOperationRequest(BaseModel):
    """Request for a destructive operation requiring confirmation"""
    operation: str
    target_path: str
    description: str
    requires_confirmation: bool = True


class DatabaseConfig(BaseModel):
    """Database connection configuration"""
    type: str = "sqlite"  # sqlite, postgresql, mysql
    connection_string: str = ""
    read_only: bool = True
    max_rows: int = 1000
    timeout: float = 30.0


class ActivatedAgentConfig(BaseModel):
    """Configuration for activated agent"""
    name: str
    tools: List[str] = Field(default_factory=list)
    model: str = "gpt-4o-mini"
    temperature: float = 0
    system_prompt: str = ""
    max_iterations: int = 10
    database: Optional[DatabaseConfig] = None


class ActivatedAgent:
    """
    Agent wrapper with file context injection and safety controls.

    Features:
    - Injects discovered files into system prompt
    - Wraps destructive tools with confirmation callbacks
    - Enforces working directory scope
    - Tracks file operations for audit
    """

    # Tools that require confirmation before execution
    DESTRUCTIVE_TOOLS = {
        "file_delete",
        "file_move",
        "file_rename",
        "directory_delete",
        "sql_execute",  # DROP, DELETE, TRUNCATE
    }

    # Operations that need confirmation in SQL
    DESTRUCTIVE_SQL_PATTERNS = [
        "DROP", "DELETE", "TRUNCATE", "ALTER", "UPDATE"
    ]

    def __init__(
        self,
        agent_name: str,
        discovered_files: List[DiscoveredFile],
        working_directory: Path,
        tool_registry: ToolRegistry,
        safety_mode: bool = True,
        confirmation_callback: Optional[Callable[[DestructiveOperationRequest], bool]] = None,
        session: Optional[AgentSessionMemory] = None,
    ):
        """
        Initialize activated agent.

        Args:
            agent_name: Name of the agent to activate
            discovered_files: List of discovered files for context
            working_directory: Working directory scope
            tool_registry: Tool registry instance
            safety_mode: Enable safety controls (default: True)
            confirmation_callback: Callback for destructive operation confirmation
            session: Session memory from previous activation (optional)
        """
        self.agent_name = agent_name
        self.discovered_files = discovered_files
        self.working_directory = Path(working_directory).resolve()
        self.tool_registry = tool_registry
        self.safety_mode = safety_mode
        self.confirmation_callback = confirmation_callback

        # Session memory for file tracking
        self.session = session or AgentSessionMemory(
            last_agent=agent_name,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        # Load agent configuration
        self._config = self._load_agent_config(agent_name)
        if not self._config:
            raise ValueError(f"Agent '{agent_name}' not found")

        # Build enhanced system prompt
        self._enhanced_prompt = self._build_enhanced_prompt()

        # Create underlying agent
        self._agent = self._create_agent()

        # Operation audit log
        self._operations_log: List[Dict[str, Any]] = []

        logger.info(
            f"ActivatedAgent initialized: {agent_name} "
            f"with {len(discovered_files)} files, safety={safety_mode}, "
            f"session_file={self.session.last_used_file}"
        )

    def _load_agent_config(self, agent_name: str) -> Optional[ActivatedAgentConfig]:
        """Load agent configuration from defaults or user configs"""
        try:
            # Check default agents first
            if is_default_agent(agent_name):
                config_dict = load_default_agent(agent_name)
            else:
                # Load from user configs
                config_gen = ConfigGenerator()
                config_dict = config_gen.load_and_validate_config("agents", agent_name)

            # Parse database config if present
            db_config = None
            if "database" in config_dict:
                db_dict = config_dict["database"]
                db_config = DatabaseConfig(
                    type=db_dict.get("type", "sqlite"),
                    connection_string=db_dict.get("connection_string", ""),
                    read_only=db_dict.get("read_only", True),
                    max_rows=db_dict.get("max_rows", 1000),
                    timeout=db_dict.get("timeout", 30.0),
                )

            return ActivatedAgentConfig(
                name=config_dict.get("name", agent_name),
                tools=config_dict.get("tools", []),
                model=config_dict.get("model", "gpt-4o-mini"),
                temperature=config_dict.get("temperature", 0),
                system_prompt=config_dict.get("system_prompt", ""),
                max_iterations=config_dict.get("max_iterations", 10),
                database=db_config,
            )

        except FileNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Failed to load agent config '{agent_name}': {e}")
            return None

    def _build_enhanced_prompt(self) -> str:
        """Build system prompt with discovered files context and session memory"""
        base_prompt = self._config.system_prompt

        # Build file context section
        if not self.discovered_files:
            file_context = """
DISCOVERED FILES: None
No matching files found in the working directory.
Ask user for specific file paths if needed.
"""
        else:
            # Calculate totals
            total_size = sum(f.size_bytes for f in self.discovered_files)
            total_size_human = AgentActivationManager._humanize_bytes(total_size)

            # Build file list (compact, max 30) - show relative paths
            file_lines = []
            for f in self.discovered_files[:30]:
                age = AgentActivationManager._get_file_age(f.modified)
                recent = " [RECENT]" if f.is_recent else ""
                # Show relative path from working directory
                try:
                    rel_path = Path(f.path).relative_to(self.working_directory)
                    display_path = str(rel_path)
                except ValueError:
                    display_path = f.name
                file_lines.append(f"  {display_path} ({f.size_human}, {age}){recent}")

            if len(self.discovered_files) > 30:
                file_lines.append(f"  ... and {len(self.discovered_files) - 30} more files")

            file_list = "\n".join(file_lines)

            file_context = f"""
DISCOVERED FILES ({len(self.discovered_files)} files, {total_size_human} total):
{file_list}

Files marked [RECENT] were modified in the last 24 hours.
"""

        # Build session context (remembers last used file)
        session_context = self.session.to_context_string() if self.session else ""

        # Build database context if configured - auto-discover schema
        database_context = ""
        if self._config.database and self._config.database.connection_string:
            schema_info = self._discover_database_schema()
            database_context = f"""
*** DATABASE MODE ***
Database: {self._config.database.type.upper()}
Read-only: {self._config.database.read_only}

{schema_info}

CRITICAL: Use ONLY the EXACT column names shown above. Do NOT guess or invent column names!
"""

        # Build complete enhanced prompt
        enhanced_prompt = f"""
=== ACTIVATED MODE: {self.agent_name} ===
Working Directory: {self.working_directory}
{database_context}
{file_context}
{session_context}

FAST FILE ACCESS (IMPORTANT - READ THIS):
1. If user provides a FULL PATH (e.g., E:\\folder\\file.csv or /home/user/file.csv) → USE IT DIRECTLY with the appropriate tool
2. If user mentions a filename only → check DISCOVERED FILES list above for the full path
3. If file not found in discovered list and no full path given → ask user for the path

TOOL SELECTION BY EXTENSION:
- .csv/.tsv → csv_process (file_path parameter)
- .json → json_process (file_path parameter)
- Other text files → file_read (file_path parameter)

CRITICAL: When user gives a FULL PATH, call the tool IMMEDIATELY with that exact path. Do NOT say "file not found" without trying!

*** CRITICAL: AUTO-USE SESSION FILE ***
If SESSION MEMORY shows a 'CURRENT WORKING FILE' and user asks about data WITHOUT specifying a file:
→ AUTOMATICALLY read and analyze that file
→ NEVER ask for confirmation ("which file?", "please confirm", etc.)
→ NEVER say "I need a file path" when session has a file
→ JUST DO THE ANALYSIS using the session file

===

{base_prompt}
"""
        return enhanced_prompt.strip()

    def _create_agent(self) -> BaseAgent:
        """Create the underlying BaseAgent with enhanced prompt"""
        # Register database tools with config if database is configured
        if self._config.database and self._config.database.connection_string:
            self._register_database_tools()

        # Get valid tools from registry
        valid_tools = []
        missing_tools = []
        for tool_name in self._config.tools:
            tool = self.tool_registry.get(tool_name)
            if tool:
                valid_tools.append(tool_name)
                logger.info(f"Tool loaded: {tool_name}")
            else:
                missing_tools.append(tool_name)
                logger.warning(f"Tool '{tool_name}' not found in registry, skipping")

        if missing_tools:
            logger.error(f"Missing tools: {missing_tools}. Available: {self.tool_registry.list_all()[:10]}")

        logger.info(f"Creating agent with {len(valid_tools)} tools: {valid_tools}")

        return BaseAgent(
            name=f"{self.agent_name}_activated",
            tools=valid_tools,
            model=self._config.model,
            temperature=self._config.temperature,
            system_prompt=self._enhanced_prompt,
            tool_registry=self.tool_registry,
            max_iterations=self._config.max_iterations,
            enable_circuit_breaker=True,
            enable_cost_tracking=True,
            enable_rate_limiting=True,
            enable_retry=True,
            enable_metrics=True,
        )

    def _discover_database_schema(self) -> str:
        """Auto-discover database schema at activation time"""
        if not self._config.database:
            return ""

        db_config = self._config.database
        schema_lines = ["DATABASE SCHEMA (use these EXACT column names):"]

        try:
            if db_config.type == "sqlite":
                import sqlite3
                conn = sqlite3.connect(db_config.connection_string, timeout=db_config.timeout)
                cursor = conn.cursor()

                # Get all tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                tables = [row[0] for row in cursor.fetchall()]

                for table in tables:
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = cursor.fetchall()
                    col_info = [f"{col[1]} ({col[2]})" for col in columns]
                    schema_lines.append(f"\n  {table}: {', '.join(col_info)}")

                conn.close()

            elif db_config.type == "postgresql":
                try:
                    import psycopg2
                    conn = psycopg2.connect(db_config.connection_string, connect_timeout=int(db_config.timeout))
                    cursor = conn.cursor()

                    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
                    tables = [row[0] for row in cursor.fetchall()]

                    for table in tables:
                        cursor.execute(f"""
                            SELECT column_name, data_type
                            FROM information_schema.columns
                            WHERE table_name = '{table}' ORDER BY ordinal_position
                        """)
                        columns = cursor.fetchall()
                        col_info = [f"{col[0]} ({col[1]})" for col in columns]
                        schema_lines.append(f"\n  {table}: {', '.join(col_info)}")

                    conn.close()
                except ImportError:
                    schema_lines.append("\n  (psycopg2 not installed - use database_describe_table)")

            elif db_config.type == "mysql":
                try:
                    import mysql.connector
                    # Parse connection string
                    import re
                    match = re.match(r"mysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", db_config.connection_string)
                    if match:
                        conn = mysql.connector.connect(
                            user=match.group(1), password=match.group(2),
                            host=match.group(3), port=int(match.group(4)),
                            database=match.group(5), connection_timeout=int(db_config.timeout)
                        )
                        cursor = conn.cursor()

                        cursor.execute("SHOW TABLES")
                        tables = [row[0] for row in cursor.fetchall()]

                        for table in tables:
                            cursor.execute(f"DESCRIBE {table}")
                            columns = cursor.fetchall()
                            col_info = [f"{col[0]} ({col[1]})" for col in columns]
                            schema_lines.append(f"\n  {table}: {', '.join(col_info)}")

                        conn.close()
                except ImportError:
                    schema_lines.append("\n  (mysql-connector not installed - use database_describe_table)")

            logger.info(f"Discovered schema for {len(tables) if 'tables' in dir() else 0} tables")

        except Exception as e:
            logger.warning(f"Schema discovery failed: {e}")
            schema_lines.append(f"\n  (Schema discovery failed: {e})")
            schema_lines.append("\n  Use database_list_tables and database_describe_table to discover schema")

        return "\n".join(schema_lines)

    def _register_database_tools(self):
        """Register database tools with proper configuration from agent config"""
        if not self._config.database:
            return

        db_config = self._config.database
        logger.info(f"Registering database tools: type={db_config.type}, read_only={db_config.read_only}")

        try:
            from agent_os.tools.library.database import (
                SQLExecutorTool,
                DatabaseListTablesTool,
                DatabaseDescribeTableTool
            )

            # Create configured database tools
            sql_executor = SQLExecutorTool(
                db_type=db_config.type,
                connection_string=db_config.connection_string,
                read_only=db_config.read_only,
                max_rows=db_config.max_rows,
                timeout=db_config.timeout,
            )

            list_tables = DatabaseListTablesTool(
                db_type=db_config.type,
                connection_string=db_config.connection_string,
                timeout=db_config.timeout,
            )

            describe_table = DatabaseDescribeTableTool(
                db_type=db_config.type,
                connection_string=db_config.connection_string,
                timeout=db_config.timeout,
            )

            # Register tools (replace defaults with configured versions)
            self.tool_registry.register(sql_executor, replace=True)
            self.tool_registry.register(list_tables, replace=True)
            self.tool_registry.register(describe_table, replace=True)

            logger.info(f"Database tools registered for {db_config.type}: {db_config.connection_string[:30]}...")

        except ImportError as e:
            logger.warning(f"Could not import database tools: {e}")
        except Exception as e:
            logger.error(f"Failed to register database tools: {e}")

    def _check_path_scope(self, path: str) -> bool:
        """Check if path is within working directory scope"""
        try:
            target = Path(path).resolve()
            return str(target).startswith(str(self.working_directory))
        except Exception:
            return False

    def _is_destructive_sql(self, query: str) -> bool:
        """Check if SQL query is destructive"""
        query_upper = query.upper().strip()
        return any(pattern in query_upper for pattern in self.DESTRUCTIVE_SQL_PATTERNS)

    def _request_confirmation(
        self,
        operation: str,
        target_path: str,
        description: str
    ) -> bool:
        """Request user confirmation for destructive operation"""
        if not self.safety_mode:
            return True

        request = DestructiveOperationRequest(
            operation=operation,
            target_path=target_path,
            description=description,
        )

        if self.confirmation_callback:
            return self.confirmation_callback(request)

        # Default: deny destructive operations without callback
        logger.warning(
            f"Destructive operation blocked (no confirmation callback): "
            f"{operation} on {target_path}"
        )
        return False

    def _log_operation(
        self,
        operation: str,
        target: str,
        success: bool,
        details: Optional[str] = None
    ):
        """Log operation for audit trail"""
        self._operations_log.append({
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "target": target,
            "success": success,
            "details": details,
        })

    def _extract_file_path_from_text(self, text: str) -> Optional[str]:
        """Extract file path from query or response text"""
        import re

        # Common file path patterns - use findall with full match
        patterns = [
            # Windows absolute paths (e.g., E:\folder\file.csv)
            r'[A-Za-z]:[\\\/][^\s\"\'\n<>|*?]+\.\w{2,5}',
            # Unix absolute paths (e.g., /home/user/file.csv)
            r'\/[^\s\"\'\n<>|*?]+\.\w{2,5}',
            # Relative paths with extension (e.g., folder/file.csv, ./file.csv)
            r'\.?[\\\/]?[\w\-\.]+[\\\/][\w\-\.\\\/]+\.\w{2,5}',
            # Simple filenames with common data extensions (no capturing group)
            r'\b[\w\-\.]+\.(?:csv|json|xlsx?|txt|parquet|tsv)\b',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Return the first valid match
                match = matches[0]
                # For simple filenames, try to find full path from discovered files
                if not ('/' in match or '\\' in match):
                    for f in self.discovered_files:
                        if f.name.lower() == match.lower():
                            return f.path
                    # If not found in discovered files, still return the filename
                    # as it might be a new file being created
                return match

        return None

    def _update_session_from_query(self, query: str, output: str):
        """Update session memory based on query/output file references"""
        # Try to extract file from query first
        file_path = self._extract_file_path_from_text(query)

        # If not found in query, try output
        if not file_path:
            file_path = self._extract_file_path_from_text(output)

        if file_path:
            # Resolve to absolute path if needed
            if not Path(file_path).is_absolute():
                resolved_path = self.working_directory / file_path
                if resolved_path.exists():
                    file_path = str(resolved_path)

            # Update session
            self.session.add_file_to_history(file_path)
            self.session.last_query = query[:200]

            # Save session to disk
            save_session(self.working_directory, self.session)
            logger.debug(f"Session updated with file: {file_path}")

            # Rebuild prompt with updated session context
            self._enhanced_prompt = self._build_enhanced_prompt()
            self._agent.update_system_prompt(self._enhanced_prompt)

    def run(self, query: str) -> Dict[str, Any]:
        """
        Execute query with enhanced context and safety controls.

        Args:
            query: User query

        Returns:
            Dict with 'output' (str), 'success' (bool), and metadata
        """
        try:
            logger.info(f"ActivatedAgent executing: {query[:100]}...")

            # Execute through base agent
            result = self._agent.run(query)

            # Update session with any file references
            self._update_session_from_query(query, result)

            self._log_operation(
                operation="query",
                target=query[:100],
                success=True,
            )

            return {
                "success": True,
                "output": result,
                "agent": self.agent_name,
                "files_context": len(self.discovered_files),
                "current_file": self.session.last_used_file if self.session else None,
            }

        except SafetyViolation as e:
            logger.warning(f"Safety violation: {e}")
            self._log_operation(
                operation="query",
                target=query[:100],
                success=False,
                details=f"Safety violation: {e}",
            )
            return {
                "success": False,
                "output": f"Operation blocked by safety controls: {e}",
                "agent": self.agent_name,
                "error": "safety_violation",
            }

        except Exception as e:
            logger.error(f"ActivatedAgent execution error: {e}")
            self._log_operation(
                operation="query",
                target=query[:100],
                success=False,
                details=str(e),
            )
            return {
                "success": False,
                "output": f"Execution error: {e}",
                "agent": self.agent_name,
                "error": type(e).__name__,
            }

    async def arun(self, query: str) -> Dict[str, Any]:
        """Async execution with enhanced context"""
        try:
            result = await self._agent.arun(query)

            self._log_operation(
                operation="async_query",
                target=query[:100],
                success=True,
            )

            return {
                "success": True,
                "output": result,
                "agent": self.agent_name,
                "files_context": len(self.discovered_files),
            }

        except Exception as e:
            logger.error(f"ActivatedAgent async error: {e}")
            self._log_operation(
                operation="async_query",
                target=query[:100],
                success=False,
                details=str(e),
            )
            return {
                "success": False,
                "output": f"Execution error: {e}",
                "agent": self.agent_name,
                "error": type(e).__name__,
            }

    def refresh_files(self, new_files: List[DiscoveredFile]):
        """Refresh discovered files and rebuild prompt"""
        self.discovered_files = new_files
        self._enhanced_prompt = self._build_enhanced_prompt()
        self._agent.update_system_prompt(self._enhanced_prompt)
        logger.info(f"Refreshed files context: {len(new_files)} files")

    def get_operations_log(self) -> List[Dict[str, Any]]:
        """Get audit log of operations"""
        return self._operations_log.copy()

    def get_discovered_files_summary(self) -> Dict[str, Any]:
        """Get summary of discovered files"""
        if not self.discovered_files:
            return {
                "count": 0,
                "total_size": "0 B",
                "extensions": [],
                "recent_count": 0,
            }

        total_size = sum(f.size_bytes for f in self.discovered_files)
        extensions = list(set(f.extension for f in self.discovered_files))
        recent_count = sum(1 for f in self.discovered_files if f.is_recent)

        return {
            "count": len(self.discovered_files),
            "total_size": AgentActivationManager._humanize_bytes(total_size),
            "extensions": extensions,
            "recent_count": recent_count,
        }

    def get_info(self) -> Dict[str, Any]:
        """Get activated agent information"""
        base_info = self._agent.get_info()

        return {
            **base_info,
            "activated_name": self.agent_name,
            "working_directory": str(self.working_directory),
            "safety_mode": self.safety_mode,
            "files_discovered": len(self.discovered_files),
            "files_summary": self.get_discovered_files_summary(),
            "operations_count": len(self._operations_log),
        }

    def get_session(self) -> Optional[AgentSessionMemory]:
        """Get current session memory"""
        return self.session

    def set_current_file(self, file_path: str):
        """Explicitly set the current working file"""
        if self.session:
            self.session.add_file_to_history(file_path)
            save_session(self.working_directory, self.session)
            # Rebuild prompt with updated session
            self._enhanced_prompt = self._build_enhanced_prompt()
            self._agent.update_system_prompt(self._enhanced_prompt)
            logger.info(f"Current file set to: {file_path}")

    def cleanup(self):
        """Clean up agent resources and save session"""
        # Save session before cleanup
        if self.session:
            save_session(self.working_directory, self.session)
            logger.info(f"Session saved for '{self.agent_name}'")

        if self._agent:
            self._agent.cleanup()
        logger.info(f"ActivatedAgent '{self.agent_name}' cleaned up")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def __repr__(self) -> str:
        return (
            f"<ActivatedAgent(name='{self.agent_name}', "
            f"files={len(self.discovered_files)}, "
            f"safety={self.safety_mode})>"
        )
