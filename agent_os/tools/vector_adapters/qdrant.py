"""Qdrant adapter implementation"""

from typing import List, Dict, Any, Optional
import hashlib
import uuid

from agent_os.tools.vector_adapters.base import VectorStoreAdapter


class QdrantAdapter(VectorStoreAdapter):
    """Qdrant vector store adapter"""

    def __init__(
        self,
        collection_name: str = "default",
        url: str = "http://localhost:6333",
        api_key: Optional[str] = None,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    ):
        """
        Initialize Qdrant adapter

        Args:
            collection_name: Name of the collection
            url: Qdrant server URL
            api_key: Optional API key for authentication
            embedding_model: Sentence transformer model for embeddings
        """
        self.collection_name = collection_name
        self.url = url
        self.api_key = api_key
        self.embedding_model = embedding_model
        self._client = None
        self._encoder = None
        self._initialize()

    def _initialize(self):
        """Initialize Qdrant client and collection"""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
            from sentence_transformers import SentenceTransformer

            # Initialize client
            self._client = QdrantClient(
                url=self.url,
                api_key=self.api_key
            )

            # Initialize embedding model
            self._encoder = SentenceTransformer(self.embedding_model)
            vector_size = self._encoder.get_sentence_embedding_dimension()

            # Create collection if it doesn't exist
            collections = self._client.get_collections().collections
            if not any(c.name == self.collection_name for c in collections):
                self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=vector_size,
                        distance=Distance.COSINE
                    )
                )

        except ImportError as e:
            if "qdrant_client" in str(e):
                raise ImportError(
                    "qdrant-client not installed. Install with: pip install qdrant-client"
                )
            elif "sentence_transformers" in str(e):
                raise ImportError(
                    "sentence-transformers not installed. Install with: pip install sentence-transformers"
                )
            raise

    def add(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Add documents to Qdrant"""
        from qdrant_client.models import PointStruct

        # Generate embeddings
        embeddings = self._encoder.encode(documents).tolist()

        # Generate IDs if not provided
        if ids is None:
            ids = [hashlib.md5(doc.encode()).hexdigest()[:16] for doc in documents]

        # Prepare points
        points = []
        for i, (doc, embedding, doc_id) in enumerate(zip(documents, embeddings, ids)):
            payload = {"document": doc}
            if metadatas and i < len(metadatas):
                payload.update(metadatas[i])

            points.append(
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id)),
                    vector=embedding,
                    payload=payload
                )
            )

        # Upsert points
        self._client.upsert(
            collection_name=self.collection_name,
            points=points
        )

        return {
            "success": True,
            "backend": "qdrant",
            "collection": self.collection_name,
            "documents_stored": len(documents),
            "document_ids": ids,
            "url": self.url
        }

    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Search Qdrant for similar documents"""
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        count = self.count()

        if count == 0:
            return {
                "success": True,
                "backend": "qdrant",
                "collection": self.collection_name,
                "total_documents": 0,
                "results": []
            }

        # Generate query embedding
        query_vector = self._encoder.encode([query])[0].tolist()

        # Build filter
        search_filter = None
        if where:
            conditions = []
            for key, value in where.items():
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )
            search_filter = Filter(must=conditions)

        # Search
        results = self._client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=min(n_results, count),
            query_filter=search_filter
        )

        # Format results
        formatted_results = []
        for hit in results:
            payload = hit.payload
            document = payload.pop("document", "")

            formatted_results.append({
                "id": str(hit.id),
                "document": document,
                "metadata": payload,
                "similarity_score": round(hit.score, 4),
                "distance": round(1 - hit.score, 4)
            })

        return {
            "success": True,
            "backend": "qdrant",
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
        """Delete documents from Qdrant"""
        from qdrant_client.models import Filter, FieldCondition, MatchValue, PointIdsList

        count_before = self.count()

        if ids:
            # Convert string IDs to UUIDs
            point_ids = [str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id)) for doc_id in ids]
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=point_ids)
            )
        elif where:
            # Delete by filter
            conditions = []
            for key, value in where.items():
                conditions.append(
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                )
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(must=conditions)
            )

        count_after = self.count()

        return {
            "success": True,
            "backend": "qdrant",
            "collection": self.collection_name,
            "documents_before": count_before,
            "documents_after": count_after,
            "documents_deleted": count_before - count_after
        }

    def count(self) -> int:
        """Get document count"""
        info = self._client.get_collection(collection_name=self.collection_name)
        return info.points_count

    def get_backend_name(self) -> str:
        """Get backend name"""
        return "qdrant"
