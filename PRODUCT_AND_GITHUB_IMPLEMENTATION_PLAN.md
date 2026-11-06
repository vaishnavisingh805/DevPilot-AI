# Product Development & GitHub Integration Master Plan

**Project:** Multi-Agent AI System for Autonomous Software Engineering  
**Workspace:** `D:\MultiAgent-Software-Engineering`  
**Document Type:** Technical Architecture, Product Specification & Academic Alignment  
**Version:** 2.0.0-PROD  
**Authors:** Vaishnavi Singh (230508) & Muskan Patni (230534)  
**Project Guide:** Prof. Pranshu Tiwari | BML Munjal University  
**Date:** November 1, 2026  

---

## Executive Overview

This document establishes the implementation roadmap for elevating the Multi-Agent Autonomous Software Engineering platform from an academic prototype into a production-grade, enterprise-ready SaaS application. 

It synthesizes:
1. **The Phase 1 Project Synopsis commitments** (five-agent cooperative model, RAG repository indexing, Git branch isolation, and the C1–C4 experimental conditions).
2. **The Milestone 3 multi-agent core** (live CrewAI + Google ADK integration, A2A bus, Shared Blackboard, MCP tools, and HITL gatekeeper).
3. **The Phase 2 product requirements** (genuine GitHub repository integration, a premium dark-themed SaaS interface with 4-tab top navigation, and comprehensive academic alignment).

---

## PART 1: Comprehensive GitHub Integration Audit

### 1.1 Existing Implementation vs. Production Requirements

| Feature Area | Current State in Codebase | Limitations / Missing Gaps | Target Production Architecture |
|---|---|---|---|
| **Repository URL Input** | Local hardcoded path (`sample_repo`) in `mcp_servers/repo_tool/server.py`. | No URL parser, no support for `https://github.com/owner/repo` or SSH URLs. | Dedicated `RepoConfig` model supporting HTTPS, SSH, and branch selection. |
| **Cloning & Fetching** | `shutil.copytree` from local `sandbox_workspace/sample_repo/`. | Does not interact with Git; cannot pull remote repos or handle large codebases. | Genuine `git clone --depth 1` into isolated sandbox directory with timeout & size limits. |
| **Private Repo Auth** | None. | Cannot authenticate against private GitHub enterprise or user repos. | Encrypted GitHub PAT / Fine-Grained Token input; environment-masked injection. |
| **Branch Creation** | Run ID string generated (`run_...`), but no Git branches created. | Changes cannot be pushed to a Git remote as an isolated branch. | Automated branch creation: `git checkout -b agentic/{task_id}-{run_id}`. |
| **Git Status & Diff** | Python `difflib.unified_diff` on overwritten file content. | Does not track Git staging, multi-file renames, untracked files, or deletions. | Real `git diff` and `git status --porcelain` execution via Git CLI / GitPython. |
| **File Indexing & RAG** | ChromaDB is installed in `.venv`, but no codebase indexer exists. | Agents lack repository-wide symbol awareness, dependency graphs, and semantic search. | AST-aware code chunker, ChromaDB vector store, and `RepositoryRAGAgent`. |
| **MCP Repo Tools** | Filesystem tools (`create_isolated_sandbox`, `apply_patch_to_sandbox`). | Operates as raw disk I/O; lacks Git semantics (branches, commit staging, remotes). | Upgraded MCP Git Server exposing: `clone_repo`, `create_branch`, `git_diff`, `stage_and_commit`. |
| **Test Execution** | `mcp_servers/test_runner/server.py` runs `pytest` via `subprocess.run`. | Hardcoded to local sandbox Python environment; lacks dynamic virtualenv detection. | Dynamic test runner supporting project venvs, pytest discovery, and polyglot runners. |
| **Human Approval** | `HITLGatekeeper` blocks local file copy to `sample_repo`. | Approves local disk writes only; cannot publish changes to GitHub. | Gatekeeper unlocks Git commit signing, branch pushing, and Pull Request synthesis. |
| **Push & PR Creation** | Completely missing. | No mechanism to open Pull Requests on GitHub. | GitHub REST API v3 integration: pushes branch and opens formatted, evidence-backed PR. |

---

### 1.2 GitHub Security & Credential Isolation Architecture

To ensure zero token leakage and complete sandbox containment:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       GITHUB SECURITY & ISOLATION MODEL                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   [Developer UI]                                                            │
│         │ (Repo URL + GitHub Personal Access Token)                         │
│         ▼                                                                   │
│   [Secret Masker] ──► Token stored in-memory in SessionState only           │
│         │              (NEVER logged to Blackboard, A2A, or Provenance)     │
│         ▼                                                                   │
│   [MCP Git Client]                                                          │
│         │                                                                   │
│         ▼ (Subprocess invocation with Git credential helper)                │
│   [Ephemeral Git Sandbox] ──► .git/config contains NO hardcoded tokens      │
│         │                                                                   │
│         ├──► 1. Clone remote repository to sandbox_workspace/runs/<run_id>   │
│         ├──► 2. Create branch: agentic/feature-<run_id>                     │
│         ├──► 3. Agent modifications applied strictly in isolated branch     │
│         ├──► 4. Run pytests inside sandbox                                  │
│         │                                                                   │
│   [HITL Gatekeeper Quarantine]                                              │
│         │                                                                   │
│         ├─── [REJECTED] ──► Destroy sandbox; zero remote modifications      │
│         │                                                                   │
│         └─── [APPROVED] ──► Push branch & Create GitHub Pull Request via API│
│                             (Requires cryptographic approver sign-off)      │
└─────────────────────────────────────────────────────────────────────────────┘
```

1. **Credential Hygiene:**
   - Tokens are passed via runtime environment variables to Git subprocesses (`GIT_ASKPASS` or ephemeral header `Authorization: token <PAT>`), never written to `.git/config` on disk.
   - All provenance trackers and A2A loggers run an automatic regex sanitizer that redacts strings matching `ghp_[A-Za-z0-9_]{36}` or `github_pat_[A-Za-z0-9_]{82}`.
2. **Repository Quarantine:**
   - The original base branch (`main` / `master`) is marked read-only.
   - All agent commits occur on a dedicated `agentic/` branch.
   - Force-push (`git push --force`) is disabled in the MCP tool layer.

---

## PART 2: Premium SaaS Dashboard Redesign

The dashboard transitions from a multi-tab student interface to an enterprise-grade Autonomous Software Engineering Studio.

### 2.1 Aesthetic & Design System

- **Color Palette (Minimalist Charcoal & Restrained Blue):**
  - Background Base: `#0B0E14` (Deep obsidian charcoal)
  - Surface Card: `#151B23` (Elevated dark slate)
  - Border Subdued: `#30363D` (Crisp 1px borders)
  - Accent Primary: `#2F81F7` (Electric GitHub blue)
  - Accent Subtle: `#1F6FEB` (Interactive hover state)
  - Success Indicator: `#238636` (Muted emerald green)
  - Warning/Failure: `#DA3633` (Ruby crimson)
  - Typography: Inter for UI body, JetBrains Mono for code diffs and tokens.
- **Top Navigation Bar:**
  - Modern horizontal tab bar with active indicator underline:
    `[ 1. Knowledge Base ]   [ 2. Ask ]   [ 3. Compare Conditions ]   [ 4. Evaluation ]`
- **Collapsible Control Sidebar:**
  - Workspace selector (Active Repository, Git Remote vs Local Sandbox).
  - Model & API Key status pill (`gemini-3.8-flash` • `Live Mode` • `HITL Active`).
  - Active branch badge and commit SHA.

---

### 2.2 Functional Layout Across the 4 Required Top Tabs

```
═══════════════════════════════════════════════════════════════════════════════════════════
   🤖 ANTIGRAVITY ENGINE   │   [1. Knowledge Base]  [2. Ask]  [3. Compare]  [4. Evaluation]
═══════════════════════════════════════════════════════════════════════════════════════════
```

#### Tab 1: Knowledge Base (Repository Explorer & RAG Context Engine)
*Addresses Muskan Patni's Phase 1 module (Repository/RAG Agent).*
- **Repository Connector:**
  - Input: GitHub Repo URL (`https://github.com/...`) + Auth Token (optional for private).
  - Local Fallback: Toggle to use built-in `sandbox_workspace/sample_repo`.
  - Actions: `Clone / Fetch Repository`, `Re-index Codebase`.
- **Repository File Explorer:**
  - Interactive file tree view with file size and type icons.
  - In-browser code preview with syntax highlighting and line numbers.
- **RAG Codebase Indexing & Embeddings Status:**
  - Vector database inspector (ChromaDB status, total chunks indexed, chunk size: 500 tokens).
  - Semantic Code Search Playground: Query the codebase with natural language (e.g., *"Where is error handling defined in statistical functions?"*) to inspect retrieved context chunks before agent execution.
- **Repository Test & Dependency Discovery:**
  - Displays detected test runner (`pytest`), test files, and existing coverage baseline.

#### Tab 2: Ask (Agent Engineering Studio & Mission Control)
*Addresses Vaishnavi Singh's Phase 1 module (Manager/Planner Agent, Blackboard, HITL, A2A).*
- **Requirement Input Deck:**
  - Pre-configured benchmark task dropdown (`BENCH-01` through `BENCH-05`) or freeform requirement editor.
  - Target branch name selector (`agentic/feature-...`).
  - Engineering Persona selector (`Balanced-Engineer`, `Strict-Architect`, `Permissive-Prototyper`).
  - Primary CTA: `Run Autonomous Multi-Agent Pipeline`.
- **Live Execution Stepper & Multi-Agent Telemetry:**
  - Visual 5-stage progress ribbon:
    `[1. Guardrails] ──► [2. Planning] ──► [3. RAG Search] ──► [4. Coding & Tests] ──► [5. Audit]`
  - Split View:
    - **Left Pane:** Live Reactive Shared Blackboard (Version state, decomposed tasks, acceptance criteria).
    - **Right Pane:** Real-time A2A Protocol Stream (Live message envelopes, correlation IDs, SHA-256 signatures).
- **Interactive Human-In-The-Loop (HITL) Gatekeeper:**
  - Side-by-side unified code diff viewer (`a/src/calculator.py` vs `b/src/calculator.py`).
  - Pytest evidence card (Pass/Fail breakdown, assertion logs, duration).
  - AST security clearance badge.
  - Reviewer Action Panel:
    - Input: Reviewer identity and sign-off notes.
    - Buttons: `✅ Approve & Commit to Local`, `🚀 Approve & Open GitHub Pull Request`, `❌ Reject & Trigger Re-planning`.
- **Validated Delivery Package & Cryptographic Lineage:**
  - SHA-256 Merkle provenance tree display.
  - One-click JSON delivery package download.

#### Tab 3: Compare Conditions (Academic Architecture & Persona Lab)
*Addresses the Phase 1 Synopsis Experimental Conditions C1, C2, C3, and C4.*
- **Condition Comparator Grid (Side-by-Side Execution):**
  - **Condition 1 (C1 - Proposed System):** Hierarchical Multi-Agent with Shared Blackboard & A2A.
  - **Condition 2 (C2 - Monolithic Baseline):** Sequential single-agent pipeline without Blackboard or subagents.
  - **Condition 3 (C3 - Protocol Comparison):** Peer-to-Peer direct reflection messaging without Blackboard.
  - **Condition 4 (C4 - Persona / Model Comparison):** Comparing temperature and system instruction rigor (Strict vs Balanced vs Permissive).
- **Live Comparison Runner (Zero Multipliers):**
  - Execute a single task across all selected conditions simultaneously.
  - Real-time comparative metric table: Pass Rate (%), Latency (s), Total Tokens, API Cost ($), Recovery Loops.
- **Architectural Trade-Off Visualizer:**
  - Interactive bar charts comparing coordination overhead vs defect recovery capability.

#### Tab 4: Evaluation (Empirical Research & Benchmark Analytics)
*Addresses the Faculty 40+ Run Requirement and persistent SQLite analytics.*
- **KPI Summary Cards:**
  - Total Recorded Experiments, Aggregate Success Rate, Average Runtime, Mean Cost per Run, Merkle Verification Rate.
- **45-Cell Matrix Completion Grid:**
  - Interactive 5×3×3 matrix showing completion status across all 5 tasks, 3 architectures, and 3 personas.
- **Historical Runs Explorer:**
  - Full-featured SQLite table with search, pagination, and multi-column filtering (Architecture, Persona, Status, Task).
- **Failure Root Cause Inspector:**
  - Deep-dive drawer for failed runs: AST violations, syntax errors, and test assertion failures.
- **Data Export Center:**
  - Direct download buttons for `benchmark_results.csv` and `benchmark_results.json` for paper publication.

---

## PART 3: Integrated System Architecture

The following diagram illustrates how all nine core subsystems interact from GitHub URL input to Pull Request creation:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              INTEGRATED END-TO-END SYSTEM TOPOLOGY                              │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘

 1. USER INTERACTION
    [Developer] ──► Top Nav: "Ask" / "Knowledge Base"
                         │  • Enters GitHub Repo URL & Personal Access Token
                         │  • Enters Software Engineering Requirement
                         ▼
 2. SECURITY & REPO INGESTION
    [Prompt Guardrail] ──► Sanitizes requirement for prompt injection
                         │
    [MCP Git Tool]    ──► git clone --depth 1 https://github.com/org/repo
                         │  • Provisions isolated directory: sandbox_workspace/runs/<run_id>/
                         │  • Creates feature branch: agentic/task-<run_id>
                         ▼
 3. CODEBASE RAG INDEXING (Muskan Patni Module)
    [Repository/RAG Agent] ──► Scans sandbox files ──► AST Symbol Chunker
                                    │
                                    ▼
                               [ChromaDB Local Vector Store]
                                    │ (Returns top-k relevant functions, tests, classes)
                                    ▼
 4. HIERARCHICAL REASONING & PLANNING (Vaishnavi Singh Module)
    [CrewAI Planner Agent] ──► Crew.kickoff() decomposes requirement into Acceptance Criteria
                         │
                         ▼
    [Shared Blackboard] ◄── Stores RequirementAnalysis & ExecutionPlan (v1)
                         │
                         ▼
    [CrewAI Manager]     ──► Dispatches tasks via A2A Protocol Envelopes
                                    │
                                    ▼
 5. CODE MODIFICATION & VERIFICATION (Dual Framework Workers)
    [Google ADK Coder]   ──► LlmAgent consumes RAG context & plan ──► Generates Code Patch
                         │   • MCP Repo Tool applies patch inside sandbox
                         │
    [Google ADK Tester]  ──► Synthesizes targeted test suite based on Acceptance Criteria
                         │   • MCP Test Runner executes pytest inside sandbox
                         ▼
 6. DEFECT CLASSIFICATION & RE-PLANNING LOOP
    [Google ADK Debugger]──► If tests fail: analyzes stack trace & classifies failure cause
                         │   • Posts failure diagnosis to Shared Blackboard
                         │   • Manager triggers A2A re-plan (up to 2 recovery cycles)
                         ▼
 7. QUALITY AUDIT & CRYPTOGRAPHIC PROVENANCE
    [CrewAI Auditor]     ──► Validates 100% test pass rate & executes AST security scan
                         │   • Generates Merkle lineage block with SHA-256 parent hash
                         ▼
 8. HUMAN-IN-THE-LOOP (HITL) GATEKEEPER
    [Dashboard UI]       ──► Presents side-by-side Diff, Pytest Output, & Provenance
                         │
                         ├──► [REJECT] ──► Aborts run; sandbox destroyed; 0 remote modifications
                         │
                         └──► [APPROVE] ──► Reviewer signs off cryptographically
                                                 │
 9. GITHUB REMOTE MERGE & PR CREATION            ▼
    [MCP Git Tool]       ──► git push origin agentic/task-<run_id>
                         │
    [GitHub API]         ──► POST /repos/{owner}/{repo}/pulls
                             • Creates Pull Request with test evidence & acceptance criteria checklist
```

---

## PART 4: Academic Alignment (Phase 1 Synopsis C1–C4 vs. Current 45-Cell Matrix)

### 4.1 Comparative Analysis

The original Phase 1 Synopsis and the current Phase 2 implementation share identical foundational goals, but structure their evaluation variables slightly differently:

| Dimension | Phase 1 Synopsis (Sept 2026) | Current Phase 2 Implementation | Scientific Alignment & Reconciliation |
|---|---|---|---|
| **Scope of Evaluation** | 10 software engineering tasks evaluated across 4 conditions ($10 \times 4 = 40\text{ runs}$). | 5 tasks $\times$ 3 architectures $\times$ 3 personas ($5 \times 3 \times 3 = 45\text{ runs}$). | Both fulfill the faculty requirement of **$\ge 40$ recorded empirical runs**. |
| **Condition 1 (C1)** | Hierarchical architecture with Blackboard communication (Primary proposed design). | `Hierarchical-Blackboard-A2A` pattern. | **Exact 1:1 Match**. Evaluates the full multi-agent cooperative system. |
| **Condition 2 (C2)** | Sequential architecture with same agents and tools (Single straight pipeline). | `Sequential Baseline` pattern. | **Exact 1:1 Match**. Tests whether managerial decomposition improves upon monolithic execution. |
| **Condition 3 (C3)** | Hierarchical architecture with peer-to-peer messaging instead of Blackboard. | `Critic-Reflection Loop` pattern (P2P generator-critic direct messaging). | **Direct Conceptual Match**. C3 evaluated P2P messaging vs Shared Blackboard. The Critic-Reflection pattern implements direct inter-agent messaging without blackboard state mutations. |
| **Condition 4 (C4)** | Hierarchical architecture with different LLMs for Coding and RAG agents. | Persona variations (`Strict-Architect`, `Balanced-Engineer`, `Permissive-Prototyper`). | **Partial Gap**. Phase 2 currently benchmarks prompt/persona variations (temperature 0.1 vs 0.2 vs 0.4) using `gemini-3.8-flash`, rather than contrasting distinct LLM model families (e.g. Gemini vs Claude/GPT). |

---

### 4.2 Recommended Unified Evaluation Design

To ensure **zero silent omissions** of the original Phase 1 Synopsis commitments, the evaluation harness will formally unify both structures into a comprehensive two-tier evaluation framework:

#### Tier 1: The Canonical C1–C4 Architectural Ablation Suite (10 Tasks × 4 Conditions = 40 Runs)
Directly maps to Section 2.3 of the Phase 1 Synopsis:
- **C1 (Proposed System):** Hierarchical Dual-Framework (CrewAI Planner/Manager + ADK Coder/Tester) with Shared Blackboard.
- **C2 (Monolithic Baseline):** Sequential pipeline without subagent decomposition or Blackboard.
- **C3 (Protocol Ablation):** Direct Peer-to-Peer A2A messaging without the Shared Blackboard (evaluating whether a blackboard reduces communication overhead).
- **C4 (Model/Persona Ablation):** Multi-model evaluation comparing `gemini-3.8-flash` against `gemini-1.5-pro` (or temperature-varied strict persona) for the coding and RAG agents.

#### Tier 2: The Extended Matrix (45 Cells)
Preserves the fully prepared 5 tasks $\times$ 3 architectures $\times$ 3 personas matrix in `scripts/run_benchmark_matrix.py`, providing deep statistical distributions for the final report.

#### Dashboard Representation:
The redesigned **"Compare Conditions"** top tab will feature dedicated sub-views for:
1. `Condition 1 vs Condition 2` (Hierarchical vs Sequential)
2. `Condition 1 vs Condition 3` (Shared Blackboard vs Peer-to-Peer Messaging)
3. `Condition 1 vs Condition 4` (Model & Persona Variations)

This completely preserves academic continuity, demonstrates that every claim from the Phase 1 defense is addressed, and provides rigorous empirical data for the final dissertation.

---

## PART 5: Exact Files to Modify & Implementation Roadmap

### 5.1 File Modification Matrix

| Module / Component | Target File Path | Nature of Change |
|---|---|---|
| **Git Operations** | `mcp_servers/repo_tool/git_manager.py` *(New)* | Implement genuine Git CLI wrapper (`clone`, `branch`, `diff`, `commit`, `push`). |
| **Git MCP Tools** | `mcp_servers/repo_tool/server.py` | Add MCP tools: `clone_github_repo`, `create_git_branch`, `push_and_create_pr`. |
| **GitHub API Client**| `core/github/pr_client.py` *(New)* | Implement GitHub REST API client for creating formatted Pull Requests. |
| **RAG / Vector Store**| `core/rag/indexer.py` *(New)* | Implement AST code chunker, ChromaDB embedding indexer, and semantic search. |
| **RAG Agent** | `agents/google_adk/rag_agent.py` *(New)* | Implement official `RepositoryRAGAgent` using Google ADK to retrieve relevant context. |
| **HITL Gatekeeper** | `core/hitl/approval_gate.py` | Update `approve_and_commit` to support pushing branches and creating PRs on GitHub. |
| **SaaS Styling** | `dashboard/styles.css` | Rewrite with enterprise dark theme, Inter typography, charcoal cards, and blue accents. |
| **SaaS App Shell** | `dashboard/app.py` | Redesign with 4-tab top navigation (`Knowledge Base`, `Ask`, `Compare`, `Evaluation`). |
| **Condition Comparator**| `dashboard/views/compare_view.py` *(New)*| Implement dedicated view for Phase 1 C1–C4 condition benchmarks. |
| **Settings & Env** | `config/settings.py` | Add `GITHUB_TOKEN`, `DEFAULT_REPO_URL`, and `CHROMA_PERSIST_DIR` fields. |

---

### 5.2 Phased Implementation Order

```
Phase 2.1: Foundation & Git Tooling (Muskan Patni Module)
  ├── 1. Implement core/github/pr_client.py and Git CLI operations in mcp_servers/repo_tool/
  ├── 2. Implement core/rag/indexer.py and ChromaDB vector indexing
  └── 3. Implement agents/google_adk/rag_agent.py

Phase 2.2: HITL & PR Synthesis (Vaishnavi Singh Module)
  ├── 4. Connect HITL Gatekeeper to GitHub PR creation API with test evidence formatting
  └── 5. Update Blackboard state schema to hold retrieved RAG chunks and PR URLs

Phase 2.3: SaaS Dashboard Redesign (Collaborative Integration)
  ├── 6. Overhaul dashboard/styles.css with premium dark theme and typography
  ├── 7. Restructure dashboard/app.py into the 4 top-level views:
  │      ├── View 1: Knowledge Base (Repo tree + RAG search)
  │      ├── View 2: Ask (Mission Control, Blackboard, A2A, HITL, PR Creation)
  │      ├── View 3: Compare Conditions (C1-C4 experimental laboratory)
  │      └── View 4: Evaluation (45-run matrix, SQLite telemetry, CSV export)
  └── 8. End-to-end regression testing and dry-run validation

Phase 2.4: Academic Evaluation Campaign
  └── 9. Authorize and execute live benchmark runs upon user approval
```

---

## Conclusion & Next Step

This audit confirms that all fundamental multi-agent, blackboard, and guardrail components are sound and passing all 47 regression tests. Transitioning to full product development requires adding the Git/GitHub integration layer, the RAG repository indexer, and restructuring the dashboard into the 4-tab enterprise layout.

**Status:** Standing by for user authorization to begin Phase 2.1 implementation.

