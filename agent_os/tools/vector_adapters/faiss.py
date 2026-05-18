"""FAISS adapter implementation"""

from typing import List, Dict, Any, Optional
import hashlib
import pickle
import numpy as np
from pathlib import Path

from agent_os.tools.vector_adapters.base import VectorStoreAdapter


class FAISSAdapter(VectorStoreAdapter):
    """FAISS vector store adapter with metadata support"""

    def __init__(
        self,
        collection_name: str = "default",
        persist_directory: str = "./faiss_db",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        index_type: str = "Flat"
    ):
        """
        Initialize FAISS adapter

        Args:
            collection_name: Name of the collection
            persist_directory: Directory to persist index and metadata
            embedding_model: Sentence transformer model for embeddings
            index_type: FAISS index type ("Flat", "IVFFlat", "HNSW")
        """
        self.collection_name = collection_name
        self.persist_directory = Path(persist_directory)
        self.embedding_model = embedding_model
        self.index_type = index_type

        self._index = None
        self._encoder = None
        self._documents = []  # Store documents
        self._metadatas = []  # Store metadata
        self._ids = []  # Store IDs
        self._id_to_idx = {}  # Map ID to index position

        self._initialize()

    def _initialize(self):
        """Initialize FAISS index and embedding model"""
        try:
            import faiss
            from sentence_transformers import SentenceTransformer

            # Create persist directory
            self.persist_directory.mkdir(parents=True, exist_ok=True)

            # Initialize embedding model
            self._encoder = SentenceTransformer(self.embedding_model)
            vector_size = self._encoder.get_sentence_embedding_dimension()

            # Try to load existing index
            index_path = self.persist_directory / f"{self.collection_name}.index"
            metadata_path = self.persist_directory / f"{self.collection_name}.metadata.pkl"

            if index_path.exists() and metadata_path.exists():
                # Load existing index and metadata
                self._index = faiss.read_index(str(index_path))

                with open(metadata_path, 'rb') as f:
                    metadata = pickle.load(f)
                    self._documents = metadata['documents']
                    self._metadatas = metadata['metadatas']
                    self._ids = metadata['ids']
                    self._id_to_idx = metadata['id_to_idx']
            else:
                # Create new index
                if self.index_type == "Flat":
                    self._index = faiss.IndexFlatL2(vector_size)
                elif self.index_type == "IVFFlat":
                    quantizer = faiss.IndexFlatL2(vector_size)
                    self._index = faiss.IndexIVFFlat(quantizer, vector_size, 100)
                    # Train with dummy data
                    dummy_data = np.random.random((100, vector_size)).astype('float32')
                    self._index.train(dummy_data)
                elif self.index_type == "HNSW":
                    self._index = faiss.IndexHNSWFlat(vector_size, 32)
                else:
                    raise ValueError(f"Unsupported index type: {self.index_type}")

        except ImportError as e:
            if "faiss" in str(e):
                raise ImportError(
                    "faiss-cpu not installed. Install with: pip install faiss-cpu"
                )
            elif "sentence_transformers" in str(e):
                raise ImportError(
                    "sentence-transformers not installed. Install with: pip install sentence-transformers"
                )
            raise

    def _persist(self):
        """Save index and metadata to disk"""
        import faiss

        index_path = self.persist_directory / f"{self.collection_name}.index"
        metadata_path = self.persist_directory / f"{self.collection_name}.metadata.pkl"

        # Save FAISS index
        faiss.write_index(self._index, str(index_path))

        # Save metadata
        metadata = {
            'documents': self._documents,
            'metadatas': self._metadatas,
            'ids': self._ids,
            'id_to_idx': self._id_to_idx
        }

        with open(metadata_path, 'wb') as f:
            pickle.dump(metadata, f)

    def _reload_from_disk(self):
        """Reload index and metadata from disk"""
        import faiss

        index_path = self.persist_directory / f"{self.collection_name}.index"
        metadata_path = self.persist_directory / f"{self.collection_name}.metadata.pkl"

        if index_path.exists() and metadata_path.exists():
            # Load existing index and metadata
            self._index = faiss.read_index(str(index_path))

            with open(metadata_path, 'rb') as f:
                metadata = pickle.load(f)
                self._documents = metadata['documents']
                self._metadatas = metadata['metadatas']
                self._ids = metadata['ids']
                self._id_to_idx = metadata['id_to_idx']

    def add(
        self,
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Add documents to FAISS index"""
        # Generate embeddings
        embeddings = self._encoder.encode(documents)
        embeddings = np.array(embeddings).astype('float32')

        # Generate IDs if not provided
        if ids is None:
            ids = [hashlib.md5(doc.encode()).hexdigest()[:16] for doc in documents]

        # Prepare metadata
        if metadatas is None:
            metadatas = [{} for _ in documents]

        # Add to index
        start_idx = len(self._documents)
        self._index.add(embeddings)

        # Store documents, metadata, and IDs
        for i, (doc, metadata, doc_id) in enumerate(zip(documents, metadatas, ids)):
            idx = start_idx + i
            self._documents.append(doc)
            self._metadatas.append(metadata)
            self._ids.append(doc_id)
            self._id_to_idx[doc_id] = idx

        # Persist to disk
        self._persist()

        return {
            "success": True,
            "backend": "faiss",
            "collection": self.collection_name,
            "documents_stored": len(documents),
            "document_ids": ids,
            "persist_directory": str(self.persist_directory),
            "index_type": self.index_type
        }

    def search(
        self,
        query: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Search FAISS index for similar documents"""
        # Reload from disk to get latest data (in case another instance added documents)
        self._reload_from_disk()

        count = self.count()

        if count == 0:
            return {
                "success": True,
                "backend": "faiss",
                "collection": self.collection_name,
                "total_documents": 0,
                "results": []
            }

        # Generate query embedding
        query_vector = self._encoder.encode([query])[0]
        query_vector = np.array([query_vector]).astype('float32')

        # Search index
        distances, indices = self._index.search(query_vector, min(n_results * 2, count))

        # Format results with metadata filtering
        formatted_results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:  # FAISS returns -1 for empty slots
                continue

            # Apply metadata filter if provided
            if where:
                metadata = self._metadatas[idx]
                if not all(metadata.get(k) == v for k, v in where.items()):
                    continue

            # L2 distance to similarity score
            similarity = float(1 / (1 + dist))

            formatted_results.append({
                "id": self._ids[idx],
                "document": self._documents[idx],
                "metadata": self._metadatas[idx],
                "similarity_score": round(similarity, 4),
                "distance": round(float(dist), 4)
            })

            if len(formatted_results) >= n_results:
                break

        return {
            "success": True,
            "backend": "faiss",
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
        """
        Delete documents from FAISS index

        Note: FAISS doesn't support deletion directly, so we rebuild the index
        """
        import faiss

        count_before = self.count()

        # Determine indices to keep
        indices_to_delete = set()

        if ids:
            for doc_id in ids:
                if doc_id in self._id_to_idx:
                    indices_to_delete.add(self._id_to_idx[doc_id])

        if where:
            for idx, metadata in enumerate(self._metadatas):
                if all(metadata.get(k) == v for k, v in where.items()):
                    indices_to_delete.add(idx)

        if not indices_to_delete:
            return {
                "success": True,
                "backend": "faiss",
                "collection": self.collection_name,
                "documents_before": count_before,
                "documents_after": count_before,
                "documents_deleted": 0
            }

        # Keep non-deleted items
        keep_indices = [i for i in range(count_before) if i not in indices_to_delete]

        if not keep_indices:
            # Delete all - recreate empty index
            vector_size = self._encoder.get_sentence_embedding_dimension()
            if self.index_type == "Flat":
                self._index = faiss.IndexFlatL2(vector_size)
            self._documents = []
            self._metadatas = []
            self._ids = []
            self._id_to_idx = {}
        else:
            # Rebuild index with remaining items
            remaining_docs = [self._documents[i] for i in keep_indices]
            remaining_metas = [self._metadatas[i] for i in keep_indices]
            remaining_ids = [self._ids[i] for i in keep_indices]

            # Re-encode and rebuild
            embeddings = self._encoder.encode(remaining_docs)
            embeddings = np.array(embeddings).astype('float32')

            vector_size = self._encoder.get_sentence_embedding_dimension()
            if self.index_type == "Flat":
                self._index = faiss.IndexFlatL2(vector_size)

            self._index.add(embeddings)

            self._documents = remaining_docs
            self._metadatas = remaining_metas
            self._ids = remaining_ids
            self._id_to_idx = {doc_id: i for i, doc_id in enumerate(remaining_ids)}

        # Persist changes
        self._persist()

        count_after = self.count()

        return {
            "success": True,
            "backend": "faiss",
            "collection": self.collection_name,
            "documents_before": count_before,
            "documents_after": count_after,
            "documents_deleted": count_before - count_after
        }

    def count(self) -> int:
        """Get document count"""
        return self._index.ntotal

    def get_backend_name(self) -> str:
        """Get backend name"""
        return "faiss"
