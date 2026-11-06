"""Regression Tests for Repository-Specific File Resolution and Dynamic Target Selection.

Ensures that DevPilot AI operates across diverse codebase architectures (React/TypeScript,
alternative Python layouts, polyglot repos) without hardcoded calculator-specific assumptions.
"""

import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch
import pytest
from pathlib import Path

from config.settings import settings
from core.schemas import (
    DeveloperRequirement,
    RepositoryConfig,
    ChangeType,
)
from orchestration import AgenticPatternType, PersonaType
from core.blackboard import global_blackboard
from core.guardrails.ast_safety import ast_guardrail
from core.rag.ast_chunker import ASTCodeChunker
from core.rag.vector_store import vector_store
from mcp_servers.repo_tool.client import mcp_repo_client
from mcp_servers.test_runner.client import mcp_test_client
from agents.crewai.planner_agent import CrewAIPlannerAgent
from agents.google_adk.coder_agent import GoogleADKCoderAgent
from agents.google_adk.test_generator_agent import GoogleADKTestGeneratorAgent
from orchestration.engine import AutonomousEngineeringOrchestrator


@pytest.fixture
def react_sandbox():
    """Creates a temporary React + TypeScript sandbox directory without any Python files."""
    run_id = f"test_react_{os.urandom(4).hex()}"
    sb_dir = settings.SANDBOX_ROOT / "runs" / run_id
    sb_dir.mkdir(parents=True, exist_ok=True)

    # Populate typical React + TypeScript structure
    (sb_dir / "src" / "components").mkdir(parents=True, exist_ok=True)
    (sb_dir / "src" / "pages").mkdir(parents=True, exist_ok=True)

    (sb_dir / "package.json").write_text(
        '{"name": "it-support-portal", "version": "1.0.0", "dependencies": {"react": "^18.0.0"}}',
        encoding="utf-8",
    )
    (sb_dir / "tsconfig.json").write_text(
        '{"compilerOptions": {"target": "ESNext", "jsx": "react-jsx"}}',
        encoding="utf-8",
    )
    (sb_dir / "src" / "App.tsx").write_text(
        'import React from "react";\nexport function App() { return <div>Support Portal</div>; }\n',
        encoding="utf-8",
    )
    (sb_dir / "src" / "components" / "TicketCard.tsx").write_text(
        'import React from "react";\nexport interface Ticket { id: string; title: string; }\n'
        'export function TicketCard({ ticket }: { ticket: Ticket }) { return <div className="card">{ticket.title}</div>; }\n',
        encoding="utf-8",
    )
    (sb_dir / "src" / "pages" / "DashboardPage.tsx").write_text(
        'import React from "react";\nimport { TicketCard } from "../components/TicketCard";\n'
        'export function DashboardPage() { return <div><h1>Dashboard</h1></div>; }\n',
        encoding="utf-8",
    )

    yield run_id, sb_dir

    # Cleanup
    if sb_dir.exists():
        shutil.rmtree(sb_dir, ignore_errors=True)


@pytest.fixture
def alt_python_sandbox():
    """Creates a temporary Python sandbox with non-calculator structure."""
    run_id = f"test_alt_py_{os.urandom(4).hex()}"
    sb_dir = settings.SANDBOX_ROOT / "runs" / run_id
    sb_dir.mkdir(parents=True, exist_ok=True)

    (sb_dir / "service").mkdir(parents=True, exist_ok=True)
    (sb_dir / "service" / "api.py").write_text(
        '"""Core Service API."""\n\ndef get_health_status() -> dict:\n    return {"status": "ok"}\n',
        encoding="utf-8",
    )
    (sb_dir / "service" / "models.py").write_text(
        '"""Data models."""\nfrom pydantic import BaseModel\n\nclass Health(BaseModel):\n    status: str\n',
        encoding="utf-8",
    )

    yield run_id, sb_dir

    if sb_dir.exists():
        shutil.rmtree(sb_dir, ignore_errors=True)


def test_react_repository_file_resolution(react_sandbox):
    """Test 1: Target file resolution in a React + TypeScript project with no calculator.py."""
    run_id, sb_dir = react_sandbox

    # Verify calculator.py is completely absent
    assert not (sb_dir / "src" / "calculator.py").exists()

    # Dynamic target resolution for TicketCard
    target_file, is_new = AutonomousEngineeringOrchestrator._resolve_target_file(
        sandbox_dir=sb_dir,
        raw_prompt="Add priority badge styling to TicketCard component in src/components/TicketCard.tsx",
    )
    assert target_file == "src/components/TicketCard.tsx"
    assert is_new is False

    # Dynamic target resolution for DashboardPage
    target_file2, _ = AutonomousEngineeringOrchestrator._resolve_target_file(
        sandbox_dir=sb_dir,
        raw_prompt="Implement ticket metrics counter in DashboardPage",
    )
    assert target_file2 == "src/pages/DashboardPage.tsx"

    # Verify Coder Agent patches the TypeScript file without injecting Python code
    coder = GoogleADKCoderAgent()
    mock_event = MagicMock()
    mock_part = MagicMock()
    mock_part.text = (
        '```tsx\nimport React from "react";\nexport interface Ticket { id: string; title: string; }\n'
        'export function TicketCard({ ticket }: { ticket: Ticket }) { return <div className="card badge-priority">{ticket.title}</div>; }\n```\n'
    )
    mock_event.content.parts = [mock_part]
    mock_event.usage_metadata = None

    with patch.object(coder.runner, "run", return_value=[mock_event]):
        proposal = coder.implement_changes(
            run_id=run_id,
            task_id="TSK-REACT-01",
            instruction="Add priority badge styling to TicketCard",
            context={"target_file": target_file, "sandbox_path": str(sb_dir)},
        )
    assert proposal is not None
    assert len(proposal.patches) == 1
    c_patch = proposal.patches[0]
    assert c_patch.file_path == "src/components/TicketCard.tsx"
    assert "def standard_deviation" not in c_patch.modified_content
    assert "import math" not in c_patch.modified_content

    # Verify AST Guardrail passes on TypeScript code
    passed, violations = ast_guardrail.scan_code(c_patch.modified_content, file_path="src/components/TicketCard.tsx")
    assert passed is True
    assert len(violations) == 0


def test_alternative_python_structure_resolution(alt_python_sandbox):
    """Test 2: Dynamic file resolution in Python repositories with alternative directory structures."""
    run_id, sb_dir = alt_python_sandbox

    assert not (sb_dir / "src" / "calculator.py").exists()

    target_file, is_new = AutonomousEngineeringOrchestrator._resolve_target_file(
        sandbox_dir=sb_dir,
        raw_prompt="Add database connection ping to service/api.py",
    )
    assert target_file == "service/api.py"
    assert is_new is False

    coder = GoogleADKCoderAgent()
    mock_event_py = MagicMock()
    mock_part_py = MagicMock()
    mock_part_py.text = (
        '```python\n"""Core Service API."""\n\ndef get_health_status() -> dict:\n    return {"status": "ok", "ping": "pong"}\n```\n'
    )
    mock_event_py.content.parts = [mock_part_py]
    mock_event_py.usage_metadata = None

    with patch.object(coder.runner, "run", return_value=[mock_event_py]):
        proposal = coder.implement_changes(
            run_id=run_id,
            task_id="TSK-ALT-PY",
            instruction="Add ping endpoint to service/api.py",
            context={"target_file": target_file, "sandbox_path": str(sb_dir)},
        )
    assert proposal.patches[0].file_path == "service/api.py"
    assert "def standard_deviation" not in proposal.patches[0].modified_content


def test_missing_target_file_raises_structured_error():
    """Test 3: Missing or non-existent files raise structured errors without calculator fallback."""
    empty_run_id = f"test_empty_{os.urandom(4).hex()}"
    empty_dir = settings.SANDBOX_ROOT / "runs" / empty_run_id
    empty_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Attempt resolution in empty directory
        with pytest.raises(RuntimeError) as exc_info:
            AutonomousEngineeringOrchestrator._resolve_target_file(
                sandbox_dir=empty_dir,
                raw_prompt="Implement some feature",
            )
        assert "No qualifying source files found" in str(exc_info.value)
        assert "calculator.py" not in str(exc_info.value)
    finally:
        shutil.rmtree(empty_dir, ignore_errors=True)


def test_sandbox_root_containment_validation(react_sandbox):
    """Test 4: Target paths attempting directory traversal outside sandbox are blocked."""
    run_id, sb_dir = react_sandbox

    coder = GoogleADKCoderAgent()
    with pytest.raises(PermissionError) as exc_info:
        coder.implement_changes(
            run_id=run_id,
            task_id="TSK-TRAVERSAL",
            instruction="Malicious file write",
            context={"target_file": "../../etc/shadow", "sandbox_path": str(sb_dir)},
        )
    assert "Path traversal detected" in str(exc_info.value)


def test_stale_context_cleared_between_runs(react_sandbox):
    """Test 5: Shared Blackboard state and prior patches are cleared on new run commencement."""
    run_id, sb_dir = react_sandbox

    # Populate blackboard with simulated stale state
    global_blackboard.reset()
    global_blackboard.update_metadata("repository", {"stale_key": "stale_value"})
    assert "repository" in global_blackboard.state.metadata

    # Running execution resets the blackboard
    orch = AutonomousEngineeringOrchestrator(
        pattern=AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A,
        persona=PersonaType.BALANCED_ENGINEER,
    )

    mock_event = MagicMock()
    mock_part = MagicMock()
    mock_part.text = (
        '```tsx\nimport React from "react";\nexport function App() { return <div className="badge">Support Portal (42)</div>; }\n```\n'
    )
    mock_event.content.parts = [mock_part]
    mock_event.usage_metadata = None

    with patch.object(orch.coder.runner, "run", return_value=[mock_event]):
        metrics = orch.execute_requirement(
            raw_prompt="Add ticket count badge to src/App.tsx",
            target_repo=f"runs/{run_id}",
        )

    # Verify old stale metadata is cleared and active patches reflect only the new execution
    assert "stale_key" not in global_blackboard.state.metadata.get("repository", {})
    assert "src/App.tsx" in global_blackboard.state.active_patches
    assert "src/calculator.py" not in global_blackboard.state.active_patches


def test_planner_dynamic_analysis_non_calculator():
    """Test 6: Planner dynamically analyzes non-calculator requirements without hardcoded defaults."""
    planner = CrewAIPlannerAgent()
    req = DeveloperRequirement(
        raw_prompt="Add real-time notifications for urgent tickets in TicketFormDrawer.tsx",
        target_repo_path="runs/test_repo",
    )

    plan = planner.plan_requirement(req)
    assert plan is not None

    analysis = global_blackboard.state.analysis
    assert analysis is not None
    assert "standard_deviation" not in analysis.title
    assert "AdvancedCalculator" not in analysis.title
    assert "TicketFormDrawer.tsx" in analysis.architectural_impact or "test_repo" in analysis.architectural_impact
    assert any("notifications" in ac.description.lower() or "functionality" in ac.description.lower() for ac in analysis.acceptance_criteria)


def test_ast_chunker_indexes_typescript_and_react(react_sandbox):
    """Test 7: AST chunker indexes .tsx, .ts, and .json files with semantic line numbers."""
    run_id, sb_dir = react_sandbox

    chunker = ASTCodeChunker()
    chunks = chunker.scan_and_chunk_repository(sb_dir)

    indexed_paths = {c.file_path for c in chunks}
    assert "src/App.tsx" in indexed_paths
    assert "src/components/TicketCard.tsx" in indexed_paths
    assert "src/pages/DashboardPage.tsx" in indexed_paths
    assert "package.json" in indexed_paths

    for chunk in chunks:
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line
        assert len(chunk.content.strip()) > 0


def test_non_pytest_repository_test_generation(react_sandbox):
    """Test 8: TestGeneratorAgent handles repos without pytest by reporting FUNCTIONAL_TESTS_NOT_CONFIGURED."""
    run_id, sb_dir = react_sandbox

    tester = GoogleADKTestGeneratorAgent()
    report = tester.generate_and_run_tests(
        run_id=run_id,
        sandbox_path=str(sb_dir),
        task_id="TSK-TEST-REACT",
    )

    assert report is not None
    assert report.all_passed is False
    assert report.total_tests == 0
    assert "FUNCTIONAL_TESTS_NOT_CONFIGURED" in report.raw_stderr
