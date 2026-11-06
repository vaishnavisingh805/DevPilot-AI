# Codebase RAG Implementation Guide: AST Chunking & Vector Intelligence

**Project:** Multi-Agent AI System for Autonomous Software Engineering  
**Workspace:** `D:\MultiAgent-Software-Engineering`  
**Phase:** Phase 2.1 — Git Tooling & Repository Intelligence  
**Component:** `core/rag/` and `agents/google_adk/rag_agent.py`  
**Authors:** Muskan Patni (230534) & Vaishnavi Singh (230508)

---

## 1. Overview and Purpose

Real-world software engineering requires agents to reason over an existing, complex codebase rather than generating isolated code snippets from scratch. The Codebase RAG (Retrieval-Augmented Generation) subsystem provides semantic repository intelligence to:
1. Parse codebases into AST-aware semantic units (classes, functions, methods, module docstrings).
2. Filter out noise, third-party libraries (`.venv`, `node_modules`), caches, binaries, and secrets (`.env`).
3. Store and index chunks in ChromaDB vector storage with zero duplicate re-indexing.
4. Retrieve the top-$k$ most relevant code snippets for a developer requirement using deterministic local embeddings.
5. Provide structured context to the CrewAI Planner and Google ADK Coder agents via the `RepositoryRAGAgent`.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CODEBASE RAG PIPELINE                            │
└─────────────────────────────────────────────────────────────────────────────┘
  Repository Files (on disk or in sandbox)
         │
         ▼
  [ASTCodeChunker]
         │  • Filters out .git, .venv, node_modules, .env, secrets
         │  • Parses Python files into AST syntax trees
         │  • Extracts: Module Overviews, Class definitions, Methods, Functions
         │  • Retains symbol hierarchy, line ranges, and docstrings
         ▼
  [Content Hashing & Deduplication]
         │  • Computes SHA-256 hash of each chunk content
         │  • Skips re-indexing unchanged chunks (0 duplicate overhead)
         ▼
  [DeterministicCodeEmbeddingFunction]
         │  • Tokenizes camelCase, snake_case, and code identifiers
         │  • Produces L2-normalized 128-dimensional dense vectors
         │  • 100% local: zero network downloads, zero Gemini API quota consumed
         ▼
  [ChromaDB Vector Store] (`sandbox_workspace/chroma_db/`)
         │
         ▼
  [RepositoryRAGAgent] (Google ADK)
         │  • Queries top-k semantic matches
         │  • Formats markdown context with line numbers and source links
         │  • Updates Shared Blackboard (`metadata['retrieved_context']`)
         ▼
  [Coding & Planning Agents] receive precise context before touching code
```

---

## 2. Component Reference

### 2.1 `core/rag/ast_chunker.py` (AST Code Chunker)
- **`ASTCodeChunker.should_index_file(path, repo_root) -> bool`**:
  Validates that a file qualifies for indexing:
  - Excludes directories: `.git`, `.venv`, `venv`, `node_modules`, `__pycache__`, `dist`, `build`, `.pytest_cache`.
  - Excludes secrets: `.env`, `.pem`, `.key`, `*secret*`, `*credential*`.
  - Supported extensions: `.py`, `.md`, `.json`, `.toml`, `.yaml`, `.txt`.
  - Max file size limit: 512 KB.
- **`ASTCodeChunker.chunk_python_source(code, rel_path) -> List[CodeChunk]`**:
  Uses `ast.parse()` to extract:
  - Top-level classes (`symbol_type="class"`)
  - Nested methods with parent symbol tracking (`symbol_type="method"`, `parent_symbol="ClassName"`)
  - Standalone functions (`symbol_type="function"`)
  - Module docstrings and import overviews (`symbol_type="module_overview"`)
- **`CodeChunk` schema**:
  - `chunk_id`: Deterministic identifier string
  - `file_path`: Relative file path within repository
  - `symbol_name`: Fully qualified symbol name (e.g. `AdvancedCalculator.standard_deviation`)
  - `symbol_type`: Type descriptor (`class`, `method`, `function`, `module_overview`)
  - `start_line` / `end_line`: Precise line numbers
  - `content`: Code block string
  - `content_hash`: SHA-256 digest of content

### 2.2 `core/rag/embeddings.py` (Deterministic Code Embeddings)
- Implements `chromadb.EmbeddingFunction[chromadb.Documents]`.
- Converts code tokens, identifier sub-words, and symbol keywords into 128-dimensional dense vectors.
- Applies feature hashing and L2 normalization via `numpy`.
- Eliminates external HuggingFace model downloads or third-party API dependencies.

### 2.3 `core/rag/vector_store.py` (ChromaDB Vector Store)
- Persistent client located at `sandbox_workspace/chroma_db/`.
- **`index_repository(repo_root, repo_id) -> Dict[str, Any]`**:
  - Performs incremental scanning and chunking.
  - Queries existing chunk IDs for the specified `repo_id`.
  - Compares content hashes: skips identical chunks (`chunks_skipped_duplicate`).
  - Batch upserts new or modified chunks with full metadata.
- **`query_codebase(query, repo_id=None, top_k=5, symbol_type=None) -> List[Dict[str, Any]]`**:
  - Semantic vector search returning ranked chunks with relevance score, file path, symbol name, and code.

### 2.4 `agents/google_adk/rag_agent.py` (`RepositoryRAGAgent`)
- Specialized Google ADK agent.
- Exposes `retrieve_context(query, repo_path, repo_id, top_k=5)`:
  - Auto-indexes repository if not yet present in vector store.
  - Formats retrieved chunks as clean markdown snippets.
  - Dispatches updates to the Shared Blackboard (`metadata['retrieved_context']`).
  - Responds to A2A envelopes (`TASK_DELEGATION` and `TOOL_PROXY_REQUEST`).

---

## 3. Usage Example

### Direct Context Retrieval
```python
from pathlib import Path
from agents.google_adk.rag_agent import RepositoryRAGAgent

agent = RepositoryRAGAgent()
repo_dir = Path("sandbox_workspace/sample_repo")

# Retrieve context for a developer requirement
context_res = agent.retrieve_context(
    query="standard deviation statistical calculation",
    repo_path=repo_dir,
    repo_id="sample_repo",
    top_k=3,
)

print(f"Retrieved {context_res['chunk_count']} relevant chunks.")
print(context_res["formatted_context"])
```

### FastMCP Tool Invocations
```python
from mcp_servers.repo_tool.client import mcp_repo_client

# Index sandbox repository into ChromaDB
index_res = mcp_repo_client.index_rag(run_id="run_test_01")
print(index_res["message"])

# Query indexed codebase via MCP
search_res = mcp_repo_client.query_rag(
    query="def compute_mean",
    run_id="run_test_01",
    top_k=2,
)
for r in search_res["results"]:
    print(f"- Found {r['symbol_name']} in {r['file_path']} (Score: {r['score']})")
```

---

## 4. Test Verification

Run all RAG and AST chunking tests:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_rag_indexing.py -v
```
All 5 tests verify:
- AST symbol extraction across classes, methods, functions.
- Automatic exclusion of `.git`, `.venv`, and `.env` secrets.
- Deduplication: re-indexing the same repository results in 0 newly inserted chunks.
- Semantic retrieval ranking of code chunks.
- `RepositoryRAGAgent` context synthesis and A2A envelope messaging.

