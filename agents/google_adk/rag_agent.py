"""Google ADK Repository Intelligence & RAG Agent.

Specialized in repository code indexing, symbol search, and semantic context
retrieval using AST chunking and ChromaDB vector store.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from google.adk.agents import LlmAgent

from config.settings import settings
from core.a2a import A2AEnvelope, A2AMessageType, global_a2a_bus
from core.blackboard import global_blackboard
from core.observability import callback_manager
from core.rag.vector_store import CodebaseVectorStore, vector_store


class RepositoryRAGAgent:
    """Google ADK-powered Repository Intelligence and RAG Agent."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        store: Optional[CodebaseVectorStore] = None,
    ):
        self.agent_id = "GoogleADK:RepositoryRAGAgent"
        self.framework = "google_adk"
        self.model_name = model_name or settings.DEFAULT_MODEL
        self.vector_store = store or vector_store

        def semantic_code_search(query: str, repo_id: str = "default_repo") -> list:
            """Performs vector-based semantic code retrieval."""
            return self.vector_store.query_codebase(query=query, repo_id=repo_id, top_k=5)

        # Instantiate official Google ADK LlmAgent
        self.adk_agent = LlmAgent(
            name="google_adk_rag_agent",
            description="Autonomous Software Engineering Repository Intelligence and Semantic Code Retrieval Specialist",
            instruction=(
                "You are an expert Codebase Intelligence and Retrieval Specialist. Your role is "
                "to analyze developer requirements, search the indexed codebase for relevant classes, "
                "functions, dependencies, and tests, and provide rich structured context to coding "
                "and testing agents."
            ),
            model=self.model_name,
            tools=[semantic_code_search],
        )

        global_a2a_bus.register_agent(self.agent_id, self.handle_a2a_message)

    def index_repository(self, repo_path: Path, repo_id: str = "default_repo") -> Dict[str, Any]:
        """Indexes all qualifying source files in the repository."""
        callback_manager.on_tool_start("RepositoryRAGAgent:index_repository", {"repo_path": str(repo_path), "repo_id": repo_id})
        res = self.vector_store.index_repository(repo_root=repo_path, repo_id=repo_id)
        callback_manager.on_tool_end("RepositoryRAGAgent:index_repository", res)
        return res

    def retrieve_context(
        self,
        query: str,
        repo_path: Optional[Path] = None,
        repo_id: str = "default_repo",
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """Retrieves top-k relevant code chunks for a given query, indexing repo if needed."""
        callback_manager.on_agent_start(self.agent_id, self.framework, f"Semantic code retrieval for: {query[:60]}...")

        # If repo_path is provided and index is empty for this repo_id, auto-index
        if repo_path and repo_path.exists():
            stats = self.vector_store.get_index_stats(repo_id=repo_id)
            if stats["total_chunks"] == 0:
                self.index_repository(repo_path, repo_id=repo_id)

        chunks = self.vector_store.query_codebase(
            query=query,
            repo_id=repo_id,
            top_k=top_k,
        )

        formatted_context = self.format_context_for_prompt(chunks)

        # Update Shared Blackboard if active
        global_blackboard.update_metadata(
            "retrieved_context",
            {
                "query": query,
                "repo_id": repo_id,
                "chunk_count": len(chunks),
                "chunks": chunks,
                "formatted_snippet": formatted_context,
            },
        )

        callback_manager.on_agent_finish(self.agent_id, self.framework, f"Retrieved {len(chunks)} context chunks")

        return {
            "success": True,
            "query": query,
            "repo_id": repo_id,
            "chunk_count": len(chunks),
            "chunks": chunks,
            "results": chunks,
            "formatted_context": formatted_context,
            "context": formatted_context,
        }

    def format_context_for_prompt(self, chunks: List[Dict[str, Any]]) -> str:
        """Formats retrieved chunks into clean markdown blocks for agent prompts."""
        if not chunks:
            return "No prior context found in indexed codebase."

        lines = ["### Retrieved Codebase Context (RAG):"]
        for i, c in enumerate(chunks, 1):
            score_str = f" (relevance: {c.get('score', 0.0):.2f})" if "score" in c else ""
            lines.append(f"\n#### [{i}] `{c['file_path']}` — `{c['symbol_name']}` (L{c['start_line']}-L{c['end_line']}){score_str}")
            lang = c.get("language", "python")
            lines.append(f"```{lang}\n{c['content']}\n```")

        return "\n".join(lines)

    def handle_a2a_message(self, envelope: A2AEnvelope) -> Optional[A2AEnvelope]:
        """Handles incoming A2A messages requesting repository context."""
        if envelope.message_type in (A2AMessageType.TASK_DELEGATION, A2AMessageType.TOOL_PROXY_REQUEST):
            query = envelope.payload.get("query") or envelope.payload.get("instruction", "")
            repo_id = envelope.payload.get("repo_id", "default_repo")
            top_k = envelope.payload.get("top_k", 5)
            repo_path_str = envelope.payload.get("repo_path")
            repo_path = Path(repo_path_str) if repo_path_str else None

            res = self.retrieve_context(query=query, repo_path=repo_path, repo_id=repo_id, top_k=top_k)

            return A2AEnvelope(
                sender_id=self.agent_id,
                sender_framework=self.framework,
                recipient_id=envelope.sender_id,
                message_type=A2AMessageType.TASK_RESULT if envelope.message_type == A2AMessageType.TASK_DELEGATION else A2AMessageType.TOOL_PROXY_RESPONSE,
                correlation_id=envelope.message_id,
                payload=res,
            )
        return None
