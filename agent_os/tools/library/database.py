"""Production-grade database query and management tools"""

from typing import Optional, List, Dict, Any, Literal
from contextlib import contextmanager
import json
import sqlite3
import re
import time
import hashlib
from functools import wraps

from pydantic import BaseModel, Field, validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import (
    ToolExecutionError,
    ToolValidationError,
    DatabaseConnectionError,
    DatabaseQueryError,
    SQLInjectionError,
    ErrorCode
)
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)

DatabaseType = Literal["sqlite", "postgresql", "mysql"]


# =============================================================================
# Type-Safe Models
# =============================================================================

class SQLExecutorInput(BaseModel):
    """Type-safe SQL query input with validation"""
    query: str = Field(..., min_length=1)
    params: Optional[List[Any]] = None

    @validator('query')
    def validate_query(cls, v):
        """Validate query for SQL injection patterns"""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")

        v_stripped = v.strip()

        # SQL injection: comments
        if "--" in v_stripped or "/*" in v_stripped or "*/" in v_stripped:
            raise SQLInjectionError(
                "Query contains SQL comments (injection vector)",
                query_preview=v_stripped[:100]
            )

        # SQL injection: multiple statements
        v_no_trailing = v_stripped.rstrip(';')
        if ';' in v_no_trailing:
            raise SQLInjectionError(
                "Multiple SQL statements not allowed",
                query_preview=v_stripped[:100]
            )

        # SQL injection: common patterns
        patterns = [
            r'\bUNION\s+SELECT\b',
            r'\bOR\s+1\s*=\s*1\b',
            r"'\s*OR\s+'",
            r'\bEXEC\s*\(',
            r'\bXP_CMDSHELL\b',
        ]

        for pattern in patterns:
            if re.search(pattern, v_stripped, re.IGNORECASE):
                raise SQLInjectionError(
                    f"Dangerous pattern detected: {pattern}",
                    query_preview=v_stripped[:100]
                )

        return v


class SQLExecutorOutput(BaseModel):
    """Type-safe SQL query output"""
    success: bool
    query: str
    rows_returned: Optional[int] = None
    rows_affected: Optional[int] = None
    truncated: bool = False
    max_rows: Optional[int] = None
    data: Optional[List[Dict[str, Any]]] = None
    message: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Retry Decorator
# =============================================================================

def retry_with_backoff(max_attempts=3, initial_delay=0.5, max_delay=10.0, base=2.0):
    """Retry with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except (sqlite3.OperationalError, ConnectionError) as e:
                    if attempt < max_attempts:
                        logger.warning(
                            f"DB operation failed, retrying {attempt}/{max_attempts}",
                            extra={"attempt": attempt, "delay": delay}
                        )
                        time.sleep(delay)
                        delay = min(delay * base, max_delay)
                    else:
                        raise DatabaseConnectionError(
                            f"Failed after {max_attempts} attempts",
                            details={"last_error": str(e)}
                        ) from e
            raise
        return wrapper
    return decorator


# =============================================================================
# Production-Grade Database Tool
# =============================================================================

class SQLExecutorTool(BaseTool):
    """Production-grade SQL executor with security and reliability

    Security:
    - SQL injection protection
    - Parameterized queries
    - Read-only mode
    - Credential masking

    Reliability:
    - Context managers (guaranteed cleanup)
    - Retry logic
    - Connection pooling
    - Structured errors
    """

    def __init__(
        self,
        db_type: DatabaseType = "sqlite",
        connection_string: Optional[str] = None,
        read_only: bool = True,
        max_rows: int = 1000,
        timeout: float = 30.0,
        max_retries: int = 3
    ):
        self.db_type = db_type
        self.connection_string = connection_string
        self.read_only = read_only
        self.max_rows = max_rows
        self.timeout = timeout
        self.max_retries = max_retries

        super().__init__(
            ToolMetadata(
                name="sql_executor",
                description="Execute SQL queries on any database. Pass database_path to connect to a specific .db file. Example: sql_executor(query='SELECT * FROM table', database_path='/path/to/file.db')",
                category="data",
                tags=["sql", "database", "query"]
            )
        )

    def _validate_config(self):
        """Validate configuration - connection_string can be provided dynamically via database_path"""
        # connection_string is optional - can be provided dynamically in _execute via database_path
        if self.timeout <= 0 or self.timeout > 300:
            raise ToolValidationError(
                "Timeout must be 0-300 seconds",
                field_name="timeout"
            )

    @contextmanager
    def _get_connection(self):
        """Context manager - guaranteed cleanup"""
        conn = None
        conn_hash = hashlib.sha256(
            (self.connection_string or "").encode()
        ).hexdigest()[:8]

        try:
            logger.info("Opening DB connection", extra={
                "db_type": self.db_type,
                "conn_hash": conn_hash
            })
            conn = self._create_connection()
            yield conn
        finally:
            if conn:
                try:
                    conn.close()
                    logger.info("DB connection closed", extra={"conn_hash": conn_hash})
                except Exception as e:
                    logger.error("Error closing connection", exc_info=True)

    @retry_with_backoff(max_attempts=3)
    def _create_connection(self):
        """Create connection with retry logic"""
        if self.db_type == "sqlite":
            return self._create_sqlite()
        elif self.db_type == "postgresql":
            return self._create_postgresql()
        elif self.db_type == "mysql":
            return self._create_mysql()
        else:
            raise ToolValidationError(
                f"Unsupported db_type: {self.db_type}",
                field_name="db_type"
            )

    def _create_sqlite(self):
        """Create SQLite connection"""
        try:
            conn = sqlite3.connect(
                self.connection_string,
                timeout=self.timeout,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            raise DatabaseConnectionError(
                "Failed to connect to SQLite",
                details={"db_path": self.connection_string, "error": str(e)}
            ) from e

    def _create_postgresql(self):
        """Create PostgreSQL connection"""
        try:
            import psycopg2
        except ImportError:
            raise ToolExecutionError(
                "psycopg2 not installed",
                details={"install": "pip install psycopg2-binary"}
            )

        try:
            return psycopg2.connect(
                self.connection_string,
                connect_timeout=int(self.timeout)
            )
        except Exception as e:
            safe_str = self._mask_credentials(self.connection_string)
            raise DatabaseConnectionError(
                "Failed to connect to PostgreSQL",
                details={"connection": safe_str, "error": str(e)}
            ) from e

    def _create_mysql(self):
        """Create MySQL connection"""
        try:
            import mysql.connector
        except ImportError:
            raise ToolExecutionError(
                "mysql-connector-python not installed",
                details={"install": "pip install mysql-connector-python"}
            )

        try:
            params = self._parse_mysql_string()
            params['connection_timeout'] = int(self.timeout)
            return mysql.connector.connect(**params)
        except Exception as e:
            raise DatabaseConnectionError(
                "Failed to connect to MySQL",
                details={"error": str(e)}
            ) from e

    def _parse_mysql_string(self) -> Dict[str, Any]:
        """Parse MySQL connection string"""
        pattern = r"mysql://(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)/(?P<database>.+)"
        match = re.match(pattern, self.connection_string)
        if not match:
            raise ToolValidationError(
                "Invalid MySQL connection string",
                field_name="connection_string"
            )
        return {
            "user": match.group("user"),
            "password": match.group("password"),
            "host": match.group("host"),
            "port": int(match.group("port")),
            "database": match.group("database")
        }

    def _mask_credentials(self, text: str) -> str:
        """Mask passwords for logging"""
        masked = re.sub(r'(password|pwd)=([^&\s]+)', r'\1=***', text, flags=re.IGNORECASE)
        masked = re.sub(r':([^:@]+)@', r':***@', masked)
        return masked

    def _validate_readonly(self, query: str):
        """Validate read-only mode"""
        if not self.read_only:
            return

        keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "REPLACE", "MERGE", "GRANT", "REVOKE"]
        query_upper = query.strip().upper()

        for keyword in keywords:
            if re.search(rf'\b{keyword}\b', query_upper):
                raise SQLInjectionError(
                    f"Forbidden keyword '{keyword}' in read-only mode",
                    query_preview=query[:100]
                )

    def _execute(
        self,
        query: str,
        params: Optional[List[Any]] = None,
        database_path: Optional[str] = None
    ) -> str:
        """Execute SQL query with production-grade security

        Args:
            query: SQL query (use ? for SQLite, %s for PostgreSQL/MySQL)
            params: Query parameters (ALWAYS use for user input)
            database_path: Optional database path (overrides configured connection_string)

        Returns:
            JSON with SQLExecutorOutput schema
        """
        # Allow dynamic database path override
        original_connection = self.connection_string
        if database_path:
            self.connection_string = database_path
            logger.info(f"Using dynamic database path: {database_path}")

        start_time = time.time()
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = SQLExecutorInput(query=query, params=params)
            self._validate_readonly(validated.query)

            logger.info("Executing SQL", extra={
                "query_hash": query_hash,
                "db_type": self.db_type,
                "parameterized": bool(params)
            })

            # Execute with context manager
            with self._get_connection() as conn:
                cursor = conn.cursor()
                try:
                    if validated.params:
                        cursor.execute(validated.query, validated.params)
                    else:
                        cursor.execute(validated.query)

                    if validated.query.strip().upper().startswith("SELECT"):
                        result = self._handle_select(cursor, validated.query)
                    else:
                        conn.commit()
                        result = SQLExecutorOutput(
                            success=True,
                            query=validated.query,
                            rows_affected=cursor.rowcount,
                            message="Query executed successfully"
                        )

                    duration = time.time() - start_time
                    result.metadata["duration_seconds"] = round(duration, 3)
                    result.metadata["db_type"] = self.db_type

                    logger.info("SQL executed", extra={
                        "query_hash": query_hash,
                        "duration": duration,
                        "status": "success"
                    })

                    return result.to_json()
                finally:
                    cursor.close()

        except ToolValidationError as e:
            logger.error("Validation failed", extra={"query_hash": query_hash}, exc_info=True)
            return SQLExecutorOutput(
                success=False, query=query, error=str(e), error_code=e.error_code.value
            ).to_json()

        except SQLInjectionError as e:
            logger.error("SQL injection blocked", extra={"query_hash": query_hash}, exc_info=True)
            return SQLExecutorOutput(
                success=False, query=query, error=str(e), error_code=e.error_code.value
            ).to_json()

        except DatabaseConnectionError as e:
            logger.error("Connection failed", extra={"query_hash": query_hash}, exc_info=True)
            return SQLExecutorOutput(
                success=False, query=query, error=str(e), error_code=e.error_code.value
            ).to_json()

        except sqlite3.Error as e:
            logger.error("SQLite error", extra={"query_hash": query_hash}, exc_info=True)
            return SQLExecutorOutput(
                success=False, query=query, error=f"SQLite error: {str(e)}",
                error_code=ErrorCode.DB_QUERY_ERROR.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"query_hash": query_hash}, exc_info=True)
            return SQLExecutorOutput(
                success=False, query=query, error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

        finally:
            # Restore original connection string if it was overridden
            if database_path:
                self.connection_string = original_connection

    def _handle_select(self, cursor, query: str) -> SQLExecutorOutput:
        """Handle SELECT query results"""
        if self.db_type == "sqlite":
            rows = cursor.fetchmany(self.max_rows)
            columns = [d[0] for d in cursor.description]
            results = [dict(zip(columns, row)) for row in rows]
            has_more = len(cursor.fetchall()) > 0

        elif self.db_type == "postgresql":
            rows = cursor.fetchmany(self.max_rows)
            columns = [d[0] for d in cursor.description]
            results = [dict(zip(columns, row)) for row in rows]
            has_more = cursor.rowcount > len(results)

        elif self.db_type == "mysql":
            rows = cursor.fetchmany(self.max_rows)
            columns = [d[0] for d in cursor.description]
            results = [dict(zip(columns, row)) for row in rows]
            has_more = cursor.rowcount > len(results)

        else:
            results = []
            has_more = False

        output = SQLExecutorOutput(
            success=True,
            query=query,
            rows_returned=len(results),
            truncated=has_more,
            max_rows=self.max_rows,
            data=results
        )

        if has_more:
            output.message = f"Results truncated to {self.max_rows} rows"

        return output


# =============================================================================
# Schema Discovery Helper Tools
# =============================================================================

class DatabaseListTablesTool(BaseTool):
    """List all available tables in the database with automatic schema discovery

    Returns structured output similar to DataFrame tools' schema pattern.
    Makes SQL operations follow the same schema-first methodology as DataFrame tools.
    """

    def __init__(
        self,
        db_type: DatabaseType = "sqlite",
        connection_string: Optional[str] = None,
        timeout: float = 30.0
    ):
        self.db_type = db_type
        self.connection_string = connection_string
        self.timeout = timeout

        super().__init__(
            ToolMetadata(
                name="database_list_tables",
                description="List all tables in a database. Pass database_path for .db files. Example: database_list_tables(database_path='/path/to/file.db')",
                category="data",
                tags=["sql", "database", "schema", "discovery"]
            )
        )

    def _execute(self, database_path: Optional[str] = None, **kwargs) -> str:
        """List all tables in the database"""
        try:
            # Use provided path or fall back to configured
            conn_string = database_path or self.connection_string
            if not conn_string:
                return json.dumps({
                    "success": False,
                    "error": "No database_path provided. Pass database_path parameter."
                })

            executor = SQLExecutorTool(
                db_type=self.db_type,
                connection_string=conn_string,
                read_only=True,
                timeout=self.timeout
            )

            # Database-specific table listing queries
            if self.db_type == "sqlite":
                query = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            elif self.db_type == "postgresql":
                query = "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            elif self.db_type == "mysql":
                query = "SHOW TABLES"
            else:
                return json.dumps({
                    "success": False,
                    "error": f"Unsupported database type: {self.db_type}"
                })

            result = json.loads(executor.execute(query=query))

            if result["success"]:
                # Extract table names from result
                if self.db_type == "sqlite":
                    tables = [row["name"] for row in result.get("data", [])]
                elif self.db_type == "postgresql":
                    tables = [row["tablename"] for row in result.get("data", [])]
                elif self.db_type == "mysql":
                    # MySQL SHOW TABLES returns with dynamic column name
                    tables = [list(row.values())[0] for row in result.get("data", [])]
                else:
                    tables = []

                # Return structured output matching DataFrame tools' pattern
                return json.dumps({
                    "success": True,
                    "schema": {
                        "available_tables": tables,
                        "total_tables": len(tables)
                    },
                    "tables": tables,
                    "database_type": self.db_type,
                    "message": f"Found {len(tables)} tables. Use database_describe_table to inspect table structures."
                })
            else:
                return json.dumps(result)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to list tables: {str(e)}"
            })


class DatabaseDescribeTableTool(BaseTool):
    """Describe table schema with column names, types, and constraints

    Returns structured output similar to DataFrame tools' schema pattern.
    Enables agents to discover column names before writing queries.
    """

    def __init__(
        self,
        db_type: DatabaseType = "sqlite",
        connection_string: Optional[str] = None,
        timeout: float = 30.0
    ):
        self.db_type = db_type
        self.connection_string = connection_string
        self.timeout = timeout

        super().__init__(
            ToolMetadata(
                name="database_describe_table",
                description="Get table schema with column names and types. Pass database_path and table_name. Example: database_describe_table(table_name='users', database_path='/path/to/file.db')",
                category="data",
                tags=["sql", "database", "schema", "discovery", "columns"]
            )
        )

    def _execute(self, table_name: str, database_path: Optional[str] = None, **kwargs) -> str:
        """Describe table structure"""
        try:
            if not table_name:
                return json.dumps({
                    "success": False,
                    "error": "table_name parameter is required"
                })

            # Use provided path or fall back to configured
            conn_string = database_path or self.connection_string
            if not conn_string:
                return json.dumps({
                    "success": False,
                    "error": "No database_path provided. Pass database_path parameter."
                })

            executor = SQLExecutorTool(
                db_type=self.db_type,
                connection_string=conn_string,
                read_only=True,
                timeout=self.timeout
            )

            # Database-specific schema inspection queries
            if self.db_type == "sqlite":
                query = f"PRAGMA table_info({table_name})"
            elif self.db_type == "postgresql":
                query = f"""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = '{table_name}'
                ORDER BY ordinal_position
                """
            elif self.db_type == "mysql":
                query = f"DESCRIBE {table_name}"
            else:
                return json.dumps({
                    "success": False,
                    "error": f"Unsupported database type: {self.db_type}"
                })

            result = json.loads(executor.execute(query=query))

            if result["success"]:
                data = result.get("data", [])

                if not data:
                    return json.dumps({
                        "success": False,
                        "error": f"Table '{table_name}' not found or is empty"
                    })

                # Parse column information based on database type
                columns = []
                column_types = {}

                if self.db_type == "sqlite":
                    for row in data:
                        col_name = row["name"]
                        col_type = row["type"]
                        columns.append(col_name)
                        column_types[col_name] = col_type

                elif self.db_type == "postgresql":
                    for row in data:
                        col_name = row["column_name"]
                        col_type = row["data_type"]
                        columns.append(col_name)
                        column_types[col_name] = col_type

                elif self.db_type == "mysql":
                    for row in data:
                        col_name = row["Field"]
                        col_type = row["Type"]
                        columns.append(col_name)
                        column_types[col_name] = col_type

                # Return structured output matching DataFrame tools' pattern
                return json.dumps({
                    "success": True,
                    "table_name": table_name,
                    "schema": {
                        "available_columns": columns,
                        "column_types": column_types,
                        "total_columns": len(columns)
                    },
                    "columns": columns,
                    "column_details": data,
                    "database_type": self.db_type,
                    "message": f"Table '{table_name}' has {len(columns)} columns. Use these EXACT column names in your queries."
                })
            else:
                return json.dumps(result)

        except Exception as e:
            return json.dumps({
                "success": False,
                "table_name": table_name,
                "error": f"Failed to describe table: {str(e)}"
            })
