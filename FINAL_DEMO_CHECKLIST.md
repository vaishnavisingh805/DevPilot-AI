# DevPilot AI — Final Academic Demonstration Checklist

**System Name:** DevPilot AI — Autonomous Multi-Agent Software Engineering Workspace  
**Workspace:** `D:\MultiAgent-Software-Engineering`  
**Purpose:** Pre-Flight Verification and Live Evaluation Execution Checklist  

---

## 📋 1. Pre-Flight Verification (T-Minus 15 Minutes)

Complete each item in the terminal before admitting examiners or starting the presentation:

- [ ] **1. Python Environment Check:**
  ```powershell
  python --version
  # Must output: Python 3.11.9
  ```

- [ ] **2. Virtual Environment Activation:**
  ```powershell
  cd D:\MultiAgent-Software-Engineering
  .\.venv\Scripts\Activate.ps1
  ```

- [ ] **3. Offline Regression Suite Verification:**
  ```powershell
  .\.venv\Scripts\python.exe -m pytest -v
  # Must output: 90 passed, 0 failed
  ```

- [ ] **4. SQLite Database Check:**
  ```powershell
  .\.venv\Scripts\python.exe -c "from evaluation.experiment_db import experiment_storage; print('Database runs:', experiment_storage.count())"
  # Must report at least 3 genuine runs
  ```

- [ ] **5. Launch SaaS Dashboard:**
  ```powershell
  .\.venv\Scripts\streamlit.exe run dashboard/app.py --server.port 8510
  ```
  Open browser at `http://localhost:8510` and verify the dark theme loads cleanly.

---

## 🎬 2. The 10-Point Core Demonstration Walkthrough

During the evaluation, tick each point as you present it to the examiners:

- [ ] **Point 1: DevPilot AI Dashboard & 4 Horizontal Navigation Tabs**
  - Show the dark enterprise theme (`#0B0E14`), Inter typography, and live status pill.
  - Point out the 4 tabs: `📁 Knowledge Base`, `💬 Ask`, `⚖️ Compare Conditions`, `📊 Evaluation`.

- [ ] **Point 2: Repository Connection & Knowledge Base**
  - Switch to `📁 Knowledge Base`.
  - Point out the active repository (`sample_repo`), active branch (`main`), commit SHA, file count, and LOC.
  - Use the file inspector dropdown to view `src/calculator.py` with syntax highlighting.

- [ ] **Point 3: RAG-Based Code Retrieval with Source Line References**
  - Show the ChromaDB vector store metrics (ingested chunks, 384-dim dense embeddings).
  - In Semantic Search, enter query: `statistical calculations and error handling`.
  - Click **Search Codebase** and show the retrieved chunks with file paths, start/end lines, and relevance scores.

- [ ] **Point 4: Natural-Language Developer Requirement Input**
  - Switch to `💬 Ask`.
  - Select preset: `Implement standard_deviation(numbers, sample=False) calculation in AdvancedCalculator`.
  - Configure Pattern: `Hierarchical-Blackboard-A2A` (C1).
  - Configure Persona: `Balanced-Engineer` ($T=0.2$).

- [ ] **Point 5: Multi-Agent Orchestration & A2A Envelopes**
  - **Mode Selection:**
    - *If live quota available:* Click **⚡ Execute Autonomous Engineering Workflow**.
    - *If preserving quota:* Showcase the verified baseline run (`RUN-38aa53bc` / `RUN-861653bb`) recorded in SQLite and Blackboard.
  - Show the A2A Event Log: Explain the SHA-256 digital signature, sender/recipient framework, and message types (`TASK_DELEGATION`, `TASK_RESULT`).

- [ ] **Point 6: Blackboard State Version Transitions**
  - In the Blackboard inspector, walk through monotonic state transitions:
    - Requirement posted ($v_1$)
    - Analysis & Acceptance Criteria ($v_2$)
    - Code Patch synthesized ($v_3$)
    - Pytest Report validated ($v_4$)
    - Security Audit cleared ($v_5$)
  - Explain deep-copy state protection (`model_copy(deep=True)`).

- [ ] **Point 7: Code Generation & Unified Diff**
  - Scroll to the **Unified Git Diff Viewer**.
  - Show the clean additions implementing population (`sample=False`) and sample (`sample=True`) standard deviation.
  - Highlight that modifications occurred strictly in the isolated sandbox clone.

- [ ] **Point 8: Testing & AST Security Validation**
  - Show the **Pytest Execution Report**: 100% pass rate ($9/9$ assertions passing).
  - Show the **AST Security Audit**: Confirms 0 forbidden syscalls (`os.system`, `subprocess(shell=True)`, `eval`, `exec`).

- [ ] **Point 9: Human-In-The-Loop (HITL) Gatekeeper Sign-Off**
  - Show the initial status: `Approval Status: PENDING`.
  - Explain: *Pushing to remote or committing is strictly blocked.*
  - Enter reviewer notes: `Approved by Academic Reviewer after test and diff review`.
  - Click **✅ Approve & Sign-Off** and observe status change to `APPROVED`.

- [ ] **Point 10: Delivery Package & GitHub PR Workflow Explanation**
  - Click **🚀 Publish GitHub Pull Request**.
  - Show the generated PR alert with clickable `#PR` link.
  - Explain the strict invariants:
    1. Only `agentic/*` branches may be pushed.
    2. Pushes to `main`, `master`, `develop` are hard-blocked.
    3. Zero force-push (`--force` forbidden).
    4. Empty diffs rejected.

---

## ⚖️ 3. Comparative Conditions & Benchmark Walkthrough

- [ ] **Condition Comparison (Tab 3):**
  - Review C1 (Proposed Dual-Framework), C2 (Monolithic Baseline), C3 (Critic-Reflection Ablation), C4 (Multi-Model Family).
  - Walk through the C4 Multi-Model Family Matrix (`gemini-3.8-flash`, `gemini-1.5-pro`, `gemini-2.0-flash`, `gpt-4o`).
  - Click **Run Comparison** to show side-by-side execution time, tokens, cost, and pass rates.

- [ ] **Evaluation & Telemetry (Tab 4):**
  - Review the summary telemetry cards (Total Runs, Pass Rate, Runtime, Total Cost) queried from SQLite.
  - Review the 45-Cell Matrix progress grid ($5\text{ tasks} \times 3\text{ architectures} \times 3\text{ personas}$).
  - Demonstrate single-click downloads of **CSV** and **JSON** telemetry exports.

- [ ] **Terminal Dry-Run Demonstration:**
  - In a terminal, run:
    ```powershell
    python scripts/run_benchmark_matrix.py --dry-run
    ```
  - Show the 45-cell plan, checkpoint validation, and confirm **zero API quota consumed**.

---

## 🛡️ 4. Handling Examiner Trap Questions

| Examiner Trap Question | Recommended Answer |
| :--- | :--- |
| *"Did you run all 45 cells live?"* | *"No, cell #01 (RUN-861653bb) was verified live with real Gemini tokens, while the remaining 44 cells are primed and checkpointed in our automated harness to respect the daily Free Tier quota. We do not fabricate results."* |
| *"Why not just use LangGraph or AutoGen?"* | *"Project and faculty rules specifically required CrewAI and Google ADK. Furthermore, federating CrewAI for management and Google ADK for technical coding gave us clean role specialization without vendor lock-in."* |
| *"Can the agent push malicious code to GitHub?"* | *"No. The code is quarantined in a sandbox, scanned via static AST analysis for forbidden syscalls, and strictly blocked from pushing until a human explicitly reviews the diff and approves it."* |
| *"Is gpt-4o running live in Google ADK?"* | *"No. gpt-4o is included in our C4 rate-card comparison matrix as an analytical baseline. Google ADK natively executes Google GenAI Gemini models."* |

---

## ✅ 5. Final Readiness Sign-Off

- [x] All 90 unit and integration tests passing.
- [x] Zero regressions introduced.
- [x] Streamlit dashboard verified on port 8510 with HTTP 200 health.
- [x] All four deliverables created and verified.
- [x] **READY FOR FINAL EVALUATION & VIVA VOCE.**

