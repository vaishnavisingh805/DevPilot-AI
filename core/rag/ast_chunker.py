"""AST-Aware Source Code Chunker for Repository RAG Indexing.

Extracts semantic code blocks (classes, functions, methods, module docstrings)
preserving structural hierarchy, line bounds, and symbol metadata while excluding
caches, secrets, and binary files.
"""

import ast
import hashlib
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple
from pydantic import BaseModel, Field


# Standard paths and patterns to strictly ignore
IGNORED_DIRECTORIES: Set[str] = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".eggs",
}

# Sensitive files to exclude from indexing
EXCLUDED_FILE_PATTERNS: Set[str] = {
    ".env",
    ".env.example",
    "id_rsa",
    "id_ed25519",
}

# File extensions supported for indexing
SUPPORTED_CODE_EXTENSIONS: Set[str] = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".html",
    ".css",
    ".md",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".txt",
    ".sql",
    ".sh",
    ".ps1",
}

MAX_FILE_SIZE_BYTES = 512 * 1024  # 512 KB


class CodeChunk(BaseModel):
    """Represents a discrete semantic chunk of code with provenance metadata."""

    chunk_id: str = Field(description="Unique deterministic ID (hash of content and path)")
    file_path: str = Field(description="Relative path of file within repository")
    symbol_name: str = Field(description="Name of class, function, or module context")
    symbol_type: str = Field(description="class, function, method, or module_overview")
    start_line: int
    end_line: int
    content: str
    content_hash: str
    language: str = "python"
    parent_symbol: Optional[str] = None
    docstring: Optional[str] = None


def compute_content_hash(text: str) -> str:
    """Computes SHA-256 digest of normalized chunk text."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


class ASTCodeChunker:
    """Parses codebases into semantic, AST-aware chunks."""

    def __init__(self, max_file_size: int = MAX_FILE_SIZE_BYTES):
        self.max_file_size = max_file_size

    def should_index_file(self, file_path: Path, repo_root: Path) -> bool:
        """Determines whether a file qualifies for indexing."""
        try:
            rel_path = file_path.relative_to(repo_root)
        except ValueError:
            return False

        # Check ignored directory names
        for part in rel_path.parts[:-1]:
            if part in IGNORED_DIRECTORIES or part.endswith(".egg-info"):
                return False

        # Check sensitive file names
        file_name = file_path.name.lower()
        if file_name in EXCLUDED_FILE_PATTERNS or file_name.startswith(".env"):
            return False
        if any(sec in file_name for sec in ["secret", "credential", "private_key", ".pem", ".key"]):
            return False

        # Check extension
        ext = file_path.suffix.lower()
        if ext not in SUPPORTED_CODE_EXTENSIONS:
            return False

        # Check file size
        try:
            if file_path.stat().st_size > self.max_file_size:
                return False
        except OSError:
            return False

        return True

    def chunk_python_source(self, code: str, rel_path: str) -> List[CodeChunk]:
        """Parses Python source code into AST chunks (modules, classes, methods, functions)."""
        chunks: List[CodeChunk] = []
        lines = code.splitlines(keepends=True)

        try:
            tree = ast.parse(code, filename=rel_path)
        except SyntaxError:
            # Fallback to line-window chunking if AST parsing fails on syntax errors
            return self._chunk_fallback_text(code, rel_path, language="python")

        # 1. Module-level overview & docstring
        module_doc = ast.get_docstring(tree)
        overview_lines = []
        for i, line in enumerate(lines[:35]):
            overview_lines.append(line)
        overview_content = "".join(overview_lines).strip()
        if overview_content:
            c_hash = compute_content_hash(overview_content)
            chunks.append(
                CodeChunk(
                    chunk_id=f"{rel_path}::module_overview::{c_hash[:8]}",
                    file_path=rel_path,
                    symbol_name="module",
                    symbol_type="module_overview",
                    start_line=1,
                    end_line=min(35, len(lines)),
                    content=overview_content,
                    content_hash=c_hash,
                    language="python",
                    docstring=module_doc,
                )
            )

        # 2. Iterate AST top-level nodes
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                chunks.extend(self._extract_class_chunks(node, lines, rel_path))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunks.append(self._extract_function_chunk(node, lines, rel_path))

        return chunks

    def _extract_class_chunks(
        self,
        node: ast.ClassDef,
        lines: List[str],
        rel_path: str,
    ) -> List[CodeChunk]:
        """Extracts class definition chunk and individual method chunks."""
        chunks: List[CodeChunk] = []
        class_name = node.name
        start = node.lineno
        end = getattr(node, "end_lineno", start + 20)
        class_doc = ast.get_docstring(node)

        # Class header chunk (first 25 lines of class)
        header_end = min(start + 25, end)
        class_header = "".join(lines[start - 1 : header_end]).strip()
        if class_header:
            c_hash = compute_content_hash(class_header)
            chunks.append(
                CodeChunk(
                    chunk_id=f"{rel_path}::{class_name}::{c_hash[:8]}",
                    file_path=rel_path,
                    symbol_name=class_name,
                    symbol_type="class",
                    start_line=start,
                    end_line=header_end,
                    content=class_header,
                    content_hash=c_hash,
                    language="python",
                    docstring=class_doc,
                )
            )

        # Extract nested methods
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m_start = item.lineno
                m_end = getattr(item, "end_lineno", m_start + 10)
                m_content = "".join(lines[m_start - 1 : m_end]).strip()
                if m_content:
                    m_hash = compute_content_hash(m_content)
                    method_full_name = f"{class_name}.{item.name}"
                    chunks.append(
                        CodeChunk(
                            chunk_id=f"{rel_path}::{method_full_name}::{m_hash[:8]}",
                            file_path=rel_path,
                            symbol_name=method_full_name,
                            symbol_type="method",
                            start_line=m_start,
                            end_line=m_end,
                            content=m_content,
                            content_hash=m_hash,
                            language="python",
                            parent_symbol=class_name,
                            docstring=ast.get_docstring(item),
                        )
                    )

        return chunks

    def _extract_function_chunk(
        self,
        node: Any,
        lines: List[str],
        rel_path: str,
    ) -> CodeChunk:
        """Extracts standalone top-level function chunk."""
        start = node.lineno
        end = getattr(node, "end_lineno", start + 15)
        content = "".join(lines[start - 1 : end]).strip()
        c_hash = compute_content_hash(content)
        return CodeChunk(
            chunk_id=f"{rel_path}::{node.name}::{c_hash[:8]}",
            file_path=rel_path,
            symbol_name=node.name,
            symbol_type="function",
            start_line=start,
            end_line=end,
            content=content,
            content_hash=c_hash,
            language="python",
            docstring=ast.get_docstring(node),
        )

    def _chunk_fallback_text(
        self,
        text: str,
        rel_path: str,
        language: str = "text",
        chunk_lines: int = 40,
        overlap_lines: int = 10,
    ) -> List[CodeChunk]:
        """Sliding window chunking for non-Python or syntax-invalid source files."""
        chunks: List[CodeChunk] = []
        lines = text.splitlines(keepends=True)
        if not lines:
            return chunks

        total = len(lines)
        idx = 0
        step = max(1, chunk_lines - overlap_lines)

        while idx < total:
            end_idx = min(idx + chunk_lines, total)
            chunk_content = "".join(lines[idx:end_idx]).strip()
            if chunk_content:
                c_hash = compute_content_hash(chunk_content)
                chunks.append(
                    CodeChunk(
                        chunk_id=f"{rel_path}::block_{idx+1}_{end_idx}::{c_hash[:8]}",
                        file_path=rel_path,
                        symbol_name=f"{Path(rel_path).name}#L{idx+1}-L{end_idx}",
                        symbol_type="text_block",
                        start_line=idx + 1,
                        end_line=end_idx,
                        content=chunk_content,
                        content_hash=c_hash,
                        language=language,
                    )
                )
            idx += step

        return chunks

    def chunk_file(self, file_path: Path, repo_root: Path) -> List[CodeChunk]:
        """Reads and chunks a single file based on its extension."""
        rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/")

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        if file_path.suffix.lower() == ".py":
            return self.chunk_python_source(content, rel_path)
        else:
            lang = file_path.suffix.lstrip(".") or "text"
            return self._chunk_fallback_text(content, rel_path, language=lang)

    def scan_and_chunk_repository(self, repo_root: Path) -> List[CodeChunk]:
        """Recursively scans a repository and yields all qualifying semantic chunks."""
        repo_root = Path(repo_root).resolve()
        all_chunks: List[CodeChunk] = []

        for root, dirs, files in os.walk(repo_root):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES and not d.endswith(".egg-info")]

            for f in files:
                full_path = Path(root) / f
                if self.should_index_file(full_path, repo_root):
                    file_chunks = self.chunk_file(full_path, repo_root)
                    all_chunks.extend(file_chunks)

        return all_chunks


# Global singleton chunker instance
ast_chunker = ASTCodeChunker()

