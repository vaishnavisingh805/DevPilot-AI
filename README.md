# Multi-Agent AI System for Autonomous Software Engineering: Converting Developer Requirements into Validated Code Changes

**Phase 2 Academic Project**  
*Built with CrewAI, Google Agent Development Kit (ADK), Model Context Protocol (MCP), and A2A Communication Protocol.*  
*Target LLM: `gemini-3.8-flash` via Google GenAI SDK (`google-genai` 2.34.0 & `google-adk` 2.13.0)*

---

## 🌟 Executive Summary

This project implements an enterprise-grade, federated multi-agent system that converts developer requirements into tested, verified, and security-audited code changes. The system adheres strictly to the 12 compulsory academic requirements:

1. **Dual Agentic Frameworks**: Uses **CrewAI** (Management, Planning, Governance, and QA Audit) and **Google ADK** (`google-adk` LlmAgent for Code Generation, Test Suite Synthesis, and AST Debugging).
2. **A2A (Agent-to-Agent) Protocol**: Standardized message envelope routing with SHA-256 cryptographic signatures, correlation IDs, and non-repudiation.
3. **Shared Blackboard Architecture**: Centralized, thread-safe (`RLock`) reactive state machine with monotonic versioning (`v0` -> `vN`) and observer callbacks.
4. **Model Context Protocol (MCP)**: Two external tools integrated via official FastMCP servers over JSON-RPC 2.0 stdio:
   - `mcp-repository-tool`: Ephemeral sandbox worktree isolation and human-gated commit.
   - `mcp-test-runner`: Sandboxed pytest execution and syntax verification.
5. **Strict Pydantic v2 Structured Outputs**: 100% typed data models for requirements, plans, diffs, test reports, metrics, and provenance.
6. **Multiple Agentic Design Patterns**: Supports three genuinely independent architectures:
   - `Hierarchical-Blackboard-A2A` (Full multi-agent)
   - `Sequential Baseline` (Monolithic single agent)
   - `Critic-Reflection Loop` (Generator-Critic iterative refinement)
   - *Zero mathematical scaling multipliers or synthetic results.*
7. **Callback Lifecycle System**: Comprehensive telemetry monitoring intermediate outputs, errors, tool invocations, and agent transitions.
8. **Multi-Layer Security Guardrails**: Prompt injection defense, AST static analysis for dangerous syscalls (`os.system`, `subprocess`, `eval`), and sandbox boundary enforcement.
9. **Cryptographic Provenance**: Tamper-evident SHA-256 chained execution lineage for complete auditability.
10. **Quantitative Performance Evaluation & SQLite Persistence**: Real-time tracking of execution latency, token counts, pricing economics, and persistent storage in `sandbox_workspace/experiments.db`.
11. **Professional Interactive Dashboard**: Full-featured 7-tab Streamlit web application with live backend telemetry and Human-In-The-Loop gatekeeper.
12. **Cloud Deployment Readiness**: Production multi-stage `Dockerfile`, `docker-compose.yml`, health checks, and environment configurations.

---

## 🏗️ System Architecture

```
                    ┌────────────────────────────────────────────────────────┐
                    │               DEVELOPER / FACULTY UI                   │
                    │         (Streamlit Mission Control Dashboard)          │
                    └───────────────────────────┬────────────────────────────┘
                                                │
                                                ▼
                    ┌────────────────────────────────────────────────────────┐
                    │            MULTI-LAYER SECURITY GUARDRAILS             │
                    │   • Prompt Injection Detector   • AST Safety Scanner   │
                    └───────────────────────────┬────────────────────────────┘
                                                │
                                                ▼
     ┌──────────────────────────────────────────────────────────────────────────────────┐
     │                             SHARED BLACKBOARD ENGINE                             │
     │   • Requirements & Acceptance Criteria  • Work Breakdown Structure (Tasks)       │
     │   • Code Change Proposals & Diffs        • Sandboxed Pytest Verification Reports │
     │   • Cryptographic Provenance Chain       • Human-In-The-Loop Sign-Off Status    │
     └───────────────────────────▲──────────────────────────────▲──────────────────────┘
                                 │                              │
                     A2A Protocol Envelopes         A2A Protocol Envelopes
                                 │                              │
                                 ▼                              ▼
     ┌─────────────────────────────────────────┐  ┌─────────────────────────────────────┐
     │             CREWAI FRAMEWORK            │  │           GOOGLE ADK FRAMEWORK      │
     │  • Planner Agent (Requirements Breakdown│  │  • Coder Agent (Patch Synthesis)    │
     │  • Manager Agent (A2A Dispatcher)       │  │  • Test Generator (Pytest Suites)   │
     │  • Auditor Agent (QA Delivery Sign-Off) │  │  • Debugger Agent (Root Cause Fix)  │
     │                                         │  │  • RAG Agent (Codebase Intelligence)│
     └─────────────────────────────────────────┘  └──────────────────┬──────────────────┘
                                                                     │
                                                       Model Context Protocol (MCP)
                                                                     │
                                                                     ▼
                                                  ┌─────────────────────────────────────┐
                                                  │          MCP TOOL SERVERS           │
                                                  │  • mcp-repository-tool (Git/Sandbox)│
                                                  │  • mcp-test-runner (Pytest Runner)  │
                                                  └─────────────────────────────────────┘
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.11.x (tested on Python 3.11.9)
- PowerShell (Windows) or Bash (Linux/macOS)
- Google AI Studio Gemini API Key

### 2. Installation
```powershell
# Navigate to workspace
cd D:\MultiAgent-Software-Engineering

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install / update dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration
Ensure `.env` exists in the project root:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
EXECUTION_MODE=live
DEFAULT_MODEL=gemini-3.8-flash
TEMPERATURE=0.2
REQUIRE_HUMAN_APPROVAL=true
ENABLE_PROMPT_INJECTION_CHECK=true
ENABLE_AST_SECURITY_SCAN=true
```

### 4. Running the Complete Pytest Suite
```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
*Current test suite: **42 passed tests**, 0 failures across 12 test modules.*

### 5. Launching the Interactive Streamlit Dashboard
```powershell
.\.venv\Scripts\streamlit.exe run dashboard/app.py
```
*Access UI at:* `http://localhost:8501`

---

## 📊 Comprehensive Documentation Suite

| Document | Description |
| :--- | :--- |
| [`FINAL_PROJECT_REPORT.md`](file:///d:/MultiAgent-Software-Engineering/FINAL_PROJECT_REPORT.md) | Comprehensive academic capstone project report and findings. |
| [`SYSTEM_ARCHITECTURE.md`](file:///d:/MultiAgent-Software-Engineering/SYSTEM_ARCHITECTURE.md) | In-depth architectural design, data flows, and subsystem specifications. |
| [`METHODOLOGY.md`](file:///d:/MultiAgent-Software-Engineering/METHODOLOGY.md) | Scientific methodology, benchmark matrix design, and measurement standards. |
| [`EXPERIMENTAL_EVALUATION.md`](file:///d:/MultiAgent-Software-Engineering/EXPERIMENTAL_EVALUATION.md) | Empirical evaluation report and verified live execution telemetry. |
| [`SECURITY_AND_GUARDRAILS.md`](file:///d:/MultiAgent-Software-Engineering/SECURITY_AND_GUARDRAILS.md) | Defense-in-depth threat model, AST analysis, and HITL gatekeeper rules. |
| [`DEPLOYMENT_GUIDE.md`](file:///d:/MultiAgent-Software-Engineering/DEPLOYMENT_GUIDE.md) | Operations guide for local, Docker container, and cloud deployment. |
| [`FINAL_COMPLETION_CHECKLIST.md`](file:///d:/MultiAgent-Software-Engineering/FINAL_COMPLETION_CHECKLIST.md) | 12/12 faculty requirements compliance audit and verification evidence. |

---

## 🧪 Benchmark Matrix Campaign (Prepared & Ready)

The system includes a fully prepared, automated 45-run evaluation matrix runner (`scripts/run_benchmark_matrix.py`):
- **5 Tasks** (Feature Addition, Edge Cases, Security Defense, Type Safety, Parity Logic)
- **3 Architectures** (Hierarchical-Blackboard-A2A, Sequential-Baseline, Critic-Reflection-Loop)
- **3 Personas** (Strict-Architect, Balanced-Engineer, Permissive-Prototyper)
- **Total Matrix:** 45 distinct evaluation cells.

The matrix is validated via dry-run and ready for live execution upon API quota window reset. All executed runs are persisted into SQLite (`sandbox_workspace/experiments.db`) and queryable in Tab 5 & Tab 6 of the Mission Control Dashboard.

```powershell
# Dry run (validates the 45-run matrix without consuming API quota)
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --dry-run

# Run a specific benchmark task cell (when API quota is available)
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --task-id BENCH-01 --pattern "Hierarchical-Blackboard-A2A"
```
