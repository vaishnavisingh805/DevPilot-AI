"""Unit tests for Codebase RAG Indexer, AST Chunker, and RepositoryRAGAgent."""

from pathlib import Path
import pytest

from core.rag.ast_chunker import ASTCodeChunker, CodeChunk
from core.rag.embeddings import DeterministicCodeEmbeddingFunction
from core.rag.vector_store import CodebaseVectorStore
from agents.google_adk.rag_agent import RepositoryRAGAgent
from core.a2a import A2AEnvelope, A2AMessageType


SAMPLE_PYTHON_CODE = '''"""Module level docstring for advanced math utilities."""

import math
from typing import List

PI_CONSTANT = 3.14159


class StatisticsCalculator:
    """Calculates summary statistics on numerical datasets."""

    def __init__(self, precision: int = 4):
        self.precision = precision

    def compute_mean(self, data: List[float]) -> float:
        """Computes arithmetic mean of numbers."""
        if not data:
            raise ValueError("Data cannot be empty")
        return round(sum(data) / len(data), self.precision)

    def compute_variance(self, data: List[float]) -> float:
        """Computes sample variance."""
        mean = self.compute_mean(data)
        return sum((x - mean) ** 2 for x in data) / (len(data) - 1)


def standalone_euclidean_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Computes straight-line distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
'''


def test_ast_chunker_extracts_symbols():
    chunker = ASTCodeChunker()
    chunks = chunker.chunk_python_source(SAMPLE_PYTHON_CODE, "src/stats.py")

    symbol_names = [c.symbol_name for c in chunks]
    symbol_types = [c.symbol_type for c in chunks]

    assert "module" in symbol_names
    assert "StatisticsCalculator" in symbol_names
    assert "StatisticsCalculator.compute_mean" in symbol_names
    assert "StatisticsCalculator.compute_variance" in symbol_names
    assert "standalone_euclidean_distance" in symbol_names

    assert "class" in symbol_types
    assert "method" in symbol_types
    assert "function" in symbol_types

    # Verify line bounds and parent hierarchy
    mean_chunk = next(c for c in chunks if c.symbol_name == "StatisticsCalculator.compute_mean")
    assert mean_chunk.parent_symbol == "StatisticsCalculator"
    assert mean_chunk.start_line > 0
    assert mean_chunk.end_line >= mean_chunk.start_line
    assert "Computes arithmetic mean of numbers." in (mean_chunk.docstring or "")


def test_ast_chunker_excludes_unwanted_files(tmp_path: Path):
    chunker = ASTCodeChunker()

    # Create directory structure
    (tmp_path / ".git").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "src").mkdir()

    # Create files
    git_file = tmp_path / ".git" / "config"
    git_file.write_text("[core]\n", encoding="utf-8")

    venv_file = tmp_path / ".venv" / "lib.py"
    venv_file.write_text("print('venv')", encoding="utf-8")

    env_file = tmp_path / ".env"
    env_file.write_text("SECRET_KEY=12345", encoding="utf-8")

    secret_key_file = tmp_path / "private_secret_key.pem"
    secret_key_file.write_text("CERT", encoding="utf-8")

    valid_py = tmp_path / "src" / "valid.py"
    valid_py.write_text("def hello(): pass\n", encoding="utf-8")

    assert chunker.should_index_file(git_file, tmp_path) is False
    assert chunker.should_index_file(venv_file, tmp_path) is False
    assert chunker.should_index_file(env_file, tmp_path) is False
    assert chunker.should_index_file(secret_key_file, tmp_path) is False
    assert chunker.should_index_file(valid_py, tmp_path) is True


def test_vector_store_indexing_and_deduplication(tmp_path: Path):
    store = CodebaseVectorStore(in_memory=True, collection_name="test_mem_rag")

    repo_dir = tmp_path / "repo1"
    repo_dir.mkdir()
    (repo_dir / "math_module.py").write_text(SAMPLE_PYTHON_CODE, encoding="utf-8")

    # 1. First indexing pass
    res1 = store.index_repository(repo_dir, repo_id="test_repo")
    assert res1["success"] is True
    assert res1["chunks_indexed"] > 0
    assert res1["chunks_skipped_duplicate"] == 0
    total_indexed = res1["chunks_indexed"]

    # 2. Second indexing pass without changes: all chunks should be skipped as duplicates!
    res2 = store.index_repository(repo_dir, repo_id="test_repo")
    assert res2["success"] is True
    assert res2["chunks_indexed"] == 0
    assert res2["chunks_skipped_duplicate"] == total_indexed

    # 3. Modify one function in file
    modified_code = SAMPLE_PYTHON_CODE.replace("def compute_variance", "def compute_sample_variance")
    (repo_dir / "math_module.py").write_text(modified_code, encoding="utf-8")

    # 4. Third pass: only modified chunks are updated
    res3 = store.index_repository(repo_dir, repo_id="test_repo")
    assert res3["success"] is True
    assert res3["chunks_indexed"] >= 1  # Updated chunk indexed


def test_vector_store_semantic_retrieval(tmp_path: Path):
    store = CodebaseVectorStore(in_memory=True, collection_name="test_search_rag")

    repo_dir = tmp_path / "repo_search"
    repo_dir.mkdir()
    (repo_dir / "calc.py").write_text(SAMPLE_PYTHON_CODE, encoding="utf-8")

    store.index_repository(repo_dir, repo_id="repo_calc")

    # Query for mean calculation
    results = store.query_codebase(query="compute mean average of dataset", repo_id="repo_calc", top_k=3)
    assert len(results) > 0
    top_result = results[0]
    assert "mean" in top_result["symbol_name"].lower() or "mean" in top_result["content"].lower()
    assert top_result["file_path"] == "calc.py"
    assert top_result["score"] >= 0.0


def test_repository_rag_agent_retrieve_context(tmp_path: Path):
    store = CodebaseVectorStore(in_memory=True, collection_name="test_agent_rag")
    repo_dir = tmp_path / "repo_agent"
    repo_dir.mkdir()
    (repo_dir / "calc.py").write_text(SAMPLE_PYTHON_CODE, encoding="utf-8")

    rag_agent = RepositoryRAGAgent(store=store)

    # Test direct context retrieval
    ret_res = rag_agent.retrieve_context(
        query="variance calculation",
        repo_path=repo_dir,
        repo_id="agent_repo_test",
        top_k=2,
    )
    assert ret_res["success"] is True
    assert ret_res["chunk_count"] > 0
    assert "Retrieved Codebase Context (RAG)" in ret_res["formatted_context"]

    # Test A2A message handling
    envelope = A2AEnvelope(
        sender_id="CrewAI:PlannerAgent",
        sender_framework="crewai",
        recipient_id=rag_agent.agent_id,
        message_type=A2AMessageType.TASK_DELEGATION,
        payload={"query": "mean computation", "repo_id": "agent_repo_test", "top_k": 1},
    )

    resp = rag_agent.handle_a2a_message(envelope)
    assert resp is not None
    assert resp.message_type == A2AMessageType.TASK_RESULT
    assert resp.payload.get("success") is True
    assert resp.payload.get("chunk_count") > 0

