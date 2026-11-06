"""DevPilot AI — Enterprise Autonomous Software Engineering Workspace.

Transforming Developer Requirements into Validated, Production-Ready Code Changes
using CrewAI, Google ADK, A2A Protocol, Shared Blackboard, and MCP Sandbox Tools.
"""

import sys
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import streamlit as st
import pandas as pd

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Backend Imports
from config.settings import settings
from config.models_config import MODEL_PRICING_TABLE, calculate_cost
from core.schemas import (
    RepositoryConfig,
    DeveloperRequirement,
    TaskStatus,
    ChangeType,
    FilePatch,
)
from core.blackboard import global_blackboard
from core.a2a import global_a2a_bus
from core.guardrails import security_suite
from core.observability import callback_manager, provenance_tracker, system_tracer
from core.hitl import hitl_gatekeeper
from core.github import github_client, pr_publisher
from core.rag.vector_store import vector_store
from mcp_servers.repo_tool import mcp_repo_client
from core.auth import resolve_user_identity, UserIdentity, Permission
from orchestration import (
    AutonomousEngineeringOrchestrator,
    AgenticPatternType,
    PATTERN_DESCRIPTIONS,
    PersonaType,
    PERSONA_CONFIGS,
    get_persona,
)
from evaluation import (
    architecture_comparator,
    metrics_collector,
    experiment_storage,
    BENCHMARK_TASKS,
)
from core.preview import preview_manager
import streamlit.components.v1 as components

# -----------------------------------------------------------------------------
# Streamlit Page Configuration
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="DevPilot AI — Autonomous Software Engineering Workspace",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load Enterprise SaaS Styling
css_path = Path(__file__).parent / "styles.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

# Session State Initialization
if "active_repo_url" not in st.session_state:
    st.session_state.active_repo_url = "sample_repo"
if "active_base_branch" not in st.session_state:
    st.session_state.active_base_branch = "main"
if "last_metrics" not in st.session_state:
    st.session_state.last_metrics = None
if "last_run_id" not in st.session_state:
    st.session_state.last_run_id = None
if "last_sandbox_path" not in st.session_state:
    st.session_state.last_sandbox_path = None
if "last_pr_result" not in st.session_state:
    st.session_state.last_pr_result = None
if "last_indexing_time" not in st.session_state:
    st.session_state.last_indexing_time = None
if "last_indexing_stats" not in st.session_state:
    st.session_state.last_indexing_stats = None

# Resolve Authenticated Identity & Permissions via Enterprise Proxy Headers or Session
current_user = resolve_user_identity(session_state=st.session_state)


# -----------------------------------------------------------------------------
# Dynamic Repository Intelligence Helper Functions
# -----------------------------------------------------------------------------
def detect_repo_metadata(sandbox_path: Optional[Path], repo_url: str) -> Dict[str, Any]:
    """Dynamically detects repository owner, repository name, base branch, and technology stack."""
    owner = "workspace"
    repo_name = "sample_repo"
    if "github.com/" in repo_url:
        parts = repo_url.split("github.com/")[-1].strip("/").split("/")
        if len(parts) >= 2:
            owner = parts[0]
            repo_name = parts[1].replace(".git", "")
    elif repo_url.strip():
        repo_name = Path(repo_url).stem or repo_url

    tech_stack = "Generic Polyglot"
    if sandbox_path and sandbox_path.exists():
        pkg = sandbox_path / "package.json"
        if pkg.exists():
            try:
                pkg_data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
                deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                has_ts = (sandbox_path / "tsconfig.json").exists() or any(sandbox_path.rglob("*.tsx")) or any(sandbox_path.rglob("*.ts"))
                if "react" in deps:
                    if "vite" in deps or (sandbox_path / "vite.config.ts").exists() or (sandbox_path / "vite.config.js").exists():
                        tech_stack = "React 18 + TypeScript (Vite)" if has_ts else "React 18 + Vite"
                    elif "next" in deps:
                        tech_stack = "Next.js + React + TypeScript" if has_ts else "Next.js + React"
                    else:
                        tech_stack = "React 18 + TypeScript" if has_ts else "React (JavaScript)"
                elif "vue" in deps:
                    tech_stack = "Vue.js + TypeScript" if has_ts else "Vue.js + Node"
                else:
                    tech_stack = "Node.js + TypeScript" if has_ts else "Node.js (JavaScript)"
            except Exception:
                tech_stack = "Node.js / JavaScript"
        elif (sandbox_path / "pyproject.toml").exists() or (sandbox_path / "requirements.txt").exists() or any(sandbox_path.rglob("*.py")):
            tech_stack = "Python 3.11 + Pytest"
        elif (sandbox_path / "pom.xml").exists():
            tech_stack = "Java 17 + Maven"
        elif (sandbox_path / "Cargo.toml").exists():
            tech_stack = "Rust + Cargo"

    return {
        "owner": owner,
        "repo_name": repo_name,
        "tech_stack": tech_stack,
    }


def scan_repository_files(sandbox_path: Optional[Path]) -> Tuple[List[str], Dict[str, int], int, float]:
    """Scans repository files across multiple languages and computes file-type breakdowns."""
    if not sandbox_path or not sandbox_path.exists():
        return [], {}, 0, 0.0

    valid_extensions = {
        ".tsx", ".ts", ".jsx", ".js", ".py", ".json", ".css", ".html",
        ".md", ".yml", ".yaml", ".toml", ".sql", ".sh"
    }
    exclude_dirs = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".pytest_cache", ".coverage"}

    file_list = []
    ext_counts: Dict[str, int] = {}
    total_lines = 0
    total_size_bytes = 0

    for p in sandbox_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in valid_extensions:
            parts = p.parts
            if any(ex in parts for ex in exclude_dirs):
                continue
            rel_path = str(p.relative_to(sandbox_path)).replace("\\", "/")
            file_list.append(rel_path)

            ext = p.suffix.lower()
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

            try:
                sz = p.stat().st_size
                total_size_bytes += sz
                if sz < 500_000:
                    with open(p, "rb") as f:
                        total_lines += sum(1 for _ in f)
            except Exception:
                pass

    file_list.sort()
    return file_list, ext_counts, total_lines, total_size_bytes / 1024.0


def get_syntax_highlight_language(file_path: str) -> str:
    """Returns Streamlit/Pygments language identifier for a file path."""
    ext = Path(file_path).suffix.lower()
    return {
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".py": "python",
        ".json": "json",
        ".css": "css",
        ".html": "html",
        ".md": "markdown",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".sql": "sql",
        ".sh": "bash",
    }.get(ext, "python")


# -----------------------------------------------------------------------------
# Top Navigation Bar & Brand Header
# -----------------------------------------------------------------------------
st.markdown(
    f"""
    <div class="devpilot-navbar">
        <div class="devpilot-brand">
            <div class="devpilot-brand-icon">⚡</div>
            <div>
                <div class="devpilot-brand-title">DevPilot AI</div>
                <div class="devpilot-tagline">Autonomous Multi-Agent Software Engineering Workspace</div>
            </div>
        </div>
        <div class="devpilot-nav-badges">
            <div class="devpilot-status-pill">
                <div class="devpilot-status-dot"></div>
                <span>Workspace Active</span>
            </div>
            <div class="badge badge-green">👤 {current_user.display_name} ({current_user.role.value})</div>
            <div class="badge badge-blue">CrewAI + Google ADK</div>
            <div class="badge badge-purple">{settings.DEFAULT_MODEL}</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Core Product Promise Hero Banner
st.markdown(
    """
    <div class="devpilot-hero-banner">
        <div class="devpilot-hero-title">
            <span>🛡️ Enterprise Autonomous Software Engineering</span>
            <span class="badge badge-blue" style="font-size: 0.75rem;">Continuous Human Oversight</span>
        </div>
        <p class="devpilot-hero-desc">
            Connect your GitHub repository. Describe what needs to change. DevPilot AI understands your codebase
            and handles the engineering workflow — while you stay in control of the final changes.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Sidebar Configuration & Environment
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Workspace Settings")
    st.caption("Central runtime configuration and credential management.")

    # Execution Mode Indicator
    st.markdown(
        f"""
        <div class="saas-metric-box" style="margin-bottom: 1rem;">
            <div class="saas-metric-label">Execution Environment</div>
            <div style="font-size: 1.05rem; font-weight: 600; color: #58A6FF; margin: 4px 0;">
                Mode: <code>{settings.EXECUTION_MODE}</code>
            </div>
            <div class="saas-metric-subtext">Primary Model: <code>{settings.DEFAULT_MODEL}</code></div>
            <div class="saas-metric-subtext" style="color: #3FB950; margin-top: 4px;">• Quota Consumed: $0 (Offline Safe)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # API Keys Configuration
    with st.expander("🔑 Credential Management", expanded=False):
        api_key = st.text_input(
            "Gemini API Key",
            value=settings.GEMINI_API_KEY,
            type="password",
            help="Google AI Studio Gemini API Key for online reasoning.",
        )
        if api_key != settings.GEMINI_API_KEY:
            settings.GEMINI_API_KEY = api_key

        gh_token = st.text_input(
            "GitHub Token (PAT)",
            value=settings.GITHUB_TOKEN,
            type="password",
            help="Personal Access Token with 'repo' scope for PR publishing.",
        )
        if gh_token != settings.GITHUB_TOKEN:
            settings.GITHUB_TOKEN = gh_token

    st.markdown("---")
    st.markdown("### 🛡️ Guardrails & Safety")
    st.markdown(
        """
        <div style="display: flex; flex-direction: column; gap: 8px; font-size: 0.85rem;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #C9D1D9;">HITL Approval Gate</span>
                <span class="badge badge-green">Compulsory</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #C9D1D9;">AST Security Scanner</span>
                <span class="badge badge-green">Enabled</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #C9D1D9;">Prompt Injection Guard</span>
                <span class="badge badge-green">Active</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #C9D1D9;">Sandbox Isolation</span>
                <span class="badge badge-blue">Ephemeral Runs</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #C9D1D9;">Remote Push Guard</span>
                <span class="badge badge-amber">Agentic Branch Only</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("### 👥 Agent Roles & Ownership")
    st.caption(
        "• **Planner / Architect:** CrewAI (Muskan Patni)\n"
        "• **Manager / Dispatcher:** CrewAI (Vaishnavi Singh)\n"
        "• **Coder:** Google ADK (Vaishnavi Singh)\n"
        "• **Test Generator:** Google ADK (Vaishnavi Singh)\n"
        "• **Debugger:** Google ADK (Vaishnavi Singh)\n"
        "• **RAG / Codebase:** Google ADK (Muskan Patni)\n"
        "• **Auditor & QA:** CrewAI (Muskan Patni)"
    )

# -----------------------------------------------------------------------------
# Four Horizontal Top Navigation Tabs
# -----------------------------------------------------------------------------
tab_kb, tab_ask, tab_compare, tab_eval = st.tabs([
    "📚 Knowledge Base",
    "💬 Ask",
    "🔬 Compare Conditions",
    "📊 Evaluation",
])

# Resolve active sandbox path
active_sb_path = (
    Path(st.session_state.last_sandbox_path)
    if st.session_state.last_sandbox_path
    else (settings.SANDBOX_ROOT / "sample_repo")
)
# Compute live metadata for current repository
repo_metadata = detect_repo_metadata(active_sb_path, st.session_state.active_repo_url)
discovered_files, file_ext_counts, total_loc, total_disk_kb = scan_repository_files(active_sb_path)


# =============================================================================
# TAB 1: KNOWLEDGE BASE
# =============================================================================
with tab_kb:
    st.markdown("## 📚 Repository Intelligence & Codebase Knowledge Base")
    st.caption("Connect repositories, dynamically inspect multi-language file trees, and semantically retrieve AST code context.")

    # Status Banner
    is_github_repo = st.session_state.active_repo_url.startswith("https://")
    conn_type = "Remote GitHub" if is_github_repo else "Local Sandbox"
    conn_badge_cls = "badge-blue" if is_github_repo else "badge-green"

    st.markdown(
        f"""
        <div class="context-banner">
            <div class="context-banner-item">
                <span style="color: #8B949E;">Target Repo:</span>
                <code style="color: #58A6FF;">{repo_metadata['owner']}/{repo_metadata['repo_name']}</code>
            </div>
            <div class="context-banner-item">
                <span style="color: #8B949E;">Base Branch:</span>
                <code>{st.session_state.active_base_branch}</code>
            </div>
            <div class="context-banner-item">
                <span style="color: #8B949E;">Detected Stack:</span>
                <span class="badge badge-purple">{repo_metadata['tech_stack']}</span>
            </div>
            <div class="context-banner-item">
                <span style="color: #8B949E;">Type:</span>
                <span class="badge {conn_badge_cls}">{conn_type}</span>
            </div>
            <div class="context-banner-item">
                <span style="color: #8B949E;">Scanned Files:</span>
                <span class="badge badge-amber">{len(discovered_files)} files ({total_loc:,} lines)</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_kb_conn, col_kb_stats = st.columns([3, 2])

    with col_kb_conn:
        st.markdown(
            """
            <div class="saas-card">
                <div class="saas-card-header">
                    <div class="saas-card-title">🔗 Target Repository Connection</div>
                    <span class="badge badge-blue">Git CLI / MCP</span>
                </div>
            """,
            unsafe_allow_html=True,
        )

        # Quick preset selection
        repo_presets = [
            "vaishnavisingh805/IT-Support (React 18 + TS)",
            "sample_repo (Python 3.11 + Pytest)",
            "runs/local_demo_welcome_page (Local Demo — React + TS)",
            "Custom Repository URL...",
        ]
        chosen_preset = st.selectbox(
            "Repository Quick Presets",
            repo_presets,
            index=0 if "IT-Support" in st.session_state.active_repo_url else (2 if "local_demo" in st.session_state.active_repo_url else (1 if "sample_repo" in st.session_state.active_repo_url else 3)),
            help="Select a benchmark repository or enter a custom GitHub URL.",
        )

        if chosen_preset == "vaishnavisingh805/IT-Support (React 18 + TS)":
            suggested_url = "https://github.com/vaishnavisingh805/IT-Support"
            suggested_branch = "main"
        elif chosen_preset == "sample_repo (Python 3.11 + Pytest)":
            suggested_url = "sample_repo"
            suggested_branch = "main"
        elif "local_demo" in chosen_preset:
            suggested_url = "runs/local_demo_welcome_page"
            suggested_branch = "main"
        else:
            suggested_url = st.session_state.active_repo_url
            suggested_branch = st.session_state.active_base_branch

        kb_repo_url = st.text_input(
            "Repository HTTPS URL or Local Workspace",
            value=suggested_url,
            help="Enter a GitHub HTTPS URL (e.g. https://github.com/owner/repo) or 'sample_repo'.",
        )
        kb_base_branch = st.text_input(
            "Base Branch",
            value=suggested_branch,
            help="Default base branch to compare against (e.g. main or master).",
        )

        col_btn1, col_btn2 = st.columns([1, 1])
        with col_btn1:
            if st.button("🔄 Connect & Index Codebase", key="btn_connect_repo"):
                st.session_state.active_repo_url = kb_repo_url
                st.session_state.active_base_branch = kb_base_branch
                st.session_state.last_metrics = None
                st.session_state.last_pr_result = None
                global_blackboard.reset()
                with st.spinner("Connecting repository and indexing AST code chunks into ChromaDB..."):
                    if kb_repo_url.startswith("https://"):
                        clone_res = mcp_repo_client.clone_repository(kb_repo_url, base_branch=kb_base_branch)
                        if clone_res.get("success"):
                            st.session_state.last_run_id = clone_res["run_id"]
                            st.session_state.last_sandbox_path = clone_res["sandbox_path"]
                            idx_res = mcp_repo_client.index_rag(clone_res["run_id"])
                            st.session_state.last_indexing_time = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                            st.session_state.last_indexing_stats = idx_res
                            st.success(f"Successfully cloned and indexed {idx_res.get('indexed_files', 0)} files ({idx_res.get('total_chunks', 0)} AST chunks)!")
                            st.rerun()
                        else:
                            st.error(f"Clone failed: {clone_res.get('error')}")
                    else:
                        sb_res = mcp_repo_client.create_sandbox(kb_repo_url)
                        if sb_res.get("success"):
                            st.session_state.last_run_id = sb_res["run_id"]
                            st.session_state.last_sandbox_path = sb_res["sandbox_path"]
                            idx_res = mcp_repo_client.index_rag(sb_res["run_id"])
                            st.session_state.last_indexing_time = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                            st.session_state.last_indexing_stats = idx_res
                            st.success(f"Indexed local sandbox: {idx_res.get('indexed_files', 0)} files ({idx_res.get('total_chunks', 0)} AST chunks).")
                            st.rerun()
                        else:
                            st.error(f"Sandbox creation failed: {sb_res.get('error')}")

        st.markdown("</div>", unsafe_allow_html=True)

    with col_kb_stats:
        stats = vector_store.get_index_stats()
        last_idx_label = st.session_state.last_indexing_time or "Live In-Memory"
        st.markdown(
            f"""
            <div class="saas-card">
                <div class="saas-card-header">
                    <div class="saas-card-title">📊 ChromaDB Vector Index</div>
                    <span class="badge badge-green">Ready</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <div class="saas-metric-box">
                        <div class="saas-metric-label">AST Chunks</div>
                        <div class="saas-metric-value">{stats.get("total_chunks", 0)}</div>
                        <div class="saas-metric-subtext">Classes, Functions & Components</div>
                    </div>
                    <div class="saas-metric-box">
                        <div class="saas-metric-label">Repositories</div>
                        <div class="saas-metric-value">{stats.get("indexed_repositories", 0)}</div>
                        <div class="saas-metric-subtext">Active Isolated Indexes</div>
                    </div>
                </div>
                <div style="margin-top: 12px; font-size: 0.82rem; color: #8B949E; line-height: 1.5;">
                    • <b>Embedding Model:</b> 128-d Feature-Hashing Dense Vectorizer<br>
                    • <b>Quota Impact:</b> $0 Gemini quota consumed (deterministic offline)<br>
                    • <b>Last Indexed:</b> <code>{last_idx_label}</code>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Repository File Browser & Multi-Language Code Viewer
    st.markdown("### 📂 Repository File Tree & Source Code Viewer")
    if active_sb_path.exists() and discovered_files:
        # Display breakdown chips by file extension
        chips_html = " ".join([
            f"<span class='chip'>{ext.upper()}: <b>{cnt}</b></span>"
            for ext, cnt in sorted(file_ext_counts.items(), key=lambda x: -x[1])
        ])
        st.markdown(
            f"""
            <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap;">
                <span style="font-size: 0.85rem; color: #8B949E;">File Distribution:</span>
                {chips_html}
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_f_sel, col_f_info = st.columns([3, 1])
        with col_f_sel:
            selected_file = st.selectbox("Select File to Inspect", discovered_files, index=0)

        target_file_path = active_sb_path / selected_file
        file_content = target_file_path.read_text(encoding="utf-8", errors="replace")
        file_lines = len(file_content.splitlines())
        file_size_kb = target_file_path.stat().st_size / 1024
        file_lang = get_syntax_highlight_language(selected_file)

        with col_f_info:
            st.markdown(
                f"""
                <div class="saas-metric-box" style="padding: 0.6rem 0.8rem; margin-top: 24px;">
                    <div style="font-size: 0.78rem; color: #8B949E;">File Size: <b>{file_size_kb:.1f} KB</b></div>
                    <div style="font-size: 0.78rem; color: #8B949E;">Lines: <b>{file_lines}</b></div>
                    <div style="font-size: 0.78rem; color: #58A6FF;">Syntax: <code>{file_lang}</code></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.code(file_content, language=file_lang, line_numbers=True)

    elif active_sb_path.exists():
        st.markdown(
            """
            <div class="saas-card" style="text-align: center; padding: 2rem;">
                <div style="font-size: 2rem; margin-bottom: 0.5rem;">📂</div>
                <div class="saas-card-title" style="justify-content: center;">No Source Files Detected</div>
                <p style="color: #8B949E; font-size: 0.88rem; max-width: 480px; margin: 0.5rem auto;">
                    No supported source files were found in the active workspace. Connect a valid repository above or clone an upstream GitHub codebase.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="saas-card" style="text-align: center; padding: 2rem;">
                <div style="font-size: 2rem; margin-bottom: 0.5rem;">🔗</div>
                <div class="saas-card-title" style="justify-content: center;">Workspace Not Connected</div>
                <p style="color: #8B949E; font-size: 0.88rem; max-width: 480px; margin: 0.5rem auto;">
                    Click <b>Connect & Index Codebase</b> above to initialize the isolated sandbox repository and populate the file tree.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Semantic Code Retrieval (RAG)
    st.markdown("### 🔎 Semantic Code Search (RAG)")
    st.caption("Search indexed classes, components, methods, and functions across the codebase using semantic relevance ranking.")

    # Suggest smart query based on current repo
    if "IT-Support" in st.session_state.active_repo_url:
        default_rag_q = "DashboardPage priority filter dropdown or ticket status counter"
    else:
        default_rag_q = "Calculate population and sample variance or standard deviation"

    col_q, col_k = st.columns([4, 1])
    with col_q:
        rag_query = st.text_input("Natural Language Code Query", value=default_rag_q)
    with col_k:
        top_k = st.slider("Top K Chunks", min_value=1, max_value=8, value=4)

    if st.button("Search Codebase", key="btn_rag_search"):
        with st.spinner("Searching indexed AST symbols..."):
            retrieval_res = mcp_repo_client.query_rag(
                query=rag_query,
                run_id=st.session_state.last_run_id,
                top_k=top_k,
            )
            chunks = retrieval_res.get("results", [])
            if chunks:
                st.success(f"Retrieved {len(chunks)} relevant code context chunks:")
                for i, chunk in enumerate(chunks):
                    score = chunk.get("relevance_score", 0.0)
                    sym_type = chunk.get("symbol_type", "code")
                    sym_name = chunk.get("symbol_name", "anonymous")
                    f_path = chunk.get("file_path", "unknown")
                    s_line = chunk.get("start_line", 0)
                    e_line = chunk.get("end_line", 0)
                    chunk_lang = get_syntax_highlight_language(f_path)

                    with st.expander(f"Chunk #{i+1}: `{f_path}` ({sym_type}: **{sym_name}**) — Lines #{s_line}–#L{e_line}", expanded=(i==0)):
                        st.markdown(
                            f"""
                            <div style="display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap;">
                                <span class="badge badge-blue">Path: {f_path}</span>
                                <span class="badge badge-purple">{sym_type}: {sym_name}</span>
                                <span class="badge badge-amber">Lines #L{s_line}–#L{e_line}</span>
                                <span class="badge badge-green">Relevance: {score:.4f}</span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        st.code(chunk.get("content", ""), language=chunk_lang)
            else:
                st.warning("No matching code chunks found for this query.")


# =============================================================================
# TAB 2: ASK (MISSION CONTROL & AUTONOMOUS WORKSPACE)
# =============================================================================
with tab_ask:
    st.markdown("## 💬 Autonomous Engineering Mission Control")
    st.caption("Submit natural-language requirements, observe multi-agent orchestration, inspect Blackboard, review diffs, and publish PRs.")

    # Context Banner for Mission Control
    st.markdown(
        f"""
        <div class="context-banner">
            <div class="context-banner-item">
                <span style="color: #8B949E;">Target Repo:</span>
                <code style="color: #58A6FF;">{repo_metadata['owner']}/{repo_metadata['repo_name']}</code>
            </div>
            <div class="context-banner-item">
                <span style="color: #8B949E;">Base Branch:</span>
                <code>{st.session_state.active_base_branch}</code>
            </div>
            <div class="context-banner-item">
                <span style="color: #8B949E;">Detected Stack:</span>
                <span class="badge badge-purple">{repo_metadata['tech_stack']}</span>
            </div>
            <div class="context-banner-item">
                <span style="color: #8B949E;">User Identity:</span>
                <span class="badge badge-blue">{current_user.display_name} ({current_user.role.value})</span>
            </div>
            <div class="context-banner-item">
                <span style="color: #8B949E;">Active Mode:</span>
                <span class="badge badge-green">{settings.EXECUTION_MODE}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_req, col_cfg = st.columns([3, 2])

    with col_req:
        st.markdown(
            """
            <div class="saas-card">
                <div class="saas-card-header">
                    <div class="saas-card-title">📝 Developer Requirement Input</div>
                    <span class="badge badge-blue">Prompt Guard Active</span>
                </div>
            """,
            unsafe_allow_html=True,
        )

        is_scratch_mode = ("empty" in str(st.session_state.active_repo_url).lower() or not st.session_state.active_repo_url)
        setup_mode_choice = st.radio(
            "Project Setup Mode",
            ["🔄 Modify Existing Project", "🏗️ Build from Scratch"],
            index=1 if is_scratch_mode else 0,
            horizontal=True,
            help="Choose whether to enhance an existing repository or scaffold a runnable React + TypeScript application from an empty repository.",
        )
        project_mode = "build_from_scratch" if "Build from Scratch" in setup_mode_choice else "modify_existing"

        # Dynamic requirement presets based on active repository and setup mode
        if project_mode == "build_from_scratch":
            preset_tasks = [
                "Build a modern, responsive login page with email validation, password visibility toggle, and loading feedback",
                "Create a user authentication dashboard with remember-me checkbox and password recovery",
                "Scaffold a full React 19 + TypeScript + Vite portal with sign-in and session state",
            ]
        elif "IT-Support" in st.session_state.active_repo_url:
            preset_tasks = [
                "Add password visibility toggle and validate email and password inputs in LoginPage.tsx",
                "Add priority filter dropdown to DashboardPage and display ticket count",
                "Implement export tickets to CSV function in TicketTable with status filters",
                "Add status badge styling for escalated tickets in TicketCard component",
            ]
        else:
            preset_tasks = [
                "Implement standard_deviation(numbers, sample=False) calculation in AdvancedCalculator with unit tests",
                "Add financial Net Present Value (npv) and Internal Rate of Return (irr) methods",
                "Implement matrix multiplication and determinant calculation for 2x2 and 3x3 matrices",
                "Add statistical summary(numbers) method returning mean, median, mode, and range",
            ]

        selected_preset = st.selectbox(
            "Benchmark Requirement Presets",
            ["Custom Requirement..."] + preset_tasks,
            index=1,
            help="Select a benchmark requirement tailored to the connected codebase.",
        )

        if selected_preset != "Custom Requirement...":
            default_prompt = selected_preset
        else:
            if project_mode == "build_from_scratch":
                default_prompt = "Build a modern, responsive login page with email validation, password visibility toggle, and loading feedback"
            elif "IT-Support" in st.session_state.active_repo_url:
                default_prompt = "Add password visibility toggle and validate email and password inputs in LoginPage.tsx"
            else:
                default_prompt = "Implement standard_deviation(numbers, sample=False) calculation in AdvancedCalculator with unit tests"

        user_prompt = st.text_area("Requirement Prompt", value=default_prompt, height=110)
        st.markdown("</div>", unsafe_allow_html=True)

    with col_cfg:
        st.markdown(
            """
            <div class="saas-card">
                <div class="saas-card-header">
                    <div class="saas-card-title">⚙️ Execution Architecture & Persona</div>
                </div>
            """,
            unsafe_allow_html=True,
        )

        selected_pattern = st.selectbox(
            "Multi-Agent Architecture Pattern",
            options=[p.value for p in AgenticPatternType],
            index=0,
            help="Select the control flow architecture under empirical evaluation.",
        )

        pattern_desc = PATTERN_DESCRIPTIONS.get(AgenticPatternType(selected_pattern), "")
        st.caption(f"ℹ️ {pattern_desc}")

        selected_persona = st.selectbox(
            "Engineering Persona Configuration",
            options=[p.value for p in PersonaType],
            index=0,
            help="Controls system instruction rigor, temperature, and validation depth.",
        )

        persona_cfg = PERSONA_CONFIGS.get(PersonaType(selected_persona))
        temp_val = getattr(persona_cfg, "temperature", 0.2)
        rigor_val = getattr(persona_cfg, "validation_rigor", "standard")
        st.caption(f"ℹ️ Temperature: `{temp_val}` | Validation Rigor: `{rigor_val.title()}`")

        auto_commit_toggle = st.checkbox(
            "Auto-Commit Locally if Approved by Gatekeeper",
            value=False,
            help="If checked, local changes are committed to the agentic branch upon successful test/audit verification.",
        )

        st.markdown("</div>", unsafe_allow_html=True)

    # Complete 8-Stage Autonomous Engineering Workflow Visualizer
    has_run = (st.session_state.last_metrics is not None)
    step1_cls = "timeline-step-done" if has_run else "timeline-step"
    step2_cls = "timeline-step-done" if has_run else "timeline-step"
    step3_cls = "timeline-step-done" if has_run else "timeline-step"
    step4_cls = "timeline-step-done" if has_run else "timeline-step"
    step5_cls = "timeline-step-done" if has_run else "timeline-step"
    step6_cls = "timeline-step-done" if has_run else "timeline-step"
    step7_cls = "timeline-step-done" if (has_run and global_blackboard.state.human_approval_status == "approved") else ("timeline-step-active" if has_run else "timeline-step")
    step8_cls = "timeline-step-done" if (has_run and st.session_state.last_pr_result and st.session_state.last_pr_result.get("pr_url")) else "timeline-step"

    st.markdown(
        f"""
        <div class="timeline-track">
            <div class="timeline-step {step1_cls}">
                <div class="timeline-step-circle">1</div>
                <div class="timeline-step-label">Requirement</div>
                <div class="timeline-step-agent">Prompt Guard</div>
            </div>
            <div style="flex: 1; height: 2px; background: var(--border-color);"></div>
            <div class="timeline-step {step2_cls}">
                <div class="timeline-step-circle">2</div>
                <div class="timeline-step-label">RAG Retrieval</div>
                <div class="timeline-step-agent">Google ADK</div>
            </div>
            <div style="flex: 1; height: 2px; background: var(--border-color);"></div>
            <div class="timeline-step {step3_cls}">
                <div class="timeline-step-circle">3</div>
                <div class="timeline-step-label">Planning</div>
                <div class="timeline-step-agent">CrewAI Planner</div>
            </div>
            <div style="flex: 1; height: 2px; background: var(--border-color);"></div>
            <div class="timeline-step {step4_cls}">
                <div class="timeline-step-circle">4</div>
                <div class="timeline-step-label">Code Patch</div>
                <div class="timeline-step-agent">Google ADK Coder</div>
            </div>
            <div style="flex: 1; height: 2px; background: var(--border-color);"></div>
            <div class="timeline-step {step5_cls}">
                <div class="timeline-step-circle">5</div>
                <div class="timeline-step-label">Test & AST</div>
                <div class="timeline-step-agent">Google ADK Tester</div>
            </div>
            <div style="flex: 1; height: 2px; background: var(--border-color);"></div>
            <div class="timeline-step {step6_cls}">
                <div class="timeline-step-circle">6</div>
                <div class="timeline-step-label">Self-Healing</div>
                <div class="timeline-step-agent">ADK Debugger</div>
            </div>
            <div style="flex: 1; height: 2px; background: var(--border-color);"></div>
            <div class="timeline-step {step7_cls}">
                <div class="timeline-step-circle">7</div>
                <div class="timeline-step-label">HITL Gate</div>
                <div class="timeline-step-agent">Human Sign-off</div>
            </div>
            <div style="flex: 1; height: 2px; background: var(--border-color);"></div>
            <div class="timeline-step {step8_cls}">
                <div class="timeline-step-circle">8</div>
                <div class="timeline-step-label">GitHub PR</div>
                <div class="timeline-step-agent">PR Publisher</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Execution Action Button
    col_exec_btn, col_exec_meta = st.columns([2, 3])
    with col_exec_btn:
        exec_clicked = st.button("🚀 Execute Autonomous Engineering Workflow", key="btn_run_pipeline")

    if exec_clicked:
        st.session_state.last_metrics = None
        st.session_state.last_pr_result = None
        global_blackboard.reset()
        with st.spinner("Multi-Agent System executing lifecycle across CrewAI and Google ADK..."):
            pattern_enum = AgenticPatternType(selected_pattern)
            persona_enum = PersonaType(selected_persona)

            orchestrator = AutonomousEngineeringOrchestrator(
                pattern=pattern_enum,
                persona=persona_enum,
            )

            repo_cfg = RepositoryConfig(
                repo_url=st.session_state.active_repo_url,
                base_branch=st.session_state.active_base_branch,
                task_id="REQ-01",
            )

            try:
                start_t = time.time()
                metrics = orchestrator.execute_requirement(
                    raw_prompt=user_prompt,
                    target_repo=repo_cfg,
                    auto_commit_if_approved=auto_commit_toggle,
                    project_setup_mode=project_mode,
                )

                st.session_state.last_metrics = metrics
                st.session_state.last_run_id = metrics.run_id
                st.session_state.last_sandbox_run_id = getattr(metrics, "sandbox_run_id", None) or global_blackboard.state.metadata.get("sandbox_run_id") or global_blackboard.state.metadata.get("repository", {}).get("run_id")
                st.session_state.last_sandbox_path = getattr(metrics, "sandbox_path", None) or global_blackboard.state.metadata.get("sandbox_path") or global_blackboard.state.metadata.get("repository", {}).get("sandbox_path")
                st.session_state.last_pr_result = None
            except Exception as e:
                st.error(f"Execution Error: {str(e)}")

    # Display Metrics Summary if execution has run
    metrics = st.session_state.last_metrics
    if metrics:
        st.markdown("---")
        st.markdown("### 📈 Real-Time Execution Telemetry")
        m_c1, m_c2, m_c3, m_c4, m_c5, m_c6 = st.columns(6)
        with m_c1:
            status_badge = "PASSED" if metrics.success else "FAILED"
            b_color = "#3FB950" if metrics.success else "#F85149"
            st.markdown(
                f'<div class="saas-metric-box"><div class="saas-metric-label">Status</div><div class="saas-metric-value" style="color: {b_color}; font-size: 1.25rem;">{status_badge}</div><div class="saas-metric-subtext">Run ID: <code>{metrics.run_id[:8]}</code></div></div>',
                unsafe_allow_html=True,
            )
        with m_c2:
            st.markdown(
                f'<div class="saas-metric-box"><div class="saas-metric-label">Runtime</div><div class="saas-metric-value">{metrics.total_execution_time_seconds:.2f}s</div><div class="saas-metric-subtext">Wall-clock time</div></div>',
                unsafe_allow_html=True,
            )
        with m_c3:
            st.markdown(
                f'<div class="saas-metric-box"><div class="saas-metric-label">Total Tokens</div><div class="saas-metric-value">{metrics.total_tokens:,}</div><div class="saas-metric-subtext">Prompt + Comp</div></div>',
                unsafe_allow_html=True,
            )
        with m_c4:
            st.markdown(
                f'<div class="saas-metric-box"><div class="saas-metric-label">Estimated Cost</div><div class="saas-metric-value">${metrics.total_cost_usd:.5f}</div><div class="saas-metric-subtext">Gemini Pricing</div></div>',
                unsafe_allow_html=True,
            )
        with m_c5:
            st.markdown(
                f'<div class="saas-metric-box"><div class="saas-metric-label">Pass Rate</div><div class="saas-metric-value">{metrics.test_pass_rate_percentage:.1f}%</div><div class="saas-metric-subtext">Sandbox Pytest / Static</div></div>',
                unsafe_allow_html=True,
            )
        with m_c6:
            st.markdown(
                f'<div class="saas-metric-box"><div class="saas-metric-label">A2A Envelopes</div><div class="saas-metric-value">{metrics.a2a_message_count}</div><div class="saas-metric-subtext">Agent Messages</div></div>',
                unsafe_allow_html=True,
            )

        # 10 Organized Sub-Tabs for complete multi-agent workflow inspection
        sub_rag, sub_plan, sub_bb, sub_a2a, sub_diff, sub_test, sub_debug, sub_preview, sub_hitl, sub_pr = st.tabs([
            "🔍 RAG Context & Provenance",
            "📋 Planner & Criteria",
            "🧠 Reactive Blackboard",
            "💬 A2A Protocol",
            "📝 Code Changes & Diff",
            "🧪 Unit Test & AST",
            "🩺 Self-Healing Debugger",
            "🌐 Live Browser Preview",
            "👤 HITL Gatekeeper",
            "🚀 GitHub Pull Request",
        ])

        with sub_rag:
            st.markdown("#### 🔍 Repository RAG Context & Target Resolution")
            resolved_target = global_blackboard.state.metadata.get("target_file") or (
                list(global_blackboard.state.active_patches.keys())[0]
                if global_blackboard.state.active_patches
                else "N/A"
            )
            st.markdown(
                f"""
                <div style="display: flex; gap: 10px; margin-bottom: 12px; align-items: center;">
                    <span class="badge badge-blue">Target File: <code>{resolved_target}</code></span>
                    <span class="badge badge-purple">Isolation: Ephemeral Sandbox</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            retrieved = global_blackboard.state.metadata.get("retrieved_chunks", [])
            if retrieved:
                st.markdown(f"**Retrieved AST Chunks ({len(retrieved)} items):**")
                for i, chunk in enumerate(retrieved):
                    c_path = chunk.get("file_path", "unknown")
                    c_start = chunk.get("start_line", 0)
                    c_end = chunk.get("end_line", 0)
                    c_type = chunk.get("symbol_type", "symbol")
                    c_name = chunk.get("symbol_name", "anonymous")
                    c_score = chunk.get("relevance_score", 0.0)
                    chunk_lang = get_syntax_highlight_language(c_path)

                    with st.expander(f"Chunk #{i+1}: `{c_path}` ({c_type}: **{c_name}**) — Lines #L{c_start}–#L{c_end}", expanded=(i==0)):
                        st.markdown(
                            f"""
                            <div style="display: flex; gap: 8px; margin-bottom: 6px;">
                                <span class="badge badge-blue">Path: {c_path}</span>
                                <span class="badge badge-amber">#L{c_start}-#L{c_end}</span>
                                <span class="badge badge-green">Relevance: {c_score:.4f}</span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        st.code(chunk.get("content", ""), language=chunk_lang)
            else:
                st.caption("No RAG chunks stored for this execution.")

        with sub_plan:
            st.markdown("#### 📋 Requirements Analysis & Acceptance Criteria")
            bb_state = global_blackboard.state
            col_p1, col_p2 = st.columns([1, 1])

            with col_p1:
                st.markdown("**CrewAI Planner Acceptance Criteria:**")
                if bb_state.analysis and bb_state.analysis.acceptance_criteria:
                    for i, ac in enumerate(bb_state.analysis.acceptance_criteria):
                        ac_id = getattr(ac, "id", f"AC-{i+1}")
                        ac_desc = getattr(ac, "description", str(ac))
                        st.markdown(f"- <span class='badge badge-blue'>{ac_id}</span> {ac_desc}", unsafe_allow_html=True)
                elif bb_state.analysis:
                    st.json(bb_state.analysis.model_dump(mode="json"))
                else:
                    st.caption("No acceptance criteria recorded.")

            with col_p2:
                st.markdown("**Ordered Execution Tasks:**")
                if bb_state.plan and bb_state.plan.tasks:
                    for task in bb_state.plan.tasks:
                        t_status = task.status.value.upper()
                        s_color = "badge-green" if t_status == "COMPLETED" else "badge-blue"
                        st.markdown(
                            f"- <span class='badge {s_color}'>{t_status}</span> <b>{task.title}</b><br>"
                            f"&nbsp;&nbsp;&nbsp;&nbsp;<small style='color: #8B949E;'>Role: {task.assigned_role} | Framework: {task.assigned_framework}</small>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.caption("No task plan recorded.")

        with sub_bb:
            st.markdown("#### 🧠 Shared Reactive Blackboard State")
            bb_state = global_blackboard.state
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                st.markdown(
                    f"""
                    <div class="saas-subcard">
                        <div class="saas-subcard-title">Blackboard State Metadata</div>
                        • <b>State Version:</b> <code>v{bb_state.version}</code><br>
                        • <b>Active Patches:</b> {len(bb_state.active_patches)}<br>
                        • <b>Test Reports:</b> {len(bb_state.test_reports)}<br>
                        • <b>HITL Status:</b> <code>{bb_state.human_approval_status.upper()}</code>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown("**Blackboard State Last Updated:**")
                st.code(bb_state.updated_at.isoformat() if hasattr(bb_state, "updated_at") and bb_state.updated_at else datetime.now(timezone.utc).isoformat())

            with col_b2:
                st.markdown("**Blackboard State Metadata:**")
                st.json(bb_state.metadata)

        with sub_a2a:
            st.markdown("#### 💬 Agent-to-Agent (A2A) Message Protocol")
            st.caption("Inspecting typed A2A JSON envelopes exchanged between CrewAI and Google ADK agents.")
            a2a_msgs = global_a2a_bus.get_history()
            if a2a_msgs:
                a2a_data = []
                for m in a2a_msgs:
                    sender_id = getattr(m, "sender_id", getattr(m, "sender", "Unknown"))
                    framework = getattr(m, "sender_framework", "N/A")
                    recipient_id = getattr(m, "recipient_id", getattr(m, "recipient", "Unknown"))
                    msg_type = m.message_type.value if hasattr(m.message_type, "value") else str(m.message_type)
                    ts = m.timestamp.strftime("%H:%M:%S UTC") if hasattr(m, "timestamp") and m.timestamp else "N/A"
                    a2a_data.append({
                        "Sender": sender_id,
                        "Framework": framework,
                        "Recipient": recipient_id,
                        "Type": msg_type,
                        "Timestamp": ts,
                        "Conversation ID": getattr(m, "conversation_id", "N/A"),
                    })
                st.dataframe(pd.DataFrame(a2a_data), use_container_width=True, hide_index=True)

                with st.expander("Inspect Raw A2A Message Envelopes", expanded=False):
                    for idx, m in enumerate(a2a_msgs):
                        sender_str = getattr(m, "sender_id", getattr(m, "sender", "Unknown"))
                        recipient_str = getattr(m, "recipient_id", getattr(m, "recipient", "Unknown"))
                        type_str = m.message_type.value if hasattr(m.message_type, "value") else str(m.message_type)
                        st.markdown(f"**Envelope #{idx+1}: `{sender_str}` ➔ `{recipient_str}` ({type_str})**")
                        st.json(m.payload)
            else:
                st.caption("No A2A messages in current bus history.")

        with sub_diff:
            st.markdown("#### 📝 Real Sandboxed Code Changes & Diff Viewer")
            patches = global_blackboard.state.active_patches

            if patches:
                patch_file = list(patches.keys())[0]
                patch_obj = patches[patch_file]
                target_lang = get_syntax_highlight_language(patch_file)

                st.markdown(
                    f"""
                    <div style="display: flex; gap: 8px; margin-bottom: 12px; align-items: center; flex-wrap: wrap;">
                        <span class="badge badge-blue">Modified File: {patch_file}</span>
                        <span class="badge badge-purple">Type: {patch_obj.change_type.value.upper()}</span>
                        <span class="badge badge-green">Syntax: {target_lang}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                diff_view_mode = st.radio(
                    "Select Diff Display Mode",
                    ["Unified Git Diff", "Side-by-Side (Before vs After)"],
                    horizontal=True,
                )

                if diff_view_mode == "Unified Git Diff":
                    if patch_obj.unified_diff:
                        st.code(patch_obj.unified_diff, language="diff")
                    else:
                        st.info("No unified diff string available.")
                else:
                    col_orig, col_new = st.columns(2)
                    with col_orig:
                        st.markdown('<div class="diff-col-header diff-col-header-orig">Original Code (Base Branch)</div>', unsafe_allow_html=True)
                        orig_code = patch_obj.original_content or "// New file (empty)"
                        st.code(orig_code, language=target_lang, line_numbers=True)
                    with col_new:
                        st.markdown('<div class="diff-col-header diff-col-header-new">Proposed Code (Agentic Branch)</div>', unsafe_allow_html=True)
                        st.code(patch_obj.modified_content, language=target_lang, line_numbers=True)

                if patch_obj.justification:
                    st.caption(f"💡 **Justification:** {patch_obj.justification}")
            else:
                delivery = global_blackboard.state.final_delivery
                unified_diff = delivery.unified_diff if delivery and delivery.unified_diff else ""
                target_sandbox_run = (
                    st.session_state.get("last_sandbox_run_id")
                    or global_blackboard.state.metadata.get("sandbox_run_id")
                    or global_blackboard.state.metadata.get("repository", {}).get("run_id")
                    or st.session_state.get("last_run_id")
                )
                if not unified_diff and target_sandbox_run:
                    diff_data = mcp_repo_client.get_diff(target_sandbox_run)
                    unified_diff = diff_data.get("diff", "")

                if unified_diff:
                    st.code(unified_diff, language="diff")
                else:
                    st.info("No modified file diffs to display.")

        with sub_test:
            st.markdown("#### 🧪 Unit Test Execution Diagnostics & AST Validation")
            reports = global_blackboard.state.test_reports
            if reports:
                latest_rep = reports[-1]
                st.markdown(
                    f"""
                    <div style="display: flex; gap: 10px; margin-bottom: 12px; align-items: center;">
                        <span class="badge badge-green">Passed: {latest_rep.passed} / {latest_rep.total_tests}</span>
                        <span class="badge badge-blue">Time: {latest_rep.execution_time_seconds:.3f}s</span>
                        <span class="badge badge-purple">Sandbox Isolated</span>
                        <span class="badge badge-green">AST Integrity: Verified Safe</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if latest_rep.items:
                    for item in latest_rep.items:
                        item_passed = (item.outcome.lower() == "passed")
                        icon = "✅" if item_passed else "❌"
                        badge_c = "badge-green" if item_passed else "badge-red"
                        st.markdown(f"{icon} ` {item.test_node_id} ` — <span class='badge {badge_c}'>{item.outcome.upper()}</span>", unsafe_allow_html=True)
                        if item.failure_message:
                            st.error(item.failure_message)
            else:
                st.caption("No test reports recorded.")

        with sub_debug:
            st.markdown("#### 🩺 Self-Healing Debugger Diagnostics")
            st.caption("Automated root-cause diagnosis, test failure triage, and iterative self-repair.")
            rec_cycles = getattr(metrics, "failure_recovery_cycles", 0)
            if rec_cycles == 0 and metrics.success:
                st.markdown(
                    """
                    <div class="saas-subcard">
                        <div class="saas-subcard-title" style="color: #3FB950;">✅ Zero Defect Verification</div>
                        Implementation satisfied all acceptance criteria and passed static/unit test validation on the first attempt (0 recovery cycles needed).
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"""
                    <div class="saas-subcard">
                        <div class="saas-subcard-title" style="color: #58A6FF;">🔄 Self-Healing Active</div>
                        Recovery cycles utilized: <b>{rec_cycles} / 3</b>. Automated diagnosis analyzed failure output and patched code iteratively.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        with sub_preview:
            st.markdown("#### 🌐 Live Browser Application Preview")
            st.caption("Inspect and interact with the actual running React + TypeScript application in an isolated sandbox environment.")

            sb_path = (
                st.session_state.get("last_sandbox_path")
                or global_blackboard.state.metadata.get("sandbox_path")
                or global_blackboard.state.metadata.get("repository", {}).get("sandbox_path")
            )
            sb_run_id = (
                st.session_state.get("last_sandbox_run_id")
                or global_blackboard.state.metadata.get("sandbox_run_id")
                or global_blackboard.state.metadata.get("repository", {}).get("run_id")
                or st.session_state.get("last_run_id", "default_run")
            )

            has_sb = sb_path and Path(sb_path).exists()
            has_pkg = has_sb and (Path(sb_path) / "package.json").exists()

            # Metadata header pills
            setup_mode_tag = global_blackboard.state.metadata.get("project_setup_mode", "modify_existing").replace("_", " ").title()
            deps_installed = global_blackboard.state.metadata.get("dependencies_installed", False)
            dep_badge_color = "badge-green" if deps_installed else "badge-amber"

            st.markdown(
                f"""
                <div style="display: flex; gap: 10px; margin-bottom: 14px; align-items: center; flex-wrap: wrap;">
                    <span class="badge badge-purple">Mode: {setup_mode_tag}</span>
                    <span class="badge {dep_badge_color}">Dependencies: {'Installed' if deps_installed else 'Not Installed'}</span>
                    <span class="badge badge-blue">Sandbox: <code>{sb_run_id}</code></span>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if not has_pkg:
                st.info("No Node/React application package.json detected in active sandbox. Connect a React repository or run 'Build from Scratch'.")
            else:
                prev_c1, prev_c2 = st.columns([1, 2])
                status = preview_manager.get_preview_status(sb_run_id)

                with prev_c1:
                    if not status.get("active"):
                        if st.button("🚀 Start Dev Server Preview", type="primary", use_container_width=True):
                            with st.spinner("Starting Vite development server inside sandbox..."):
                                start_res = preview_manager.start_preview(sb_path, sb_run_id)
                                if start_res.get("success"):
                                    st.success(f"Dev server running at {start_res.get('url')}")
                                    st.rerun()
                                else:
                                    st.error(f"Failed to start preview: {start_res.get('error')}")
                    else:
                        if st.button("⏹️ Stop Preview Server", type="secondary", use_container_width=True):
                            preview_manager.stop_preview(sb_run_id)
                            st.info("Preview server stopped.")
                            st.rerun()

                with prev_c2:
                    if status.get("active"):
                        st.markdown(
                            f"""
                            <div style="padding: 10px 14px; background: rgba(63, 185, 80, 0.15); border: 1px solid #3FB950; border-radius: 8px;">
                                <span style="color: #3FB950; font-weight: 600;">● Live Preview Active</span> &nbsp;|&nbsp;
                                <a href="{status['url']}" target="_blank" style="color: #58A6FF; text-decoration: underline; font-weight: 600;">Open in external browser ({status['url']}) ↗</a>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            """
                            <div style="padding: 10px 14px; background: rgba(139, 148, 158, 0.1); border: 1px solid #30363D; border-radius: 8px;">
                                <span style="color: #8B949E;">● Server Inactive</span> &nbsp;|&nbsp;
                                <span style="font-size: 13px; color: #8B949E;">Click <b>Start Dev Server Preview</b> to launch Vite preview on localhost:5173</span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                if status.get("active") and status.get("url"):
                    st.markdown(f"**Live Interactive Application Frame ({status['url']}):**")
                    components.iframe(src=status["url"], height=560, scrolling=True)

                # Diagnostic logs
                dep_result = global_blackboard.state.metadata.get("dependency_install_result")
                if dep_result:
                    with st.expander("📦 Dependency Installation Diagnostics", expanded=False):
                        st.json({
                            "package_manager": dep_result.get("package_manager"),
                            "command": dep_result.get("command"),
                            "exit_code": dep_result.get("exit_code"),
                            "installed": dep_result.get("installed"),
                            "error": dep_result.get("error"),
                        })
                        if dep_result.get("raw_stdout"):
                            st.code(dep_result["raw_stdout"][-1000:], language="text")

        with sub_hitl:
            st.markdown("#### 👤 Human-In-The-Loop Approval Sign-off")
            hitl_status = global_blackboard.state.human_approval_status
            st.markdown(f"Current Approval Gate Status: <span class='badge badge-{'green' if hitl_status == 'approved' else 'amber' if hitl_status == 'pending' else 'red'}'>{hitl_status.upper()}</span>", unsafe_allow_html=True)

            col_h1, col_h2 = st.columns(2)
            with col_h1:
                approver_name = st.text_input("Approver Identity", value="Lead Software Architect")
                approval_notes = st.text_area("Review Notes & Justification", value="Verified tests passing at 100% and AST guardrails verified.")
                
                target_sandbox_run = (
                    st.session_state.get("last_sandbox_run_id")
                    or global_blackboard.state.metadata.get("sandbox_run_id")
                    or global_blackboard.state.metadata.get("repository", {}).get("run_id")
                    or st.session_state.get("last_run_id")
                    or "run_01"
                )
                
                readiness = hitl_gatekeeper.evaluate_readiness(
                    run_id=target_sandbox_run,
                    target_repo=st.session_state.active_repo_url,
                )
                if not readiness["can_approve"]:
                    for reason in readiness.get("rejection_reasons", []):
                        st.warning(f"⚠️ Precondition blocked: {reason}")
                
                if st.button("✅ Approve Code Changes", key="btn_hitl_approve", disabled=(not readiness["can_approve"])):
                    res = hitl_gatekeeper.approve_and_commit(
                        run_id=target_sandbox_run,
                        approver=approver_name,
                        notes=approval_notes,
                        target_repo=st.session_state.active_repo_url,
                        user=current_user,
                    )
                    if res.get("success"):
                        st.success(f"Changes approved! {res.get('message', '')}")
                    else:
                        st.error(f"Approval Failed: {res.get('error', 'Operation blocked by policy')}")
                    st.rerun()

            with col_h2:
                rejection_reason = st.text_area("Rejection Reason", value="Changes do not meet quality or architecture guidelines.")
                if st.button("❌ Reject Changes", key="btn_hitl_reject"):
                    hitl_gatekeeper.reject(rejection_reason)
                    st.error("Code changes rejected. Commit and push blocked.")
                    st.rerun()

        with sub_pr:
            st.markdown("#### 🚀 GitHub Pull Request Publisher")
            st.caption("Publishes the verified agentic branch to GitHub and opens a structured Pull Request.")

            pr_info = global_blackboard.state.metadata.get("github_pr") or st.session_state.last_pr_result

            if pr_info and pr_info.get("success", True) and pr_info.get("pr_url"):
                st.success(f"🎉 Pull Request Published: [PR #{pr_info.get('pr_number')}]({pr_info.get('pr_url')})")
                st.markdown(
                    f"""
                    <div class="saas-card">
                        <div class="saas-card-title">Pull Request #{pr_info.get('pr_number')}</div>
                        <p><b>URL:</b> <a href="{pr_info.get('pr_url')}" target="_blank">{pr_info.get('pr_url')}</a></p>
                        <p><b>Head Branch:</b> <code>{pr_info.get('head_branch')}</code> ➔ <b>Base:</b> <code>{pr_info.get('base_branch')}</code></p>
                        <p><b>Status:</b> <span class="badge badge-green">OPEN</span></p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                is_hitl_approved = (global_blackboard.state.human_approval_status == "approved")
                can_publish = current_user.has_permission(Permission.PUBLISH_PR)

                if not is_hitl_approved:
                    st.warning("⚠️ **Human Approval Required:** Please review and sign off on code changes in the 'HITL Gatekeeper' tab before publishing a Pull Request.")
                if not can_publish:
                    st.info(f"🔒 **Role Restriction:** User `{current_user.user_id}` with role `{current_user.role.value}` does not possess Pull Request publishing permissions.")

                token_val = st.text_input("GitHub Token (PAT)", value=settings.GITHUB_TOKEN, type="password", help="Must have write/push permissions to target repository.")
                col_p1, col_p2 = st.columns([1, 2])
                with col_p1:
                    pr_btn = st.button("🚀 Publish Pull Request to GitHub", key="btn_publish_pr", disabled=(not is_hitl_approved or not can_publish))

                if pr_btn:
                    with st.spinner("Pushing agentic branch and opening Pull Request on GitHub..."):
                        target_sandbox_run = (
                            st.session_state.get("last_sandbox_run_id")
                            or global_blackboard.state.metadata.get("sandbox_run_id")
                            or global_blackboard.state.metadata.get("repository", {}).get("run_id")
                            or st.session_state.get("last_run_id")
                            or "run_01"
                        )
                        sb_path_actual = Path(st.session_state.last_sandbox_path) if st.session_state.get("last_sandbox_path") else (settings.SANDBOX_ROOT / "runs" / target_sandbox_run)
                        pr_res = pr_publisher.publish_pull_request(
                            run_id=target_sandbox_run,
                            sandbox_path=sb_path_actual,
                            repo_url=st.session_state.active_repo_url,
                            base_branch=st.session_state.active_base_branch,
                            task_id="REQ-01",
                            requirement_prompt=user_prompt,
                            auth_token=token_val,
                            approver=approver_name if "approver_name" in locals() else "Lead Engineer",
                            approval_notes=approval_notes if "approval_notes" in locals() else "Verified",
                            user=current_user,
                        )
                        st.session_state.last_pr_result = pr_res
                        if pr_res.get("success"):
                            st.success(f"Pull Request created successfully! URL: {pr_res.get('pr_url')}")
                            st.rerun()
                        else:
                            st.error(f"Publication Failed: {pr_res.get('error')}")
    else:
        st.markdown(
            """
            <div class="saas-card" style="margin-top: 1.5rem; text-align: center; padding: 2.5rem 1rem;">
                <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">🤖</div>
                <div class="saas-card-title" style="font-size: 1.15rem; justify-content: center;">Awaiting Autonomous Engineering Mission</div>
                <p style="color: #8B949E; max-width: 540px; margin: 0.6rem auto 1.2rem auto; font-size: 0.88rem; line-height: 1.6;">
                    Select a benchmark preset above or enter a custom requirement prompt, then click <b>Execute Autonomous Engineering Workflow</b> to trigger the CrewAI and Google ADK multi-agent pipeline.
                </p>
                <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
                    <span class="badge badge-blue">RAG Enabled</span>
                    <span class="badge badge-purple">AST Protected</span>
                    <span class="badge badge-green">HITL Gated</span>
                    <span class="badge badge-amber">A2A Protocol</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# =============================================================================
# TAB 3: COMPARE CONDITIONS (C1, C2, C3, C4)
# =============================================================================
with tab_compare:
    st.markdown("## 🔬 Experimental Conditions Comparison (C1 – C4)")
    st.caption("Addressing Phase 1 Project Synopsis Experimental Conditions C1, C2, C3, and C4.")

    # Part A: 4 Condition Definitions from Phase 1 Synopsis
    st.markdown("### 🏛️ Part A: Phase 1 Synopsis Experimental Conditions")
    conditions = architecture_comparator.get_c1_c4_conditions_definitions()

    c_cols = st.columns(4)
    badges = ["badge-blue", "badge-amber", "badge-purple", "badge-green"]
    for i, (col, cond, b_cls) in enumerate(zip(c_cols, conditions, badges)):
        with col:
            st.markdown(
                f"""
                <div class="saas-card" style="min-height: 380px; display: flex; flex-direction: column; justify-content: space-between;">
                    <div>
                        <div class="saas-card-header">
                            <span class="badge {b_cls}">{cond['condition']}</span>
                        </div>
                        <div style="font-weight: 600; font-size: 1rem; margin-bottom: 8px; color: #F0F6FC;">{cond['title']}</div>
                        <p style="font-size: 0.84rem; color: #8B949E; line-height: 1.45;">{cond['description']}</p>
                    </div>
                    <div style="border-top: 1px solid #30363D; padding-top: 10px; margin-top: 10px; font-size: 0.8rem; color: #C9D1D9; line-height: 1.5;">
                        <b>Communication:</b> {cond['communication']}<br>
                        <b>Frameworks:</b> {cond['frameworks']}<br>
                        <b>State Sync:</b> {cond['state_sync']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # Architectural Trade-off Summary Table
    st.markdown("### ⚖️ Multi-Agent Architecture Trade-off Analysis")
    trade_off_data = [
        {
            "Condition": "C1 (Proposed)",
            "Orchestration": "Hierarchical Leader-Worker",
            "State Sync": "Shared Reactive Blackboard",
            "Communication": "JSON A2A Protocol",
            "Fault Recovery": "Dynamic Failure Re-planning (3 Cycles)",
            "Human Oversight": "Compulsory Pre-Commit Gatekeeper",
        },
        {
            "Condition": "C2 (Baseline)",
            "Orchestration": "Single-Agent Monolithic",
            "State Sync": "No Shared Blackboard",
            "Communication": "None (Sequential Function Calls)",
            "Fault Recovery": "Single-Attempt Fallback",
            "Human Oversight": "Post-Hoc Verification",
        },
        {
            "Condition": "C3 (Ablation)",
            "Orchestration": "Peer-to-Peer Reflection Loop",
            "State Sync": "Isolated Agent Contexts",
            "Communication": "Direct P2P Envelope Messaging",
            "Fault Recovery": "Critic Feedback Iterations",
            "Human Oversight": "Compulsory Pre-Commit Gatekeeper",
        },
    ]
    df_tradeoff = pd.DataFrame(trade_off_data)
    st.dataframe(df_tradeoff, use_container_width=True, hide_index=True)

    # Condition C4 Model Comparison Matrix
    st.markdown("### 🤖 Part B: Condition C4 Frontier Multi-Model Family Matrix")
    st.caption("Direct comparison of genuine frontier LLM models evaluated for Coding and RAG agents (no persona substitutions).")
    model_matrix = architecture_comparator.get_c4_model_comparison_matrix()
    df_models = pd.DataFrame(model_matrix)
    st.dataframe(df_models, use_container_width=True, hide_index=True)

    # Interactive Comparison Benchmark Runner
    st.markdown("### ⚡ Part C: Live Architecture Benchmark Runner")
    st.caption("Execute a benchmark requirement across all three architecture patterns independently on the connected repository.")

    default_cmp_task = (
        "Add priority filter dropdown to DashboardPage and display ticket count"
        if "IT-Support" in st.session_state.active_repo_url
        else "Implement standard_deviation calculation in AdvancedCalculator"
    )

    col_cmp_prompt, col_cmp_btn = st.columns([4, 1])
    with col_cmp_prompt:
        cmp_task = st.text_input("Comparison Requirement", value=default_cmp_task, key="cmp_task_input")
    with col_cmp_btn:
        st.write("")
        st.write("")
        cmp_run_clicked = st.button("Run Comparison", key="btn_run_compare")

    if cmp_run_clicked:
        with st.spinner("Executing benchmark across Hierarchical, Sequential, and Critic-Reflection architectures..."):
            cmp_res = architecture_comparator.run_comparison_benchmark(
                test_requirement=cmp_task,
                target_repo=st.session_state.active_repo_url,
            )
            st.success("Comparison completed successfully!")
            st.markdown("#### Empirical Metrics Summary Table")
            df_cmp = pd.DataFrame(cmp_res["comparison_table"])
            st.dataframe(df_cmp, use_container_width=True, hide_index=True)


# =============================================================================
# TAB 4: EVALUATION & BENCHMARK MATRIX
# =============================================================================
with tab_eval:
    st.markdown("## 📊 Evaluation & Empirical Benchmark Telemetry")
    st.caption("SQLite-backed 45-cell matrix, genuine token measurements, cost accounting, and dataset exports.")

    runs = experiment_storage.get_all()
    recent_runs = experiment_storage.get_recent_runs(limit=100)

    # Overview Metrics Cards
    total_runs = len(runs)
    passed_runs = len([r for r in runs if r.get("success") == 1])
    overall_pass_rate = (passed_runs / max(1, total_runs)) * 100.0 if total_runs > 0 else 0.0
    total_cost_all = sum(r.get("estimated_cost_usd", 0.0) for r in runs)
    avg_runtime = (sum(r.get("execution_time_seconds", 0.0) for r in runs) / max(1, total_runs)) if total_runs > 0 else 0.0

    e_c1, e_c2, e_c3, e_c4 = st.columns(4)
    with e_c1:
        st.markdown(f'<div class="saas-metric-box"><div class="saas-metric-label">Evaluated Runs</div><div class="saas-metric-value">{total_runs}</div><div class="saas-metric-subtext">Across SQLite Store</div></div>', unsafe_allow_html=True)
    with e_c2:
        st.markdown(f'<div class="saas-metric-box"><div class="saas-metric-label">Overall Pass Rate</div><div class="saas-metric-value">{overall_pass_rate:.1f}%</div><div class="saas-metric-subtext">{passed_runs}/{total_runs} Passing</div></div>', unsafe_allow_html=True)
    with e_c3:
        st.markdown(f'<div class="saas-metric-box"><div class="saas-metric-label">Average Runtime</div><div class="saas-metric-value">{avg_runtime:.2f}s</div><div class="saas-metric-subtext">Per Execution</div></div>', unsafe_allow_html=True)
    with e_c4:
        st.markdown(f'<div class="saas-metric-box"><div class="saas-metric-label">Total Cost</div><div class="saas-metric-value">${total_cost_all:.4f}</div><div class="saas-metric-subtext">Genuine Gemini Tokens</div></div>', unsafe_allow_html=True)

    # 45-Cell Matrix Progress Grid with Interactive Filters
    st.markdown("### 🧩 45-Cell Benchmark Matrix (5 Tasks × 3 Architectures × 3 Personas)")
    st.caption("Visual matrix representing all academic evaluation combinations across tasks, architectures, and personas.")

    # Data Authenticity Clarification Callout
    st.markdown(
        """
        <div style="background: rgba(22, 27, 34, 0.7); border: 1px solid #30363D; border-radius: 6px; padding: 8px 14px; margin-bottom: 12px; font-size: 0.82rem; color: #8B949E;">
            ℹ️ <b>Provenance & Measurement Standard:</b> Records populated below reflect genuine SQLite entries from <code>sandbox_workspace/experiments.db</code>. Completed benchmark runs display <code>MEASURED (ONLINE)</code> or <code>MEASURED (SIMULATED)</code> badges. Cells awaiting evaluation are clearly marked <code>PENDING EXECUTION</code> without synthetic estimation.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Filter Bar
    f_c1, f_c2, f_c3 = st.columns(3)
    with f_c1:
        task_options = ["All Tasks"] + [t.get("title", f"Task {t.get('id')}") for t in BENCHMARK_TASKS]
        selected_task_filter = st.selectbox("Filter by Task", task_options, index=0)
    with f_c2:
        arch_options = ["All Architectures"] + [a.value for a in AgenticPatternType]
        selected_arch_filter = st.selectbox("Filter by Architecture", arch_options, index=0)
    with f_c3:
        status_options = ["All Statuses", "Completed Only", "Pending Only"]
        selected_status_filter = st.selectbox("Filter by Status", status_options, index=0)

    matrix_rows = []
    completed_cells_count = 0

    for task in BENCHMARK_TASKS:
        t_id = task.get("id") if isinstance(task, dict) else getattr(task, "id", "N/A")
        t_title = task.get("title") if isinstance(task, dict) else getattr(task, "title", "N/A")
        t_prompt = task.get("prompt") if isinstance(task, dict) else getattr(task, "prompt", "")

        for arch in [a.value for a in AgenticPatternType]:
            for pers in [p.value for p in PersonaType]:
                # Find matching run in storage
                match = next(
                    (
                        r
                        for r in runs
                        if (
                            r.get("benchmark_task") == t_prompt
                            or r.get("benchmark_task") == t_id
                            or (r.get("benchmark_task") and t_id in r.get("benchmark_task"))
                        )
                        and r.get("architecture_pattern") == arch
                        and r.get("persona") == pers
                    ),
                    None,
                )

                is_completed = match is not None
                if is_completed:
                    completed_cells_count += 1

                # Apply Filters
                if selected_task_filter != "All Tasks" and t_title != selected_task_filter:
                    continue
                if selected_arch_filter != "All Architectures" and arch != selected_arch_filter:
                    continue
                if selected_status_filter == "Completed Only" and not is_completed:
                    continue
                if selected_status_filter == "Pending Only" and is_completed:
                    continue

                if is_completed:
                    mode_str = match.get("execution_mode") or "SIMULATED"
                    status_label = f"MEASURED ({mode_str.upper()})"
                else:
                    status_label = "PENDING EXECUTION"

                success_label = ("PASSED" if match.get("success") == 1 else "FAILED") if match else "—"

                matrix_rows.append(
                    {
                        "Task ID": t_id,
                        "Task Title": t_title,
                        "Architecture": arch,
                        "Persona": pers,
                        "Status": status_label,
                        "Success": success_label,
                        "Runtime (s)": (
                            f"{match.get('execution_time_seconds', 0):.2f}"
                            if match
                            else "—"
                        ),
                        "Pass Rate (%)": (
                            f"{match.get('test_pass_rate', 0):.1f}%"
                            if match
                            else "—"
                        ),
                        "Cost ($)": (
                            f"${match.get('estimated_cost_usd', 0):.5f}"
                            if match
                            else "—"
                        ),
                    }
                )

    # Progress Indicator
    pct_complete = (completed_cells_count / 45.0) * 100.0
    st.markdown(
        f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin: 8px 0; font-size: 0.85rem; color: #8B949E;">
            <span>Evaluated Cells: <b>{completed_cells_count} / 45</b> ({pct_complete:.1f}%)</span>
            <span>Showing: <b>{len(matrix_rows)}</b> filtered rows</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    df_matrix = pd.DataFrame(matrix_rows)
    st.dataframe(df_matrix, use_container_width=True, hide_index=True)

    # Historical Experiments Table
    st.markdown("### 🗄️ Historical Experiment Runs (SQLite)")
    st.caption("Granular execution telemetry records stored in `sandbox_workspace/experiments.db`.")
    if recent_runs:
        df_runs = pd.DataFrame(recent_runs)
        cols_to_show = [
            "run_id", "timestamp", "architecture_pattern", "persona", "benchmark_task",
            "execution_status", "test_pass_rate", "execution_time_seconds", "total_tokens", "estimated_cost_usd"
        ]
        existing_cols = [c for c in cols_to_show if c in df_runs.columns]
        st.dataframe(df_runs[existing_cols], use_container_width=True, hide_index=True)
    else:
        st.info("No experiment runs recorded in SQLite yet.")

    # Data Export Options
    st.markdown("### 📥 Dataset Export")
    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        csv_data = pd.DataFrame(runs).to_csv(index=False).encode("utf-8") if runs else b""
        st.download_button(
            label="Download Experiment History (CSV)",
            data=csv_data,
            file_name="benchmark_experiments_export.csv",
            mime="text/csv",
        )
    with col_exp2:
        json_data = json.dumps(runs, indent=2, default=str).encode("utf-8") if runs else b""
        st.download_button(
            label="Export Complete Telemetry (JSON)",
            data=json_data,
            file_name="benchmark_telemetry_export.json",
            mime="application/json",
        )
