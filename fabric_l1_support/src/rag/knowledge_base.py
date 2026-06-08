"""RAG knowledge base: index runbooks and past error resolutions."""
import json
import logging
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

COLLECTION_NAME = "fabric_runbooks"


class KnowledgeBase:
    """ChromaDB-backed vector store for runbooks and error patterns."""

    def __init__(self, db_path: str = "./data/chroma_db"):
        self._client = chromadb.PersistentClient(path=db_path)
        self._ef = embedding_functions.DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

    def index_runbooks(self, runbooks_dir: str = "./runbooks") -> int:
        """Index all .md and .json runbook files from directory."""
        path = Path(runbooks_dir)
        docs, ids, metadatas = [], [], []

        for file in path.glob("**/*.md"):
            content = file.read_text(encoding="utf-8")
            doc_id = f"runbook_{file.stem}"
            docs.append(content)
            ids.append(doc_id)
            metadatas.append({"source": str(file), "type": "runbook"})

        for file in path.glob("**/*.json"):
            data = json.loads(file.read_text(encoding="utf-8"))
            for i, entry in enumerate(data if isinstance(data, list) else [data]):
                doc_id = f"error_pattern_{file.stem}_{i}"
                content = json.dumps(entry)
                docs.append(content)
                ids.append(doc_id)
                metadatas.append({"source": str(file), "type": "error_pattern"})

        if docs:
            # Upsert to avoid duplicates on restart
            self._collection.upsert(documents=docs, ids=ids, metadatas=metadatas)
            logger.info(f"Indexed {len(docs)} documents into knowledge base.")

        return len(docs)

    def add_resolved_incident(
        self, error_message: str, root_cause: str, resolution: str, pipeline_name: str
    ):
        """Add a resolved incident to the KB for future reference."""
        import hashlib
        doc_id = "incident_" + hashlib.md5(error_message.encode()).hexdigest()[:12]
        document = (
            f"Pipeline: {pipeline_name}\n"
            f"Error: {error_message}\n"
            f"Root Cause: {root_cause}\n"
            f"Resolution: {resolution}"
        )
        self._collection.upsert(
            documents=[document],
            ids=[doc_id],
            metadatas=[{"source": "incident_history", "type": "resolved_incident"}],
        )

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        """Semantic search over the knowledge base."""
        results = self._collection.query(
            query_texts=[query],
            n_results=min(n_results, self._collection.count() or 1),
        )
        hits = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            hits.append({
                "content": doc,
                "source": meta.get("source", ""),
                "type": meta.get("type", ""),
                "relevance_score": round(1 - dist, 3),
            })
        return hits
