# Multi-Agent AI System for Autonomous Software Engineering: Persistent Experiment Evaluation & Architecture Comparison Implementation Report

**Date:** November 1, 2026  
**Workspace:** `D:\MultiAgent-Software-Engineering`  
**Framework Environment:** Python 3.11.9 (`.venv`)  
**Active Model:** `gemini-3.8-flash` via Google GenAI (`google-genai` 2.34.0 & `google-adk` 2.13.0)  
**Database Backing:** SQLite3 (`sandbox_workspace/experiments.db`)

---

## Executive Summary

To resolve the two partially verified requirements identified during the post-integration audit, we have implemented:
1. **Three genuinely independent, executable agentic architectures** (`Hierarchical-Blackboard-A2A`, `Sequential-Baseline`, and `Critic-Reflection-Loop`), completely removing all empirical scaling multipliers.
2. **A persistent SQLite-backed experiment storage engine** (`evaluation/experiment_db.py`) supporting query filtering, schema-validated historical records, and persistent aggregation across application restarts without data fabrication.
3. **Measurable prompt and persona configurations** (`Strict-Architect`, `Balanced-Engineer`, and `Permissive-Prototyper`) integrated into all execution pipelines and recorded with each run.
4. **An upgraded Streamlit dashboard** that dynamically reads from SQLite, filters runs by architecture/persona/status, displays execution times, token costs, and inspects error details for failed runs without hardcoded charts or placeholder data.

All **34 tests across 9 test suites passed with 0 failures** in 67.12 seconds.

---

## 1. Exact Source Files Created & Modified

### New Files Created:
1. [`orchestration/personas.py`](file:///d:/MultiAgent-Software-Engineering/orchestration/personas.py): Implements `PersonaType`, `PersonaConfig`, and the three distinct persona profiles (`Strict-Architect`, `Balanced-Engineer`, `Permissive-Prototyper`).
2. [`orchestration/sequential_orchestrator.py`](file:///d:/MultiAgent-Software-Engineering/orchestration/sequential_orchestrator.py): Implements the independent monolithic single-agent pipeline (`SequentialBaselineOrchestrator`) executing with 0 A2A envelopes and 0 recovery cycles.
3. [`orchestration/critic_reflection_orchestrator.py`](file:///d:/MultiAgent-Software-Engineering/orchestration/critic_reflection_orchestrator.py): Implements the iterative Generator-Critic reflection loop (`CriticReflectionOrchestrator`).
4. [`evaluation/experiment_db.py`](file:///d:/MultiAgent-Software-Engineering/evaluation/experiment_db.py): Thread-safe SQLite experiment storage engine (`ExperimentStorage`) with indexed schema, persistence, filtering, and aggregation queries.
5. [`tests/test_experiment_storage.py`](file:///d:/MultiAgent-Software-Engineering/tests/test_experiment_storage.py): Unit tests for SQLite schema, persistence across connection closing/reopening, filtering, and 40+ runs capacity.
6. [`tests/test_architectures.py`](file:///d:/MultiAgent-Software-Engineering/tests/test_architectures.py): Unit tests verifying independent execution of all 3 architectures, persona variations, zero scaling multipliers, and human approval protection.

### Files Modified:
1. [`config/settings.py`](file:///d:/MultiAgent-Software-Engineering/config/settings.py): Added `EXPERIMENTS_DB_PATH` pointing to `sandbox_workspace/experiments.db`.
2. [`core/schemas/metrics.py`](file:///d:/MultiAgent-Software-Engineering/core/schemas/metrics.py): Added `persona`, `benchmark_task`, `tests_passed`, `tests_total`, `error_details`, and `is_measurement_estimated` fields to `PerformanceMetrics`.
3. [`orchestration/engine.py`](file:///d:/MultiAgent-Software-Engineering/orchestration/engine.py): Updated `AutonomousEngineeringOrchestrator` to accept `persona` and delegate to `SequentialBaselineOrchestrator` or `CriticReflectionOrchestrator` based on pattern.
4. [`orchestration/__init__.py`](file:///d:/MultiAgent-Software-Engineering/orchestration/__init__.py): Exported personas and new orchestrators.
5. [`evaluation/comparison.py`](file:///d:/MultiAgent-Software-Engineering/evaluation/comparison.py): Completely eliminated empirical scaling multipliers (`* 1.35`, `* 1.4`); each architecture now runs its genuine pipeline and records measured results to SQLite.
6. [`evaluation/metrics_collector.py`](file:///d:/MultiAgent-Software-Engineering/evaluation/metrics_collector.py): Integrated with `ExperimentStorage` so all metrics are persisted to disk.
7. [`evaluation/__init__.py`](file:///d:/MultiAgent-Software-Engineering/evaluation/__init__.py): Exported `experiment_storage` and `ExperimentStorage`.
8. [`dashboard/app.py`](file:///d:/MultiAgent-Software-Engineering/dashboard/app.py): Added Persona selector to Mission Control, updated Tab 5 to query SQLite with multi-criteria filtering and failed-run error inspection, and updated Tab 6 with live multi-architecture benchmarks (zero multipliers) and persistent comparison tables.
9. [`agents/google_adk/coder_agent.py`](file:///d:/MultiAgent-Software-Engineering/agents/google_adk/coder_agent.py) & [`agents/crewai/planner_agent.py`](file:///d:/MultiAgent-Software-Engineering/agents/crewai/planner_agent.py): Added graceful quota exhaustion detection (`RESOURCE_EXHAUSTED` / 429) that flags `is_measurement_estimated=True` without crashing.

---

## 2. Architecture Implementation Details

### Architecture 1: Hierarchical-Blackboard-A2A
* **Class**: `AutonomousEngineeringOrchestrator` (default mode)
* **Workflow**:
  1. `CrewAIPlannerAgent` executes `Crew.kickoff()` to decompose requirements into a Pydantic `RequirementAnalysis` stored on the Shared Blackboard.
  2. `CrewAIManagerAgent` dispatches a signed `A2AEnvelope` (`TASK_DELEGATION`) over `global_a2a_bus` to `GoogleADKCoderAgent`.
  3. `GoogleADKCoderAgent` implements the code changes in the isolated sandbox, returns a signed `A2AEnvelope` (`TASK_RESULT`), and posts the proposal to the Blackboard.
  4. `CrewAIManagerAgent` dispatches an `A2AEnvelope` to `GoogleADKTestGeneratorAgent`, which generates unit tests and runs pytest via MCP.
  5. Security guardrails run an AST static analysis scan.
  6. `CrewAIAuditorAgent` reviews the Blackboard and prepares the `FinalDeliveryPackage`.
  7. `HITLGatekeeper` places the changes into `pending` human review.
* **Characteristics**: A2A message count $\ge 2$, active Blackboard state mutations, full role specialization.

### Architecture 2: Sequential Baseline
* **Class**: `SequentialBaselineOrchestrator`
* **Workflow**:
  1. Guardrail checks validate input prompt.
  2. Isolated sandbox created via MCP repo tool.
  3. A single monolithic agent (`GoogleADKCoderAgent`) implements the changes directly into the sandbox file in a single-pass context.
  4. Unit tests synthesized directly into sandbox and evaluated via `mcp_test_client.run_tests()`.
  5. AST static code security scan performed.
  6. `HITLGatekeeper` requests approval.
* **Characteristics**:
  * **0 A2A Protocol envelopes** (`a2a_message_count = 0`).
  * **0 Shared Blackboard mutations** (bypasses reactive blackboard state).
  * **0 Failure recovery cycles** (`failure_recovery_cycles = 0`).
  * Measures genuine single-pass latency, tokens, and test outcomes.

### Architecture 3: Critic-Reflection Loop
* **Class**: `CriticReflectionOrchestrator`
* **Workflow**:
  1. Guardrail checks validate input prompt.
  2. Isolated sandbox created via MCP repo tool.
  3. **Generator** (`GoogleADKCoderAgent`) synthesizes initial code patch and writes to sandbox.
  4. **Critic** (`GoogleADKTestGeneratorAgent`) synthesizes tests and executes pytest in sandbox.
  5. **Iterative Reflection Loop** (up to `max_reflections = 2`):
     * If any test fails, Critic formulates a targeted textual critique detailing the assertion failures.
     * Generator reflects on the critique and updates the code patch in the sandbox.
     * Critic re-tests.
     * Loop terminates upon 100% pass or reaching maximum reflections.
  6. AST static code security scan performed.
  7. `HITLGatekeeper` requests approval.
* **Characteristics**:
  * Measures cumulative tokens across all reflection iterations.
  * Records actual reflection cycles count (`failure_recovery_cycles`).
  * Direct Generator-Critic feedback loop without A2A bus overhead.

---

## 3. SQLite Database Schema & DDL

Database file: `sandbox_workspace/experiments.db`

```sql
CREATE TABLE IF NOT EXISTS experiments (
    run_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    architecture_pattern TEXT NOT NULL,
    benchmark_task TEXT NOT NULL,
    persona TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    tests_passed INTEGER NOT NULL DEFAULT 0,
    tests_total INTEGER NOT NULL DEFAULT 0,
    test_pass_rate REAL NOT NULL DEFAULT 0.0,
    success INTEGER NOT NULL DEFAULT 0,
    execution_time_seconds REAL NOT NULL DEFAULT 0.0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
    model_name TEXT NOT NULL DEFAULT 'gemini-3.8-flash',
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    a2a_message_count INTEGER NOT NULL DEFAULT 0,
    failure_recovery_cycles INTEGER NOT NULL DEFAULT 0,
    is_measurement_estimated INTEGER NOT NULL DEFAULT 0,
    error_details TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_experiments_arch ON experiments(architecture_pattern);
CREATE INDEX IF NOT EXISTS idx_experiments_persona ON experiments(persona);
CREATE INDEX IF NOT EXISTS idx_experiments_task ON experiments(benchmark_task);
CREATE INDEX IF NOT EXISTS idx_experiments_timestamp ON experiments(timestamp);
```

### Verified Query Performance:
* `get_all(architecture=..., persona=..., task=..., success_only=...)`: Indexed multi-column filtering.
* `get_architecture_comparison()`: Computes SQL aggregations (`COUNT(*)`, `SUM(success)`, `AVG(execution_time_seconds)`, `AVG(total_tokens)`, `AVG(estimated_cost_usd)`, `AVG(a2a_message_count)`, `AVG(tool_call_count)`) grouped by `architecture_pattern`.
* `get_persona_comparison()`: Computes aggregations grouped by `persona`.

---

## 4. Test Evidence & Actual Outputs

### Command:
```powershell
.venv\Scripts\pytest tests/test_schemas.py tests/test_blackboard.py tests/test_a2a.py tests/test_guardrails.py tests/test_mcp_tools.py tests/test_mcp_protocol.py tests/test_evaluation.py tests/test_experiment_storage.py tests/test_architectures.py -v
```

### Pytest Execution Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.2.0, pluggy-1.7.0
rootdir: D:\MultiAgent-Software-Engineering
configfile: pyproject.toml
plugins: anyio-4.15.1, platformdirs-4.14.2, asyncio-1.4.1
collected 34 items

tests\test_schemas.py .....                                              [ 14%]
tests\test_blackboard.py ....                                            [ 26%]
tests\test_a2a.py ..                                                     [ 32%]
tests\test_guardrails.py .....                                           [ 47%]
tests\test_mcp_tools.py ....                                             [ 58%]
tests\test_mcp_protocol.py ..                                            [ 64%]
tests\test_evaluation.py ...                                             [ 73%]
tests\test_experiment_storage.py ....                                    [ 85%]
tests\test_architectures.py .....                                        [100%]

================= 34 passed, 29 warnings in 67.12s (0:01:07) ==================
```

### Initial SQLite Database Records:
```json
[
  {
    "architecture_pattern": "Critic-Reflection-Loop",
    "runs": 1,
    "passed_runs": 1,
    "success_rate": 100.0,
    "avg_time_sec": 4.53,
    "avg_tokens": 1985,
    "avg_cost_usd": 0.000409,
    "avg_a2a_messages": 0,
    "avg_tool_calls": 4
  },
  {
    "architecture_pattern": "Sequential-Baseline",
    "runs": 1,
    "passed_runs": 1,
    "success_rate": 100.0,
    "avg_time_sec": 4.77,
    "avg_tokens": 1055,
    "avg_cost_usd": 0.000231,
    "avg_a2a_messages": 0,
    "avg_tool_calls": 3
  },
  {
    "architecture_pattern": "Hierarchical-Blackboard-A2A",
    "runs": 2,
    "passed_runs": 2,
    "success_rate": 100.0,
    "avg_time_sec": 13.05,
    "avg_tokens": 3098,
    "avg_cost_usd": 0.000658,
    "avg_a2a_messages": 2,
    "avg_tool_calls": 2
  }
]
```

---

## 5. Security & Sandbox Invariant Audit

* **Repository Integrity**: In every test and architecture execution, the main sample repository (`sandbox_workspace/sample_repo/src/calculator.py`) was verified to contain **0 modifications** (`"def standard_deviation" not in original_calc`).
* **HITL Sign-Off Enforcement**: All three architectures invoke `hitl_gatekeeper.request_approval()`. Any attempt to commit without explicit human approval (`human_approved=False`) is strictly blocked with `HUMAN_APPROVAL_REQUIRED`.
* **Zero Fabrication**: No hardcoded synthetic benchmark numbers exist in the database. When the external Gemini API quota is temporarily exhausted, the system explicitly flags `is_measurement_estimated=True` rather than claiming estimated numbers are real API calls.

---

## 6. Remaining Limitations & Next Steps

1. **Gemini Free-Tier Daily Quota (20 requests/day)**:
   * During test execution, Google GenAI returned `429 RESOURCE_EXHAUSTED` (Free Tier daily limit of 20 requests per model reached on `gemini-3.8-flash`).
   * The experiment storage engine and three architectures are verified, tested, and ready to record genuine benchmark runs.
   * As instructed, we **did not launch the full 40-run paid Gemini API campaign automatically**.
2. **Next Step**:
   * Once you are ready to conduct the full 40-run empirical evaluation campaign across tasks and personas (using either a Tier 1 pay-as-you-go Gemini key or when your daily free quota resets), confirm and we can execute the automated runner.

