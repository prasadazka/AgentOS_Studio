"""Base adapter interface for vector databases"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple


class VectorStoreAdapter(ABC):
    """Abstract base class for vector database adapters"""

    @abstractmethod
    def add(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Add documents to vector store

        Args:
            documents: List of text documents
            metadatas: Optional metadata for each document
            ids: Optional custom IDs (auto-generated if not provided)

        Returns:
            Dict with success status and metadata
        """
        pass

    @abstractmethod
    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Search for similar documents

        Args:
            query: Search query text
            n_results: Number of results to return
            where: Optional metadata filter

        Returns:
            Dict with search results and similarity scores
        """
        pass

    @abstractmethod
    def delete(
        self,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Delete documents from vector store

        Args:
            ids: List of document IDs to delete
            where: Metadata filter for deletion

        Returns:
            Dict with deletion status
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """
        Get total number of documents in collection

        Returns:
            Number of documents
        """
        pass

    @abstractmethod
    def get_backend_name(self) -> str:
        """
        Get the name of the vector database backend

        Returns:
            Backend name (e.g., "chromadb", "qdrant", "weaviate", "faiss")
        """
        pass
