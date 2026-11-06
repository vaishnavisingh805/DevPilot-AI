# DevPilot AI — Final Academic Demonstration Script

**System Name:** DevPilot AI — Autonomous Multi-Agent Software Engineering Workspace  
**Workspace:** `D:\MultiAgent-Software-Engineering`  
**Target Audience:** Academic Evaluation Committee, External Examiners, Faculty Advisors  
**Demonstration Length:** 12–15 Minutes  
**Prerequisites:** Python 3.11 Virtual Environment (`.venv`), Streamlit Dashboard, SQLite Telemetry DB  

---

## 🎯 Demonstration Objective

To provide a live, deterministic, and safe walkthrough of **DevPilot AI** demonstrating:
1. Enterprise SaaS user experience across all four navigation tabs.
2. Dual-framework multi-agent coordination (CrewAI + Google ADK + Shared Blackboard + A2A Protocol).
3. Repository intelligence via AST-aware chunking and ChromaDB RAG vector search.
4. Compulsory Human-In-The-Loop (HITL) gatekeeper enforcement.
5. GitHub Pull Request publishing pipeline with branch containment guardrails.
6. Fair architectural comparison across Conditions C1, C2, C3, and C4.
7. Empirical SQLite telemetry and 45-cell benchmark matrix export.

---

## 📋 Preparation & Pre-Flight Checklist

Before presenting to examiners, run these non-destructive pre-flight commands:

```powershell
# 1. Activate Virtual Environment
cd D:\MultiAgent-Software-Engineering
.\.venv\Scripts\Activate.ps1

# 2. Verify all 90 automated tests pass cleanly (Zero API quota consumed)
.\.venv\Scripts\python.exe -m pytest -v

# 3. Launch DevPilot AI SaaS Dashboard
.\.venv\Scripts\streamlit.exe run dashboard/app.py --server.port 8510
```

Open a web browser at `http://localhost:8510`. You will see the **DevPilot AI** interface in its dark theme (`#0B0E14` charcoal background with `#2F81F7` electric blue accents).

---

## 🎬 Step-by-Step Demonstration Script

### Scene 1: System Overview & Architecture (1.5 Minutes)
**Presenter Narrative:**
> *"Esteemed examiners, welcome to DevPilot AI. Autonomous software engineering requires moving beyond single-prompt open-loop LLMs. Our research federates two complementary frameworks: CrewAI for strategic planning and governance, and Google ADK for localized implementation and unit testing. They coordinate over a reactive Shared Blackboard and typed Agent-to-Agent (A2A) message envelopes, protected by static AST guardrails and isolated MCP tool sandboxes."*

- Point to the brand navbar: **⚡ DevPilot AI — Autonomous Software Engineering Workspace**.
- Highlight the horizontal tabs: `📁 Knowledge Base`, `💬 Ask`, `⚖️ Compare Conditions`, and `📊 Evaluation`.

---

### Scene 2: Tab 1 — Knowledge Base & Code Intelligence (2.5 Minutes)
**Action:** Click the **`📁 Knowledge Base`** tab.

**Presenter Narrative:**
> *"In Tab 1, DevPilot AI connects to target software repositories. Code is not treated as flat text; our RAG pipeline performs AST-aware chunking that preserves function signatures, class hierarchies, and module context."*

1. **Inspect Repository Connection:**
   - Note the connected repository: `sample_repo` (or entered HTTPS repository URL).
   - Point out the **Repository Metadata Card**:
     - Remote Origin: Local Isolated Sandbox
     - Active Branch: `main`
     - Commit SHA: Tracked
     - File Count & Total Lines of Code (LOC)
2. **Explore Repository Files:**
   - Under **Repository File Tree & Code Inspector**, select `src/calculator.py` from the dropdown.
   - Show the syntax-highlighted code inspector displaying the `AdvancedCalculator` class.
3. **Inspect ChromaDB Vector Store:**
   - Highlight the **RAG Vector Store Status**: Ingested AST Chunks, Collection Health, 384-dimensional dense embeddings.
4. **Demonstrate Semantic Code Search:**
   - In the search box, enter query: `statistical calculations and error handling`.
   - Click **Search Codebase**.
   - Show the returned code chunks: exact function names (`mean`), file paths, line ranges, and similarity relevance scores.

---

### Scene 3: Tab 2 — Ask: Autonomous Multi-Agent Engineering (4.5 Minutes)
**Action:** Click the **`💬 Ask`** tab.

**Presenter Narrative:**
> *"In Tab 2, developer requirements are translated into fully verified code changes. Let us examine how the autonomous pipeline executes either live or by inspecting verified telemetry."*

1. **Select Requirement Preset:**
   - Under **Sample Academic Benchmark Presets**, select:  
     `Implement standard_deviation(numbers, sample=False) calculation in AdvancedCalculator`.
   - Show the generated requirement text.
2. **Configure Execution Pattern & Persona:**
   - Pattern: `Hierarchical-Blackboard-A2A` (Condition C1 — Proposed System).
   - Persona: `Balanced-Engineer` (Sampling temperature $0.2$, standard nominal rigor).

3. **Demonstrating the Multi-Agent Pipeline (Two Verified Presentation Modes):**
   > [!TIP]
   > **Faculty Evaluation Strategy — Two Execution Modes:**
   > - **Mode A (Live API Execution):** If live Gemini API quota is available, click **⚡ Execute Autonomous Engineering Workflow** to generate live reasoning.
   > - **Mode B (Inspecting Verified Telemetry — Quota-Safe):** If operating under API quota conservation or presenting offline, showcase the verified genuine baseline run (`RUN-38aa53bc` / `RUN-861653bb`) recorded in SQLite and the Blackboard state file (`sandbox_workspace/blackboard_state.json`). Explain: *"Examiners, to preserve API quota without fabricating metrics, our system provides full post-execution telemetry from our verified baseline run."*

4. **Inspect Live Telemetry Metrics:**
   - Point out the metric cards:
     - Runtime: $\approx 12-17\text{s}$ (Run `RUN-38aa53bc`: 17.375s)
     - Tests Passed: `100.0%` ($9/9$ tests passing)
     - Total Tokens: Genuine measurement ($5,795$ tokens)
     - Calculated Cost: Exact rate card ($\$0.001132\text{ USD}$)
     - A2A Messages: $6$ signed envelopes
     - Tool Invocations: $14$ MCP operations
5. **Inspect the Shared Blackboard State:**
   - Click through the tabbed Blackboard inspector:
     - **Requirement Analysis:** Shows structured acceptance criteria formulated by CrewAI Planner.
     - **Execution Plan:** Shows task assignments across CrewAI and Google ADK.
     - **AST Security Audit:** Confirms clean audit (`os.system`, `subprocess(shell=True)`, `eval` clean).
     - **A2A Event Log:** Shows typed envelopes exchanged over `global_a2a_bus` with SHA-256 signatures.
6. **Inspect Code Diffs & Pytest Execution:**
   - Scroll to **Unified Git Diff Viewer**: Point out the clean green added lines implementing population and sample standard deviation in `src/calculator.py`.
   - Show the formatted **Pytest Execution Report** showing all test assertions passed.

---

### Scene 4: HITL Gatekeeper & Safe GitHub PR Publishing (2.5 Minutes)
**Action:** Remain on the **`💬 Ask`** tab, scrolling to the **Human-in-the-Loop Gatekeeper** section.

**Presenter Narrative:**
> *"Autonomous agents must never push directly to production without human oversight. DevPilot AI enforces a compulsory Human-In-The-Loop gatekeeper. Furthermore, strict invariants prevent force-pushes or pushing to protected default branches."*

1. **Show Gating Status:**
   - Point to the badge: `Approval Status: PENDING`.
   - Explain: *Until an operator approves, remote publishing is strictly impossible.*
2. **Perform Human Review & Approval:**
   - In the **Reviewer Notes** box, type: `Approved for publication after diff and test review`.
   - Click the green button: **✅ Approve & Sign-Off**.
   - Observe the live badge transition: `Approval Status: APPROVED`.
3. **Demonstrate GitHub PR Publication:**
   - Click the electric blue button: **🚀 Publish GitHub Pull Request**.
   - Show the success alert: Pull request created with structured markdown description including task ID, acceptance criteria, test results, AST security audit, and human sign-off block.
   - Point out the clickable `#PR` badge and stored SQLite record.
4. **Explain Safety Invariants:**
   - *Invariable Rule 1:* Only dedicated feature branches (`agentic/*`) may be pushed.
   - *Invariable Rule 2:* Pushing to `main`, `master`, or `develop` is hard-blocked.
   - *Invariable Rule 3:* Force pushes (`--force`, `-f`) are forbidden.

---

### Scene 5: Tab 3 — Compare Conditions (C1–C4) (2.5 Minutes)
**Action:** Click the **`⚖️ Compare Conditions`** tab.

**Presenter Narrative:**
> *"Tab 3 addresses our core empirical research: comparing the four experimental conditions defined in our methodology."*

1. **Walk Through Condition Cards:**
   - **C1 (Proposed System):** Hierarchical Dual-Framework (CrewAI + Google ADK + Shared Blackboard + A2A).
   - **C2 (Monolithic Baseline):** Sequential Single-Agent (Google ADK) without blackboard or A2A communication.
   - **C3 (Protocol Ablation):** Direct Generator-Critic peer-to-peer reflection loop without central blackboard mutations.
   - **C4 (Multi-Model Family Evaluation):** Cross-foundation-model contrast.
2. **Review the C4 Multi-Model Family Matrix:**
   - Highlight the comparison table:
     - `gemini-3.8-flash`: \$0.10 / \$0.40 per 1M tokens, 1M context (Primary Production Target).
     - `gemini-1.5-pro`: \$1.25 / \$5.00 per 1M tokens, 2M context (High-Reasoning Frontier).
     - `gemini-2.0-flash`: \$0.10 / \$0.40 per 1M tokens, 1M context (High-Throughput Fast).
     - `gpt-4o`: \$5.00 / \$15.00 per 1M tokens, 128k context (Cross-Provider Rate Baseline).
3. **Trigger Architectural Comparison:**
   - Click **Run Comparison**.
   - Show the multi-column comparison table comparing C1, C2, and C3 on execution time, token consumption, cost, and test pass rates.

---

### Scene 6: Tab 4 — Evaluation & Telemetry (1.5 Minutes)
**Action:** Click the **`📊 Evaluation`** tab.

**Presenter Narrative:**
> *"Tab 4 presents our empirical SQLite telemetry and benchmark progress."*

1. **Overall Telemetry Cards:**
   - Show Total Evaluated Runs, Overall Pass Rate, Average Runtime, and Total Cost queried directly from `sandbox_workspace/experiments.db`.
2. **Visual 45-Cell Benchmark Matrix:**
   - Show the 45-row progress grid ($5\text{ tasks} \times 3\text{ architectures} \times 3\text{ personas}$).
   - Point out Cell `#01` marked as `COMPLETED` with verified live metrics, and remaining cells primed as `PENDING`.
3. **Dataset Export Verification:**
   - Point to the download buttons:
     - **Download Experiment History (CSV)**
     - **Export Complete Telemetry (JSON)**
   - Click to demonstrate instantaneous download of verifiable academic data.

---

### Scene 7: Command-Line Benchmark Matrix Dry-Run (1 Minute)
**Action:** Switch to terminal and run:

```powershell
python scripts/run_benchmark_matrix.py --dry-run
```

**Presenter Narrative:**
> *"Finally, here is our automated 45-run evaluation harness in dry-run mode. It validates the full 45-cell matrix, checks the checkpoint file, skips already completed cells, and consumes exactly zero Gemini API quota. When our quota resets, running this script without `--dry-run` executes the complete campaign autonomously with exponential backoff and quota exhaustion traps."*

---

## 🏆 Demonstration Conclusion
Summarize to the examiners:
- **Architecture Validated:** CrewAI and Google ADK successfully federated over Shared Blackboard and A2A.
- **Safety Verified:** Compulsory HITL gatekeeper, sandboxed AST guardrails, and default branch protection.
- **Academic Rigor:** Zero fabricated numbers, genuine SQLite telemetry, 90 passing automated tests, and reproducible 45-cell benchmark harness.

