"""ChromaDB Vector Store Manager for Repository Intelligence & Semantic Code Search.

Maintains persistent or in-memory vector collections, enforces deduplication
via content hashing, and provides top-k relevance retrieval for agent planning.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import chromadb

from config.settings import settings
from core.rag.ast_chunker import ASTCodeChunker, CodeChunk, ast_chunker
from core.rag.embeddings import DeterministicCodeEmbeddingFunction, code_embedding_function


DEFAULT_CHROMA_DIR = settings.SANDBOX_ROOT / "chroma_db"
DEFAULT_COLLECTION_NAME = "codebase_rag"


class CodebaseVectorStore:
    """Encapsulates ChromaDB operations for indexing and semantic code retrieval."""

    def __init__(
        self,
        persist_directory: Optional[Path] = None,
        in_memory: bool = False,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        chunker: Optional[ASTCodeChunker] = None,
    ):
        self.persist_dir = Path(persist_directory or DEFAULT_CHROMA_DIR).resolve()
        self.collection_name = collection_name
        self.chunker = chunker or ast_chunker
        self.in_memory = in_memory

        if in_memory:
            self.client = chromadb.Client()
        else:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(self.persist_dir))

        self.embedding_function = code_embedding_function
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
            metadata={"description": "AST-indexed codebase semantic chunks"},
        )

    def index_repository(
        self,
        repo_root: Path,
        repo_id: str = "default_repo",
    ) -> Dict[str, Any]:
        """Scans, parses, and indexes a repository with incremental deduplication.

        Args:
            repo_root: Path to repository on disk.
            repo_id: Canonical repository identifier or URL slug.

        Returns:
            Summary of scanned files, indexed chunks, and skipped duplicates.
        """
        repo_root = Path(repo_root).resolve()
        if not repo_root.exists():
            return {
                "success": False,
                "error": f"Repository directory '{repo_root}' does not exist.",
            }

        chunks = self.chunker.scan_and_chunk_repository(repo_root)
        if not chunks:
            return {
                "success": True,
                "repo_id": repo_id,
                "total_chunks_scanned": 0,
                "chunks_indexed": 0,
                "chunks_skipped_duplicate": 0,
                "message": "No qualifying code files found to index.",
            }

        # Retrieve existing chunk metadata for this repository to avoid redundant inserts
        existing = self.collection.get(
            where={"repo_id": repo_id},
            include=["metadatas"],
        )
        existing_hashes: Dict[str, str] = {}
        if existing and existing.get("ids"):
            for c_id, meta in zip(existing["ids"], existing["metadatas"]):
                existing_hashes[c_id] = meta.get("content_hash", "")

        ids_to_add: List[str] = []
        docs_to_add: List[str] = []
        metas_to_add: List[Dict[str, Any]] = []
        skipped_count = 0

        for chunk in chunks:
            c_id = f"{repo_id}::{chunk.chunk_id}"
            # Deduplication check: skip if chunk already indexed with identical content hash
            if c_id in existing_hashes and existing_hashes[c_id] == chunk.content_hash:
                skipped_count += 1
                continue

            # Rich text for semantic indexing includes symbol name and docstrings
            embed_text = (
                f"File: {chunk.file_path}\n"
                f"Symbol: {chunk.symbol_name} ({chunk.symbol_type})\n"
                f"{chunk.docstring or ''}\n\n"
                f"{chunk.content}"
            )

            ids_to_add.append(c_id)
            docs_to_add.append(embed_text)
            metas_to_add.append({
                "repo_id": repo_id,
                "chunk_id": chunk.chunk_id,
                "file_path": chunk.file_path,
                "symbol_name": chunk.symbol_name,
                "symbol_type": chunk.symbol_type,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content_hash": chunk.content_hash,
                "language": chunk.language,
                "parent_symbol": chunk.parent_symbol or "",
                "raw_content": chunk.content,
            })

        if ids_to_add:
            # Batch upsert into Chroma
            self.collection.upsert(
                ids=ids_to_add,
                documents=docs_to_add,
                metadatas=metas_to_add,
            )

        return {
            "success": True,
            "repo_id": repo_id,
            "total_chunks_scanned": len(chunks),
            "chunks_indexed": len(ids_to_add),
            "chunks_skipped_duplicate": skipped_count,
            "total_collection_count": self.collection.count(),
            "message": f"Indexed {len(ids_to_add)} chunks ({skipped_count} skipped duplicates)",
        }

    def query_codebase(
        self,
        query: str,
        repo_id: Optional[str] = None,
        top_k: int = 5,
        symbol_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Queries the vector store for top-k semantically relevant code chunks.

        Args:
            query: Natural language requirement or code symbol query.
            repo_id: Optional repository filter.
            top_k: Maximum number of chunks to return.
            symbol_type: Optional filter ('class', 'method', 'function').

        Returns:
            Ranked list of chunk dictionaries with scores and source metadata.
        """
        where_clause: Dict[str, Any] = {}
        if repo_id and symbol_type:
            where_clause = {"$and": [{"repo_id": repo_id}, {"symbol_type": symbol_type}]}
        elif repo_id:
            where_clause = {"repo_id": repo_id}
        elif symbol_type:
            where_clause = {"symbol_type": symbol_type}

        query_kwargs: Dict[str, Any] = {
            "query_texts": [query],
            "n_results": max(1, top_k),
            "include": ["metadatas", "documents", "distances"],
        }
        if where_clause:
            query_kwargs["where"] = where_clause

        try:
            results = self.collection.query(**query_kwargs)
        except Exception:
            return []

        formatted: List[Dict[str, Any]] = []
        if not results or not results.get("ids") or not results["ids"][0]:
            return formatted

        ids = results["ids"][0]
        metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)
        distances = results["distances"][0] if results.get("distances") else [0.0] * len(ids)

        for c_id, meta, dist in zip(ids, metadatas, distances):
            # Convert cosine distance to approximate similarity score
            score = round(max(0.0, 1.0 - float(dist)), 4)
            formatted.append({
                "chunk_id": meta.get("chunk_id", c_id),
                "file_path": meta.get("file_path", "unknown"),
                "symbol_name": meta.get("symbol_name", "unnamed"),
                "symbol_type": meta.get("symbol_type", "unknown"),
                "start_line": meta.get("start_line", 1),
                "end_line": meta.get("end_line", 1),
                "content": meta.get("raw_content", ""),
                "score": score,
                "language": meta.get("language", "python"),
                "parent_symbol": meta.get("parent_symbol", ""),
            })

        return formatted

    def get_index_stats(self, repo_id: Optional[str] = None) -> Dict[str, Any]:
        """Returns statistics on the indexed collection."""
        where = {"repo_id": repo_id} if repo_id else None
        data = self.collection.get(where=where, include=["metadatas"]) if where else self.collection.get(include=["metadatas"])
        total_chunks = len(data["ids"]) if data and data.get("ids") else 0

        files: set = set()
        symbol_counts: Dict[str, int] = {}

        if data and data.get("metadatas"):
            for m in data["metadatas"]:
                files.add(m.get("file_path", ""))
                stype = m.get("symbol_type", "other")
                symbol_counts[stype] = symbol_counts.get(stype, 0) + 1

        return {
            "total_chunks": total_chunks,
            "unique_files": len(files),
            "symbol_breakdown": symbol_counts,
        }

    def clear(self) -> None:
        """Empties the current collection."""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
        )


# Global vector store singleton
vector_store = CodebaseVectorStore()

