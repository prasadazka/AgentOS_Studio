"""ChromaDB adapter implementation"""

from typing import List, Dict, Any, Optional
import hashlib

from agent_os.tools.vector_adapters.base import VectorStoreAdapter


class ChromaAdapter(VectorStoreAdapter):
    """ChromaDB vector store adapter"""

    def __init__(self, collection_name: str = "default", persist_directory: str = "./chroma_db"):
        """
        Initialize ChromaDB adapter

        Args:
            collection_name: Name of the collection
            persist_directory: Directory to persist data
        """
        self.collection_name = collection_name
        self.persist_directory = persist_directory
        self._collection = None
        self._initialize()

    def _initialize(self):
        """Initialize ChromaDB client and collection"""
        try:
            import chromadb
            from chromadb.config import Settings

            client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False)
            )

            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )

        except ImportError:
            raise ImportError(
                "chromadb not installed. Install with: pip install chromadb"
            )

    def add(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Add documents to ChromaDB"""
        # Generate IDs if not provided
        if ids is None:
            ids = [hashlib.md5(doc.encode()).hexdigest()[:16] for doc in documents]

        self._collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )

        return {
            "success": True,
            "backend": "chromadb",
            "collection": self.collection_name,
            "documents_stored": len(documents),
            "document_ids": ids,
            "persist_directory": self.persist_directory
        }

    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Search ChromaDB for similar documents"""
        count = self.count()

        if count == 0:
            return {
                "success": True,
                "backend": "chromadb",
                "collection": self.collection_name,
                "total_documents": 0,
                "results": []
            }

        # Build search parameters
        search_params = {
            "query_texts": [query],
            "n_results": min(n_results, count),
            "include": ["documents", "metadatas", "distances"]
        }

        if where:
            search_params["where"] = where

        results = self._collection.query(**search_params)

        # Format results
        formatted_results = []
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i]
            similarity = 1 - (distance / 2)  # Cosine distance to similarity

            formatted_results.append({
                "id": results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] or {},
                "similarity_score": round(similarity, 4),
                "distance": round(distance, 4)
            })

        return {
            "success": True,
            "backend": "chromadb",
            "collection": self.collection_name,
            "query": query,
            "total_documents": count,
            "results_returned": len(formatted_results),
            "results": formatted_results
        }

    def delete(
        self,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Delete documents from ChromaDB"""
        count_before = self.count()

        delete_params = {}
        if ids:
            delete_params["ids"] = ids
        if where:
            delete_params["where"] = where

        self._collection.delete(**delete_params)

        count_after = self.count()

        return {
            "success": True,
            "backend": "chromadb",
            "collection": self.collection_name,
            "documents_before": count_before,
            "documents_after": count_after,
            "documents_deleted": count_before - count_after
        }

    def count(self) -> int:
        """Get document count"""
        return self._collection.count()

    def get_backend_name(self) -> str:
        """Get backend name"""
        return "chromadb"
