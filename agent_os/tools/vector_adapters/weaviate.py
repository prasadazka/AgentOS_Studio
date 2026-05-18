"""Weaviate adapter implementation"""

from typing import List, Dict, Any, Optional
import hashlib

from agent_os.tools.vector_adapters.base import VectorStoreAdapter


class WeaviateAdapter(VectorStoreAdapter):
    """Weaviate vector store adapter"""

    def __init__(
        self,
        collection_name: str = "Default",
        url: str = "http://localhost:8080",
        api_key: Optional[str] = None
    ):
        """
        Initialize Weaviate adapter

        Args:
            collection_name: Name of the class (Weaviate uses PascalCase)
            url: Weaviate server URL
            api_key: Optional API key for authentication
        """
        # Weaviate uses PascalCase for class names
        self.collection_name = collection_name.capitalize()
        self.url = url
        self.api_key = api_key
        self._client = None
        self._initialize()

    def _initialize(self):
        """Initialize Weaviate client and class"""
        try:
            import weaviate
            from weaviate.classes.config import Configure, Property, DataType

            # Initialize client
            if self.api_key:
                self._client = weaviate.connect_to_custom(
                    http_host=self.url.replace("http://", "").replace("https://", ""),
                    http_port=8080,
                    http_secure=False,
                    auth_credentials=weaviate.auth.AuthApiKey(self.api_key)
                )
            else:
                self._client = weaviate.connect_to_local(
                    host=self.url.replace("http://", "").replace("https://", "").split(":")[0],
                    port=8080
                )

            # Create class if it doesn't exist
            if not self._client.collections.exists(self.collection_name):
                self._client.collections.create(
                    name=self.collection_name,
                    vectorizer_config=Configure.Vectorizer.text2vec_transformers(),
                    properties=[
                        Property(
                            name="document",
                            data_type=DataType.TEXT
                        )
                    ]
                )

        except ImportError:
            raise ImportError(
                "weaviate-client not installed. Install with: pip install weaviate-client"
            )

    def add(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Add documents to Weaviate"""
        import weaviate.classes as wvc

        collection = self._client.collections.get(self.collection_name)

        # Generate IDs if not provided
        if ids is None:
            ids = [hashlib.md5(doc.encode()).hexdigest()[:16] for doc in documents]

        # Prepare objects
        objects_to_insert = []
        for i, (doc, doc_id) in enumerate(zip(documents, ids)):
            properties = {"document": doc}

            # Add metadata as properties
            if metadatas and i < len(metadatas):
                # Flatten metadata into properties
                for key, value in metadatas[i].items():
                    properties[key] = str(value)  # Weaviate needs strings

            objects_to_insert.append(
                wvc.data.DataObject(
                    properties=properties,
                    uuid=wvc.config.UUID(doc_id)
                )
            )

        # Insert batch
        collection.data.insert_many(objects_to_insert)

        return {
            "success": True,
            "backend": "weaviate",
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
        """Search Weaviate for similar documents"""
        import weaviate.classes as wvc

        collection = self._client.collections.get(self.collection_name)
        count = self.count()

        if count == 0:
            return {
                "success": True,
                "backend": "weaviate",
                "collection": self.collection_name,
                "total_documents": 0,
                "results": []
            }

        # Build query
        query_params = {
            "query": query,
            "limit": min(n_results, count)
        }

        # Add filter if provided
        if where:
            filters = []
            for key, value in where.items():
                filters.append(
                    wvc.query.Filter.by_property(key).equal(str(value))
                )
            # Combine filters with AND
            if len(filters) == 1:
                query_params["filters"] = filters[0]
            else:
                combined_filter = filters[0]
                for f in filters[1:]:
                    combined_filter = combined_filter & f
                query_params["filters"] = combined_filter

        # Execute search
        response = collection.query.near_text(**query_params)

        # Format results
        formatted_results = []
        for obj in response.objects:
            properties = obj.properties
            document = properties.pop("document", "")

            # Distance to similarity (Weaviate uses cosine distance)
            distance = obj.metadata.distance if obj.metadata.distance else 0
            similarity = 1 - distance

            formatted_results.append({
                "id": str(obj.uuid),
                "document": document,
                "metadata": properties,
                "similarity_score": round(similarity, 4),
                "distance": round(distance, 4)
            })

        return {
            "success": True,
            "backend": "weaviate",
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
        """Delete documents from Weaviate"""
        import weaviate.classes as wvc

        collection = self._client.collections.get(self.collection_name)
        count_before = self.count()

        if ids:
            # Delete by IDs
            for doc_id in ids:
                try:
                    collection.data.delete_by_id(wvc.config.UUID(doc_id))
                except Exception:
                    pass  # ID might not exist

        elif where:
            # Delete by filter
            filters = []
            for key, value in where.items():
                filters.append(
                    wvc.query.Filter.by_property(key).equal(str(value))
                )

            # Combine filters
            if len(filters) == 1:
                combined_filter = filters[0]
            else:
                combined_filter = filters[0]
                for f in filters[1:]:
                    combined_filter = combined_filter & f

            collection.data.delete_many(where=combined_filter)

        count_after = self.count()

        return {
            "success": True,
            "backend": "weaviate",
            "collection": self.collection_name,
            "documents_before": count_before,
            "documents_after": count_after,
            "documents_deleted": count_before - count_after
        }

    def count(self) -> int:
        """Get document count"""
        collection = self._client.collections.get(self.collection_name)
        agg = collection.aggregate.over_all(total_count=True)
        return agg.total_count

    def get_backend_name(self) -> str:
        """Get backend name"""
        return "weaviate"
