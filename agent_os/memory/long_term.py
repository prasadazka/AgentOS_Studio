"""
Long-term semantic memory using ChromaDB.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import SemanticMemory, MemoryItem


def _parse_timestamp(metadata: Dict, default: datetime = None) -> datetime:
    """Parse timestamp from metadata, returning default if invalid."""
    if default is None:
        default = datetime.now()
    ts = metadata.get("timestamp")
    if ts:
        try:
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            pass
    return default

# ChromaDB is optional - graceful fallback if not installed
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False


class LongTermMemory(SemanticMemory):
    """
    ChromaDB-backed semantic memory with embeddings.

    Features:
    - Semantic similarity search
    - Automatic embedding generation
    - Persistent storage
    - Metadata filtering
    - Configurable embedding models

    Example:
        memory = LongTermMemory(
            collection_name="agent_memory",
            persist_directory="~/.agent_os/memory/chroma"
        )
        memory.store_with_embedding(
            content="User asked about quantum computing",
            metadata={"topic": "physics", "agent": "ResearchBot"}
        )
        results = memory.search_similar("what is quantum entanglement?")
    """

    def __init__(
        self,
        collection_name: str = "agent_memory",
        persist_directory: Optional[str] = None,
        embedding_function: Optional[Any] = None
    ):
        """
        Initialize long-term memory.

        Args:
            collection_name: Name of ChromaDB collection
            persist_directory: Directory for persistent storage (None = in-memory)
            embedding_function: Custom embedding function (None = use default)
        """
        if not CHROMADB_AVAILABLE:
            raise ImportError(
                "ChromaDB is required for LongTermMemory. "
                "Install with: pip install chromadb"
            )

        self.collection_name = collection_name

        # Setup ChromaDB client
        if persist_directory:
            persist_path = Path(persist_directory).expanduser()
            persist_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(persist_path),
                settings=Settings(anonymized_telemetry=False)
            )
        else:
            self._client = chromadb.Client(
                settings=Settings(anonymized_telemetry=False)
            )

        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function,
            metadata={"hnsw:space": "cosine"}  # Use cosine similarity
        )

    def store_with_embedding(
        self,
        content: str,
        metadata: Optional[Dict] = None,
        embedding: Optional[List[float]] = None
    ) -> str:
        """
        Store content with its embedding vector.

        Args:
            content: Text content to store
            metadata: Optional metadata dict
            embedding: Pre-computed embedding (None = auto-generate)

        Returns:
            Document ID
        """
        doc_id = str(uuid.uuid4())
        metadata = metadata or {}

        # Add timestamp to metadata
        metadata["timestamp"] = datetime.now().isoformat()
        metadata["content_length"] = len(content)

        # Store with or without pre-computed embedding
        if embedding:
            self._collection.add(
                ids=[doc_id],
                documents=[content],
                metadatas=[metadata],
                embeddings=[embedding]
            )
        else:
            self._collection.add(
                ids=[doc_id],
                documents=[content],
                metadatas=[metadata]
            )

        return doc_id

    def search_similar(
        self,
        query: str,
        limit: int = 5,
        threshold: float = 0.0
    ) -> List[MemoryItem]:
        """
        Search for semantically similar items.

        Args:
            query: Search query
            limit: Max results
            threshold: Minimum similarity score (0-1, higher = more similar)

        Returns:
            List of MemoryItems with relevance scores
        """
        results = self._collection.query(
            query_texts=[query],
            n_results=limit,
            include=["documents", "metadatas", "distances"]
        )

        items = []
        if results and results['documents'] and results['documents'][0]:
            for i, doc in enumerate(results['documents'][0]):
                # ChromaDB returns distances, convert to similarity
                # For cosine distance: similarity = 1 - distance
                distance = results['distances'][0][i] if results['distances'] else 0
                similarity = 1 - distance

                # Apply threshold filter
                if similarity < threshold:
                    continue

                metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                doc_id = results['ids'][0][i] if results['ids'] else str(uuid.uuid4())

                items.append(MemoryItem(
                    id=doc_id,
                    content=doc,
                    content_type="text",
                    metadata=metadata,
                    timestamp=_parse_timestamp(metadata),
                    relevance_score=similarity
                ))

        return items

    def store(self, key: str, value: Any, metadata: Optional[Dict] = None) -> str:
        """Store a value with metadata"""
        content = str(value)
        metadata = metadata or {}

        # Add timestamp
        metadata["timestamp"] = datetime.now().isoformat()

        self._collection.add(
            ids=[key],
            documents=[content],
            metadatas=[metadata]
        )
        return key

    def retrieve(self, key: str) -> Optional[Any]:
        """Retrieve a document by ID"""
        results = self._collection.get(
            ids=[key],
            include=["documents", "metadatas"]
        )

        if results and results['documents'] and results['documents'][0]:
            return {
                "content": results['documents'][0],
                "metadata": results['metadatas'][0] if results['metadatas'] else {}
            }
        return None

    def search(self, query: str, limit: int = 10) -> List[MemoryItem]:
        """Search using semantic similarity"""
        return self.search_similar(query, limit=limit, threshold=0.0)

    def delete(self, key: str) -> bool:
        """Delete a document by ID."""
        try:
            self._collection.delete(ids=[key])
            return True
        except ValueError:
            return False

    def clear(self, older_than: Optional[datetime] = None) -> int:
        """
        Clear documents.

        Args:
            older_than: If provided, only clear documents before this time

        Returns:
            Number of documents cleared
        """
        if older_than is None:
            # Clear all - delete and recreate collection
            count = self._collection.count()
            self._client.delete_collection(self.collection_name)
            self._collection = self._client.create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            return count
        else:
            # Delete by timestamp filter
            # ChromaDB doesn't support direct timestamp filtering in delete
            # So we query and delete individually
            all_docs = self._collection.get(include=["metadatas"])
            count = 0

            if all_docs and all_docs['ids']:
                ids_to_delete = []
                for i, doc_id in enumerate(all_docs['ids']):
                    metadata = all_docs['metadatas'][i] if all_docs['metadatas'] else {}
                    doc_time = _parse_timestamp(metadata, default=datetime.max)
                    if doc_time < older_than:
                        ids_to_delete.append(doc_id)

                if ids_to_delete:
                    self._collection.delete(ids=ids_to_delete)
                    count = len(ids_to_delete)

            return count

    def count(self) -> int:
        """Get total number of documents"""
        return self._collection.count()

    def search_by_metadata(
        self,
        filters: Dict[str, Any],
        limit: int = 10
    ) -> List[MemoryItem]:
        """
        Search documents by metadata filters.

        Args:
            filters: Metadata filters (e.g., {"agent": "GitManager"})
            limit: Max results

        Returns:
            Matching documents as MemoryItems
        """
        # Build ChromaDB where clause
        where_clause = {}
        for key, value in filters.items():
            where_clause[key] = {"$eq": value}

        if not where_clause:
            return []

        results = self._collection.get(
            where=where_clause if len(where_clause) == 1 else {"$and": [
                {k: v} for k, v in where_clause.items()
            ]},
            limit=limit,
            include=["documents", "metadatas"]
        )

        items = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents']):
                metadata = results['metadatas'][i] if results['metadatas'] else {}
                items.append(MemoryItem(
                    id=results['ids'][i],
                    content=doc,
                    content_type="text",
                    metadata=metadata,
                    timestamp=_parse_timestamp(metadata)
                ))
        return items

    def get_all_documents(self, limit: int = 100) -> List[MemoryItem]:
        """Get all documents (limited)."""
        results = self._collection.get(limit=limit, include=["documents", "metadatas"])
        items = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents']):
                metadata = results['metadatas'][i] if results['metadatas'] else {}
                items.append(MemoryItem(
                    id=results['ids'][i],
                    content=doc,
                    content_type="text",
                    metadata=metadata,
                    timestamp=_parse_timestamp(metadata)
                ))
        return items

    def close(self) -> None:
        """Cleanup resources"""
        # ChromaDB handles cleanup automatically
        pass


# Convenience check for ChromaDB availability
def is_chromadb_available() -> bool:
    """Check if ChromaDB is installed"""
    return CHROMADB_AVAILABLE
