"""Production-grade vector database tools for semantic search and RAG"""

from typing import List, Dict, Any, Optional, Literal
from contextlib import contextmanager
import json
import time
import hashlib
from functools import wraps

from pydantic import BaseModel, Field, validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.tools.vector_adapters.base import VectorStoreAdapter
from agent_os.tools.vector_adapters.chroma import ChromaAdapter
from agent_os.tools.vector_adapters.qdrant import QdrantAdapter
from agent_os.tools.vector_adapters.weaviate import WeaviateAdapter
from agent_os.tools.vector_adapters.faiss import FAISSAdapter
from agent_os.utils.errors import (
    ToolExecutionError,
    ToolValidationError,
    DatabaseConnectionError,
    ErrorCode
)
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)

VectorBackend = Literal["chromadb", "qdrant", "weaviate", "faiss"]


# =============================================================================
# Type-Safe Models
# =============================================================================

class VectorStoreInput(BaseModel):
    """Type-safe vector store input"""
    documents: List[str] = Field(..., min_items=1)
    metadatas: Optional[List[Dict[str, Any]]] = None
    ids: Optional[List[str]] = None

    @validator('documents')
    def validate_documents(cls, v):
        if not v:
            raise ValueError("Documents list cannot be empty")
        if any(not doc or not doc.strip() for doc in v):
            raise ValueError("Documents cannot contain empty strings")
        return v

    @validator('metadatas')
    def validate_metadatas(cls, v, values):
        if v is not None and 'documents' in values:
            if len(v) != len(values['documents']):
                raise ValueError(
                    f"Metadata count ({len(v)}) must match document count ({len(values['documents'])})"
                )
        return v

    @validator('ids')
    def validate_ids(cls, v, values):
        if v is not None and 'documents' in values:
            if len(v) != len(values['documents']):
                raise ValueError(
                    f"ID count ({len(v)}) must match document count ({len(values['documents'])})"
                )
        return v


class VectorSearchInput(BaseModel):
    """Type-safe vector search input"""
    query: str = Field(..., min_length=1)
    n_results: int = Field(5, gt=0, le=100)
    where: Optional[Dict[str, Any]] = None

    @validator('query')
    def validate_query(cls, v):
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        return v


class VectorDeleteInput(BaseModel):
    """Type-safe vector delete input"""
    ids: Optional[List[str]] = Field(None, min_items=1)
    where: Optional[Dict[str, Any]] = None

    @validator('ids', 'where')
    def validate_at_least_one(cls, v, values):
        # At least one of ids or where must be provided
        if v is None and values.get('ids') is None and values.get('where') is None:
            raise ValueError("Must provide either 'ids' or 'where' filter")
        return v


class VectorOutput(BaseModel):
    """Type-safe vector operation output"""
    success: bool
    backend: str
    collection: str
    operation: str
    count: Optional[int] = None
    results: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Adapter Factory
# =============================================================================

class AdapterFactory:
    """Factory for creating vector database adapters"""

    @staticmethod
    def create(
        backend: VectorBackend,
        collection_name: str,
        **kwargs
    ) -> VectorStoreAdapter:
        """Create adapter with connection validation"""
        try:
            if backend == "chromadb":
                return ChromaAdapter(
                    collection_name=collection_name,
                    persist_directory=kwargs.get("persist_directory", "./chroma_db")
                )
            elif backend == "qdrant":
                return QdrantAdapter(
                    collection_name=collection_name,
                    url=kwargs.get("url", "http://localhost:6333"),
                    api_key=kwargs.get("api_key"),
                    embedding_model=kwargs.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
                )
            elif backend == "weaviate":
                return WeaviateAdapter(
                    collection_name=collection_name,
                    url=kwargs.get("url", "http://localhost:8080"),
                    api_key=kwargs.get("api_key")
                )
            elif backend == "faiss":
                return FAISSAdapter(
                    collection_name=collection_name,
                    persist_directory=kwargs.get("persist_directory", "./faiss_db"),
                    embedding_model=kwargs.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2"),
                    index_type=kwargs.get("index_type", "Flat")
                )
            else:
                raise ToolValidationError(
                    f"Unsupported backend: {backend}",
                    field_name="backend",
                    expected_type="chromadb, qdrant, weaviate, or faiss"
                )
        except Exception as e:
            if isinstance(e, ToolValidationError):
                raise
            raise DatabaseConnectionError(
                f"Failed to create {backend} adapter",
                details={"backend": backend, "error": str(e)}
            ) from e


# =============================================================================
# Retry Decorator
# =============================================================================

def retry_with_backoff(max_attempts=3, initial_delay=1.0, max_delay=30.0, base=2.0):
    """Retry vector operations with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except (ConnectionError, TimeoutError) as e:
                    if attempt < max_attempts:
                        logger.warning(
                            f"Vector operation failed, retrying {attempt}/{max_attempts}",
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
# Production-Grade Vector Tools
# =============================================================================

class VectorStoreTool(BaseTool):
    """Production-grade vector storage with connection management

    Features:
    - Context managers (guaranteed cleanup)
    - Pydantic validation
    - Retry logic for network backends
    - Structured error handling
    - Connection pooling support
    """

    def __init__(
        self,
        backend: VectorBackend = "chromadb",
        collection_name: str = "default",
        max_retries: int = 3,
        **backend_kwargs
    ):
        self.backend = backend
        self.collection_name = collection_name
        self.max_retries = max_retries
        self.backend_kwargs = backend_kwargs

        super().__init__(
            ToolMetadata(
                name="vector_store",
                description=f"Store documents with embeddings in {backend} vector database. Production-grade with retry logic and validation.",
                category="data",
                tags=["vector", "embedding", "storage", "rag", backend]
            )
        )

    @contextmanager
    def _get_adapter(self):
        """Context manager - guaranteed adapter cleanup"""
        adapter = None
        try:
            logger.info("Creating vector adapter", extra={
                "backend": self.backend,
                "collection": self.collection_name
            })
            adapter = AdapterFactory.create(
                self.backend,
                self.collection_name,
                **self.backend_kwargs
            )
            yield adapter
        finally:
            if adapter and hasattr(adapter, 'close'):
                try:
                    adapter.close()
                    logger.info("Vector adapter closed", extra={
                        "backend": self.backend
                    })
                except Exception as e:
                    logger.error("Error closing adapter", exc_info=True)

    @retry_with_backoff(max_attempts=3)
    def _store_with_retry(self, adapter, documents, metadatas, ids):
        """Store documents with retry logic"""
        return adapter.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

    def _execute(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None
    ) -> str:
        """Store documents in vector database

        Args:
            documents: List of text documents to store
            metadatas: Optional metadata for each document
            ids: Optional custom IDs (auto-generated if not provided)

        Returns:
            JSON with VectorOutput schema
        """
        start_time = time.time()
        doc_hash = hashlib.sha256(str(documents[:1]).encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = VectorStoreInput(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )

            logger.info("Storing documents in vector DB", extra={
                "backend": self.backend,
                "collection": self.collection_name,
                "doc_count": len(validated.documents),
                "doc_hash": doc_hash
            })

            # Store with context manager
            with self._get_adapter() as adapter:
                result = self._store_with_retry(
                    adapter,
                    validated.documents,
                    validated.metadatas,
                    validated.ids
                )

            duration = time.time() - start_time
            output = VectorOutput(
                success=result.get("success", False),
                backend=self.backend,
                collection=self.collection_name,
                operation="store",
                count=len(validated.documents),
                metadata={
                    "duration_seconds": round(duration, 3),
                    "sample_metadata": validated.metadatas[0] if validated.metadatas else None
                }
            )

            if not result.get("success"):
                output.error = result.get("error", "Unknown error")
                output.error_code = ErrorCode.DB_QUERY_ERROR.value

            logger.info("Documents stored", extra={
                "backend": self.backend,
                "duration": duration,
                "count": len(validated.documents),
                "status": "success" if output.success else "failed"
            })

            return output.to_json()

        except ToolValidationError as e:
            logger.error("Validation failed", extra={"doc_hash": doc_hash}, exc_info=True)
            return VectorOutput(
                success=False,
                backend=self.backend,
                collection=self.collection_name,
                operation="store",
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except DatabaseConnectionError as e:
            logger.error("Connection failed", extra={"backend": self.backend}, exc_info=True)
            return VectorOutput(
                success=False,
                backend=self.backend,
                collection=self.collection_name,
                operation="store",
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"backend": self.backend}, exc_info=True)
            return VectorOutput(
                success=False,
                backend=self.backend,
                collection=self.collection_name,
                operation="store",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class VectorSearchTool(BaseTool):
    """Production-grade vector search with retry and validation"""

    def __init__(
        self,
        backend: VectorBackend = "chromadb",
        collection_name: str = "default",
        max_retries: int = 3,
        **backend_kwargs
    ):
        self.backend = backend
        self.collection_name = collection_name
        self.max_retries = max_retries
        self.backend_kwargs = backend_kwargs

        super().__init__(
            ToolMetadata(
                name="vector_search",
                description=f"Search {backend} vector database for similar documents. Returns ranked results with scores.",
                category="data",
                tags=["vector", "search", "semantic", "rag", "retrieval", backend]
            )
        )

    @contextmanager
    def _get_adapter(self):
        """Context manager - guaranteed adapter cleanup"""
        adapter = None
        try:
            adapter = AdapterFactory.create(
                self.backend,
                self.collection_name,
                **self.backend_kwargs
            )
            yield adapter
        finally:
            if adapter and hasattr(adapter, 'close'):
                try:
                    adapter.close()
                except Exception as e:
                    logger.error("Error closing adapter", exc_info=True)

    @retry_with_backoff(max_attempts=3)
    def _search_with_retry(self, adapter, query, n_results, where):
        """Search with retry logic"""
        return adapter.search(
            query=query,
            n_results=n_results,
            where=where
        )

    def _execute(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None
    ) -> str:
        """Search for similar documents

        Args:
            query: Search query text
            n_results: Number of results to return (default: 5, max: 100)
            where: Optional metadata filter

        Returns:
            JSON with VectorOutput schema
        """
        start_time = time.time()
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = VectorSearchInput(
                query=query,
                n_results=n_results,
                where=where
            )

            logger.info("Searching vector DB", extra={
                "backend": self.backend,
                "collection": self.collection_name,
                "query_hash": query_hash,
                "n_results": validated.n_results,
                "has_filter": bool(where)
            })

            # Search with context manager
            with self._get_adapter() as adapter:
                result = self._search_with_retry(
                    adapter,
                    validated.query,
                    validated.n_results,
                    validated.where
                )

            duration = time.time() - start_time
            output = VectorOutput(
                success=result.get("success", False),
                backend=self.backend,
                collection=self.collection_name,
                operation="search",
                count=result.get("count", 0),
                results=result.get("results"),
                metadata={
                    "duration_seconds": round(duration, 3),
                    "query_hash": query_hash,
                    "n_results": validated.n_results,
                    "filter_applied": validated.where
                }
            )

            if not result.get("success"):
                output.error = result.get("error", "Unknown error")
                output.error_code = ErrorCode.DB_QUERY_ERROR.value

            logger.info("Search completed", extra={
                "backend": self.backend,
                "duration": duration,
                "results_count": output.count,
                "status": "success" if output.success else "failed"
            })

            return output.to_json()

        except ToolValidationError as e:
            logger.error("Validation failed", extra={"query_hash": query_hash}, exc_info=True)
            return VectorOutput(
                success=False,
                backend=self.backend,
                collection=self.collection_name,
                operation="search",
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except DatabaseConnectionError as e:
            logger.error("Connection failed", extra={"backend": self.backend}, exc_info=True)
            return VectorOutput(
                success=False,
                backend=self.backend,
                collection=self.collection_name,
                operation="search",
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"backend": self.backend}, exc_info=True)
            return VectorOutput(
                success=False,
                backend=self.backend,
                collection=self.collection_name,
                operation="search",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class VectorDeleteTool(BaseTool):
    """Production-grade vector deletion with validation"""

    def __init__(
        self,
        backend: VectorBackend = "chromadb",
        collection_name: str = "default",
        max_retries: int = 3,
        **backend_kwargs
    ):
        self.backend = backend
        self.collection_name = collection_name
        self.max_retries = max_retries
        self.backend_kwargs = backend_kwargs

        super().__init__(
            ToolMetadata(
                name="vector_delete",
                description=f"Delete documents from {backend} vector database by IDs or metadata filter.",
                category="data",
                tags=["vector", "delete", "cleanup", backend]
            )
        )

    @contextmanager
    def _get_adapter(self):
        """Context manager - guaranteed adapter cleanup"""
        adapter = None
        try:
            adapter = AdapterFactory.create(
                self.backend,
                self.collection_name,
                **self.backend_kwargs
            )
            yield adapter
        finally:
            if adapter and hasattr(adapter, 'close'):
                try:
                    adapter.close()
                except Exception as e:
                    logger.error("Error closing adapter", exc_info=True)

    @retry_with_backoff(max_attempts=3)
    def _delete_with_retry(self, adapter, ids, where):
        """Delete with retry logic"""
        return adapter.delete(ids=ids, where=where)

    def _execute(
        self,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None
    ) -> str:
        """Delete documents from vector database

        Args:
            ids: List of document IDs to delete
            where: Metadata filter for deletion

        Returns:
            JSON with VectorOutput schema
        """
        start_time = time.time()

        try:
            # Validate input
            validated = VectorDeleteInput(ids=ids, where=where)

            logger.info("Deleting from vector DB", extra={
                "backend": self.backend,
                "collection": self.collection_name,
                "id_count": len(validated.ids) if validated.ids else 0,
                "has_filter": bool(where)
            })

            # Delete with context manager
            with self._get_adapter() as adapter:
                result = self._delete_with_retry(
                    adapter,
                    validated.ids,
                    validated.where
                )

            duration = time.time() - start_time
            output = VectorOutput(
                success=result.get("success", False),
                backend=self.backend,
                collection=self.collection_name,
                operation="delete",
                count=result.get("count", 0),
                metadata={
                    "duration_seconds": round(duration, 3),
                    "deleted_ids": validated.ids,
                    "filter_applied": validated.where
                }
            )

            if not result.get("success"):
                output.error = result.get("error", "Unknown error")
                output.error_code = ErrorCode.DB_QUERY_ERROR.value

            logger.info("Deletion completed", extra={
                "backend": self.backend,
                "duration": duration,
                "count": output.count,
                "status": "success" if output.success else "failed"
            })

            return output.to_json()

        except ToolValidationError as e:
            logger.error("Validation failed", exc_info=True)
            return VectorOutput(
                success=False,
                backend=self.backend,
                collection=self.collection_name,
                operation="delete",
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except DatabaseConnectionError as e:
            logger.error("Connection failed", extra={"backend": self.backend}, exc_info=True)
            return VectorOutput(
                success=False,
                backend=self.backend,
                collection=self.collection_name,
                operation="delete",
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("Unexpected error", extra={"backend": self.backend}, exc_info=True)
            return VectorOutput(
                success=False,
                backend=self.backend,
                collection=self.collection_name,
                operation="delete",
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
