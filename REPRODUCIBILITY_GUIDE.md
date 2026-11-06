# DevPilot AI — Independent Research Reproducibility Guide

**System Name:** DevPilot AI — Autonomous Multi-Agent Software Engineering Workspace  
**Workspace:** `D:\MultiAgent-Software-Engineering`  
**Target Environment:** Python 3.11.9 (64-bit) on Windows 10/11 or Linux  
**Repository Version:** 1.0.0 (Phase 2.5)  

---

## 1. System Requirements & Environment Setup

### 1.1 Python Version
DevPilot AI requires **Python 3.11.9**. Both CrewAI and Google ADK have strict compatibility requirements centered on Python 3.11.

```powershell
# Verify Python version
python --version
# Expected: Python 3.11.9
```

### 1.2 Virtual Environment Creation & Dependency Installation
Create an isolated virtual environment and install pinned dependencies:

```powershell
# Clone or navigate to the repository root
cd D:\MultiAgent-Software-Engineering

# Create a clean virtual environment
python -m venv .venv

# Activate the virtual environment
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On Linux / macOS:
# source .venv/bin/activate

# Upgrade packaging tools
python -m pip install --upgrade pip setuptools wheel

# Install core framework dependencies
pip install -r requirements.txt
```

### 1.3 Key Installed Framework Versions
- `google-genai`: 2.34.0
- `google-adk`: 2.13.0
- `crewai`: 0.102.0
- `chromadb`: 0.6.3
- `pydantic`: 2.10.6
- `pytest`: 9.2.0
- `streamlit`: 1.42.0

---

## 2. Environment Variables & Credentials Configuration

Configure runtime environment variables using a local `.env` file in the project root.

> [!CAUTION]
> **Credential Safety Rule:** Never commit the `.env` file to version control. An sanitized template is provided as `.env.example`.

### Required & Optional Variable Names:
| Variable Name | Required? | Purpose | Default / Fallback |
| :--- | :---: | :--- | :--- |
| `GEMINI_API_KEY` | **Yes** (for live runs) | Google Gemini API authorization key for CrewAI and Google ADK | `""` (Falls back to deterministic offline synthesis during unit tests) |
| `GITHUB_TOKEN` | Optional | GitHub Personal Access Token (`repo` scope) for Pull Request publishing | `""` (PR publishing will operate in local sandboxed dry-run mode) |
| `OPENAI_API_KEY` | Optional | Reserved for future OpenAI cross-model testing | `""` |
| `EXECUTION_MODE` | Optional | Controls execution profile (`live` or `deterministic_simulation`) | `live` |
| `DEFAULT_MODEL` | Optional | Active foundation LLM identifier | `gemini-3.8-flash` |
| `REQUIRE_HUMAN_APPROVAL` | Optional | Compulsory Human-in-the-Loop review toggle | `true` |

---

## 3. Database Initialization & Schema

All experimental telemetry and published pull request records persist to a local SQLite database located at:
`sandbox_workspace/experiments.db`

### 3.1 Automatic Table Creation
The database and tables initialize automatically on first import of `evaluation.experiment_db`.

```python
from evaluation.experiment_db import experiment_storage

# Verifies or creates tables automatically
count = experiment_storage.count()
print(f"Total experiments in database: {count}")
```

### 3.2 Schema Architecture
```sql
-- Main Experiments Telemetry Table
CREATE TABLE IF NOT EXISTS experiments (
    run_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    architecture_pattern TEXT NOT NULL,
    benchmark_task TEXT NOT NULL,
    persona TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    tests_passed INTEGER NOT NULL,
    tests_total INTEGER NOT NULL,
    test_pass_rate REAL NOT NULL,
    success INTEGER NOT NULL,
    execution_time_seconds REAL NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    estimated_cost_usd REAL NOT NULL,
    model_name TEXT NOT NULL,
    tool_call_count INTEGER NOT NULL,
    a2a_message_count INTEGER NOT NULL,
    failure_recovery_cycles INTEGER NOT NULL,
    is_measurement_estimated INTEGER NOT NULL DEFAULT 0,
    error_details TEXT,
    metadata_json TEXT
);

-- Published Pull Requests Table
CREATE TABLE IF NOT EXISTS pull_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    pr_url TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    base_branch TEXT NOT NULL,
    head_branch TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY (run_id) REFERENCES experiments(run_id)
);
```

---

## 4. Safe Local Execution & Sandbox Boundaries

All repository modifications are strictly quarantined:
1. **Sandbox Root:** `sandbox_workspace/runs/<run_id>/`
2. **Ephemeral Clones:** Every execution clones the target repository into a uniquely named run directory.
3. **Dedicated Branches:** Only branches prefixed with `agentic/` (e.g., `agentic/{task_id}-{run_id}`) are created.
4. **Path Traversal Shield:** Sandboxed operations pass through `_resolve_sandbox_path()`. Invocations attempting directory escapes (`../../`) trigger immediate `PermissionError`.

---

## 5. Running Automated Verification Tests

Verify the entire multi-agent system offline without consuming API quota:

```powershell
# Run the complete test suite (90 tests across 17 test modules)
pytest -v

# Run only GitHub Pull Request & Push Guardrail tests
pytest tests/test_github_pr.py -v

# Run only SaaS Dashboard and Comparison tests
pytest tests/test_dashboard.py -v

# Run only Architecture Pattern tests (C1, C2, C3)
pytest tests/test_architectures.py -v
```

---

## 6. Launching the SaaS Dashboard

To start the interactive DevPilot AI workspace:

```powershell
# Launch Streamlit dashboard on local port 8510
streamlit run dashboard/app.py --server.port 8510
```

Access the interface in any standard browser at:
`http://localhost:8510`

---

## 7. Reproducing the 45-Cell Academic Benchmark Campaign

The benchmark campaign is orchestrated via [`scripts/run_benchmark_matrix.py`](file:///d:/MultiAgent-Software-Engineering/scripts/run_benchmark_matrix.py).

### 7.1 Dry-Run Validation (Zero API Calls)
Validates the full matrix, inspects checkpoint state, and verifies database readiness without invoking LLMs:

```powershell
python scripts/run_benchmark_matrix.py --dry-run
```

### 7.2 Executing a Targeted Single-Cell Test
To reproduce a single benchmark experiment without running the entire campaign:

```powershell
# Example: Run BENCH-01 under Hierarchical pattern with Balanced-Engineer persona
python scripts/run_benchmark_matrix.py --task-id BENCH-01 --pattern Hierarchical-Blackboard-A2A --persona Balanced-Engineer --runs-limit 1
```

### 7.3 Executing or Resuming the Full 45-Run Campaign
To execute the campaign with automatic checkpointing and resume support:

```powershell
# Resumes from last checkpoint automatically
python scripts/run_benchmark_matrix.py
```

### 7.4 Force Re-Running Completed Cells
To bypass the checkpoint file and force a fresh execution of all cells:

```powershell
python scripts/run_benchmark_matrix.py --force-rerun
```

---

## 8. Telemetry Data Exports

Benchmark results can be exported at any time directly from SQLite:

```powershell
# Export database records to CSV and JSON without running experiments
python scripts/run_benchmark_matrix.py --export-only
```

Exported files are saved to:
- CSV: `sandbox_workspace/benchmark_results.csv`
- JSON: `sandbox_workspace/benchmark_results.json`

