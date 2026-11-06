# Benchmark Execution Guide: 45-Run Experimental Campaign

**Project:** Multi-Agent AI System for Autonomous Software Engineering  
**Workspace:** `D:\MultiAgent-Software-Engineering`  
**Target:** 45 Controlled Experimental Cells (5 Tasks × 3 Architecture Patterns × 3 Personas)  
**Execution Script:** `scripts/run_benchmark_matrix.py`

---

## 1. Overview and Architecture

The benchmark harness tests 45 systematically controlled configurations:
- **5 Canonical Benchmark Tasks:**
  - `BENCH-01`: Standard Deviation calculation in `AdvancedCalculator`
  - `BENCH-02`: LRU Cache implementation with TTL expiry
  - `BENCH-03`: Vector dot product and cosine similarity
  - `BENCH-04`: Safe JSON configuration parser with fallback defaults
  - `BENCH-05`: Asynchronous retry utility with exponential backoff and jitter
- **3 Architecture Patterns:**
  - `Hierarchical-Blackboard-A2A`: Full 6-agent hierarchy, A2A bus, Shared Blackboard, MCP tools
  - `Sequential Baseline`: Linear Planner → Coder → Test-Runner pipeline without feedback loops
  - `Critic-Reflection Loop`: Iterative Coder ↔ Critic reflection loop (up to 3 revisions)
- **3 Personas:**
  - `Balanced-Engineer`: Balanced temperature (0.2), standard prompt
  - `Aggressive-Optimizer`: Low temperature (0.1), performance-focused prompt
  - `Cautious-Tester`: Low temperature (0.1), boundary/edge-case focused prompt

All runs record real LLM calls (via Google Gemini `gemini-2.5-flash`), actual token usage, MCP tool interactions, test outcomes, and execution latency into persistent SQLite storage (`sandbox_workspace/experiments.db`).

---

## 2. Safety Features & Resiliency Architecture

The benchmark runner is engineered with safety protocols to prevent API exhaustion, data loss, or unmonitored costs:

1. **Deterministic Checkpointing:**  
   After every cell completion, state is saved to `sandbox_workspace/benchmark_checkpoint.json` and committed to SQLite (`sandbox_workspace/experiments.db`).
2. **Automatic Resume:**  
   When restarted, the runner checks both the checkpoint file and existing SQLite records. Completed cells are automatically skipped (`[COMPLETED - SKIP]`).
3. **HTTP 429 Quota Exhaustion Guard:**  
   If Gemini returns HTTP 429 (`RESOURCE_EXHAUSTED` or rate limit quota exceeded), execution **pauses gracefully**, saves state, and halts without crashing or marking the cell as failed.
4. **Transient Error Retries:**  
   Network timeouts or transient HTTP 503 errors undergo exponential backoff (up to 3 retries: 5s, 10s, 20s). Quota errors are never retried.
5. **No Fabricated Data:**  
   Every metric reflects genuine system execution. Dry runs display planned execution without touching the Gemini API or creating fake records.
6. **Isolated Sandbox Execution:**  
   All code generation and test execution take place inside `sandbox_workspace/` without affecting the host repository.

---

## 3. CLI Command Reference

All commands must be executed using the project's virtual environment:

### A. Pre-Flight Inspection (Dry Run — 0 API Calls)
Inspect the full 45-run matrix, identify completed vs. pending cells, and verify configuration without consuming Gemini quota:

```powershell
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --dry-run
```

To preview what a complete clean run would look like (ignoring existing checkpoints in dry-run mode):
```powershell
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --dry-run --force-rerun
```

### B. Standard Live Execution (Auto-Resume Enabled)
Run all pending cells in sequence. Already completed cells are skipped automatically:

```powershell
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py
```

### C. Targeted Subsets & Controlled Batches
To execute specific slices or limit the number of runs per session:

```powershell
# Run only a single task across all patterns and personas (9 runs)
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --task-id BENCH-01

# Run only a specific architecture pattern (15 runs)
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --pattern Hierarchical-Blackboard-A2A

# Run only a specific persona (15 runs)
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --persona Balanced-Engineer

# Run a maximum of 3 cells in this session (e.g. for quota management)
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --runs-limit 3

# Combine filters: Run 1 cell of BENCH-02 with Critic-Reflection and Cautious-Tester
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --task-id BENCH-02 --pattern "Critic-Reflection Loop" --persona Cautious-Tester
```

### D. Exporting Benchmark Results
Export all recorded benchmark runs from SQLite to CSV and JSON:

```powershell
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --export-only
```
- CSV Output: `sandbox_workspace/benchmark_results.csv`
- JSON Output: `sandbox_workspace/benchmark_results.json`

### E. Advanced Flags

| Flag | Description |
|---|---|
| `--dry-run` | Display matrix plan and status without making API calls |
| `--runs-limit N` | Stop execution after completing `N` cells |
| `--task-id ID` | Filter matrix to run only `BENCH-01` through `BENCH-05` |
| `--pattern NAME` | Filter matrix by pattern (`Hierarchical-Blackboard-A2A`, `Sequential Baseline`, `Critic-Reflection Loop`) |
| `--persona NAME` | Filter matrix by persona (`Balanced-Engineer`, `Aggressive-Optimizer`, `Cautious-Tester`) |
| `--force-rerun` | Rerun cells even if already recorded as completed |
| `--retry-failed` | Specifically rerun cells previously logged with `FAILED` status |
| `--export-only` | Export SQLite records to CSV/JSON and exit |
| `--export-csv PATH` | Custom destination path for CSV export |
| `--export-json PATH` | Custom destination path for JSON export |
| `--db PATH` | Custom SQLite database file path (default: `sandbox_workspace/experiments.db`) |

---

## 4. Operational Workflow: Start, Pause, Resume

### Starting the Campaign
1. Verify Gemini API key is configured in `.env`:
   ```powershell
   Get-Content .env | Select-String "GEMINI_API_KEY"
   ```
2. Verify pre-flight matrix status:
   ```powershell
   .\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py --dry-run
   ```
3. Begin execution:
   ```powershell
   .\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py
   ```

### Pausing the Campaign
- **Manual Pause:** Press `Ctrl+C` in the terminal at any time. The current cell will exit cleanly, and all previous completed cells remain safely committed to SQLite and checkpointed.
- **Automatic Quota Pause:** If HTTP 429 occurs, the runner logs the error, saves checkpoint metadata, and terminates with code 0 to protect API integrity.

### Resuming the Campaign
Simply reissue the run command:
```powershell
.\.venv\Scripts\python.exe scripts/run_benchmark_matrix.py
```
The runner reads `sandbox_workspace/benchmark_checkpoint.json` and SQLite, prints `[COMPLETED - SKIP]` for finished cells, and immediately resumes from the first pending cell.

---

## 5. Verification & Monitoring

### Dashboard Monitoring (Streamlit)
Launch the interactive monitoring dashboard:
```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard/app.py
```
1. **Tab 5: Architecture Comparison:**  
   View side-by-side metric charts comparing Hierarchical, Sequential, and Critic patterns across Token Usage, Latency, and Test Pass Rates.
2. **Tab 6: Benchmark Matrix & Empirical Results:**  
   View real-time 5×3×3 matrix completion grid, empirical statistical summaries, and export capabilities.

### SQLite Database Verification
Verify recorded runs directly via Python:
```powershell
.\.venv\Scripts\python.exe -c "from evaluation.experiment_db import ExperimentStorage; s = ExperimentStorage(); runs = s.get_all(); print(f'Total recorded runs: {len(runs)}')"
```

