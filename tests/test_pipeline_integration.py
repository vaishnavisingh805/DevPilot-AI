"""Comprehensive Integration Tests for Phase 2.2: GitHub + RAG Pipeline.

Verifies end-to-end integration:
1. Repository Workflow: RepositoryConfig validation, safe cloning to isolated sandbox, dedicated branch creation.
2. RAG Intelligence: AST chunking, semantic vector indexing, context retrieval, provenance tracking.
3. Coding Integration: RAG context injection, dynamic target file discovery, sandboxed patching.
4. Testing & Debugging: Test execution in isolated repo, diagnostic capture, failure recovery self-healing.
5. Auditor & HITL Safety: Real git diff generation, AST security audit, gatekeeper sign-off, strict branch isolation.
6. Multi-Architecture Compatibility: Hierarchical, Sequential, and Critic-Reflection architectures.

Zero Gemini API quota consumed (deterministic simulation & local git operations).
"""

import subprocess
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from core.schemas import (
    RepositoryConfig,
    DeveloperRequirement,
    RequirementAnalysis,
    AcceptanceCriterion,
    ExecutionPlan,
    TaskItem,
    TaskStatus,
    TaskFramework,
    CodeChangeProposal,
    FilePatch,
    ChangeType,
    TestResultReport,
    TestResultItem,
)
from core.blackboard import global_blackboard
from core.a2a import global_a2a_bus, A2AEnvelope, A2AMessageType
from core.hitl import hitl_gatekeeper
from mcp_servers.repo_tool import mcp_repo_client
from mcp_servers.repo_tool.server import _resolve_sandbox_path
from core.git.git_manager import git_manager
from agents.google_adk import RepositoryRAGAgent, GoogleADKCoderAgent
from agents.crewai import CrewAIPlannerAgent, CrewAIManagerAgent, CrewAIAuditorAgent
from orchestration import (
    AutonomousEngineeringOrchestrator,
    AgenticPatternType,
    SequentialBaselineOrchestrator,
    CriticReflectionOrchestrator,
)
from orchestration.failure_recovery import FailureRecoveryController


@pytest.fixture
def local_git_repo(tmp_path: Path):
    """Creates a local upstream Git repository with source and tests for testing."""
    repo_dir = tmp_path / "upstream_math_repo"
    repo_dir.mkdir(parents=True)

    # Initialize Git
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "PipelineTester"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.email", "pipeline@test.local"], cwd=str(repo_dir), check=True)

    # Create source files
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "calculator.py").write_text(
        "import math\n"
        "from typing import List, Union\n\n"
        "class AdvancedCalculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n"
        "    def subtract(self, a, b):\n"
        "        return a - b\n"
        "    def mean(self, numbers):\n"
        "        if not numbers:\n"
        "            raise ValueError('empty')\n"
        "        return sum(numbers) / len(numbers)\n",
        encoding="utf-8",
    )

    # Create test files
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_calculator.py").write_text(
        "import pytest\n"
        "from src.calculator import AdvancedCalculator\n\n"
        "@pytest.fixture\n"
        "def calc():\n"
        "    return AdvancedCalculator()\n\n"
        "def test_add(calc):\n"
        "    assert calc.add(2, 3) == 5\n\n"
        "def test_mean(calc):\n"
        "    assert calc.mean([2, 4, 6]) == 4.0\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit on main"], cwd=str(repo_dir), check=True)

    return repo_dir


def test_repository_config_validation():
    """Verify Pydantic RepositoryConfig handles URLs and local paths safely."""
    # Remote GitHub URL
    cfg_remote = RepositoryConfig(
        repo_url="https://github.com/torvalds/linux",
        base_branch="master",
        task_id="TASK-KERNEL-01",
    )
    assert cfg_remote.is_github is True
    assert cfg_remote.base_branch == "master"
    assert cfg_remote.task_id == "TASK-KERNEL-01"

    # Local repository target
    cfg_local = RepositoryConfig(
        repo_url="sample_repo",
        base_branch="main",
        task_id="TASK-LOCAL-01",
    )
    assert cfg_local.is_github is False
    assert cfg_local.repo_url == "sample_repo"

    # Rejection of unsafe inputs
    with pytest.raises(ValueError):
        RepositoryConfig(repo_url="https://github.com/evil; rm -rf /")


def test_git_cloning_and_isolated_branch_creation(local_git_repo: Path):
    """Verify cloning a Git repository into an isolated sandbox and creating agentic branch."""
    # Clone repository via MCP Repo Client
    clone_res = mcp_repo_client.clone_repository(repo_url=str(local_git_repo), base_branch="main")
    assert clone_res["success"] is True
    run_id = clone_res["run_id"]
    sandbox_path = Path(clone_res["sandbox_path"])

    assert sandbox_path.exists()
    assert (sandbox_path / ".git").exists()
    assert (sandbox_path / "src" / "calculator.py").exists()

    # Create isolated agentic branch
    branch_res = mcp_repo_client.create_branch(run_id=run_id, task_id="REQ-42")
    assert branch_res["success"] is True
    assert branch_res["branch_name"].startswith("agentic/REQ-42-")

    # Verify active branch inside sandbox
    current_branch = git_manager.get_current_branch(sandbox_path)
    assert current_branch == branch_res["branch_name"]

    # Verify upstream repository remains strictly on 'main'
    upstream_branch = git_manager.get_current_branch(local_git_repo)
    assert upstream_branch == "main"


def test_rag_agent_indexing_and_context_retrieval(local_git_repo: Path):
    """Verify RepositoryRAGAgent indexes AST chunks and returns semantic context."""
    global_blackboard.reset()
    clone_res = mcp_repo_client.clone_repository(repo_url=str(local_git_repo))
    run_id = clone_res["run_id"]
    sandbox_path = Path(clone_res["sandbox_path"])

    rag_agent = RepositoryRAGAgent()
    retrieval = rag_agent.retrieve_context(
        query="Calculate arithmetic mean and addition",
        repo_path=sandbox_path,
        repo_id=run_id,
        top_k=3,
    )

    assert retrieval["success"] is True
    assert retrieval["chunk_count"] >= 1
    assert "calculator.py" in retrieval["context"]
    assert "mean" in retrieval["context"] or "add" in retrieval["context"]

    # Verify Shared Blackboard metadata captured RAG context
    bb_context = global_blackboard.state.metadata.get("retrieved_context")
    assert bb_context is not None
    assert bb_context["chunk_count"] >= 1


def test_rag_context_injection_into_planner_and_coder(local_git_repo: Path):
    """Verify RAG context is passed to Planner and Coder agents."""
    global_blackboard.reset()
    clone_res = mcp_repo_client.clone_repository(repo_url=str(local_git_repo))
    run_id = clone_res["run_id"]
    sandbox_path = Path(clone_res["sandbox_path"])

    # 1. Retrieve RAG context
    rag_agent = RepositoryRAGAgent()
    rag_res = rag_agent.retrieve_context(
        query="Implement standard_deviation",
        repo_path=sandbox_path,
        repo_id=run_id,
    )
    rag_context = rag_res["context"]

    # 2. Plan requirement with RAG context
    planner = CrewAIPlannerAgent()
    req = DeveloperRequirement(
        raw_prompt="Add standard_deviation to AdvancedCalculator",
        target_repo_path=str(local_git_repo),
    )
    plan = planner.plan_requirement(req, rag_context=rag_context)
    assert plan is not None
    assert len(plan.tasks) >= 3

    # 3. Code requirement with RAG context
    coder = GoogleADKCoderAgent()
    proposal = coder.implement_changes(
        run_id=run_id,
        task_id="TSK-02-CODING",
        instruction="Add standard_deviation method",
        context={
            "sandbox_path": str(sandbox_path),
            "rag_context": rag_context,
            "retrieved_chunks": rag_res["results"],
        },
    )
    assert proposal is not None
    assert len(proposal.patches) >= 1
    assert "standard_deviation" in proposal.patches[0].modified_content


def test_safe_branch_modification_and_diff_generation(local_git_repo: Path):
    """Verify sandboxed changes stay inside isolated branch and generate real Git diffs."""
    clone_res = mcp_repo_client.clone_repository(repo_url=str(local_git_repo))
    run_id = clone_res["run_id"]
    sandbox_path = Path(clone_res["sandbox_path"])

    branch_res = mcp_repo_client.create_branch(run_id=run_id, task_id="DIFF-TEST")
    branch_name = branch_res["branch_name"]

    # Apply patch to sandbox
    new_code = (
        "class AdvancedCalculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n"
        "    def subtract(self, a, b):\n"
        "        return a - b\n"
        "    def mean(self, numbers):\n"
        "        if not numbers:\n"
        "            raise ValueError('empty')\n"
        "        return sum(numbers) / len(numbers)\n"
        "    def power(self, base, exp):\n"
        "        return base ** exp\n"
    )
    patch_res = mcp_repo_client.apply_patch(
        run_id=run_id,
        file_path="src/calculator.py",
        content=new_code,
        justification="Add power function",
    )
    assert patch_res["success"] is True

    # Verify Git status
    status = mcp_repo_client.get_status(run_id=run_id)
    assert status["is_dirty"] is True
    assert "src/calculator.py" in status["modified"]

    # Verify Git diff
    diff_res = mcp_repo_client.get_diff(run_id=run_id)
    assert diff_res["success"] is True
    assert "+    def power(self, base, exp):" in diff_res["diff"]

    # Verify upstream repo is completely untouched
    upstream_calc = (local_git_repo / "src" / "calculator.py").read_text(encoding="utf-8")
    assert "def power" not in upstream_calc


def test_failure_recovery_controller_self_healing(local_git_repo: Path):
    """Verify failure recovery controller invokes Debugger to fix defect."""
    global_blackboard.reset()
    clone_res = mcp_repo_client.clone_repository(repo_url=str(local_git_repo))
    run_id = clone_res["run_id"]
    sandbox_path = str(clone_res["sandbox_path"])

    # Simulate failing test report
    failed_report = TestResultReport(
        all_passed=False,
        total_tests=3,
        passed=2,
        failed=1,
        items=[
            TestResultItem(
                name="test_mean",
                test_node_id="tests/test_calculator.py::test_mean",
                outcome="failed",
                failure_message="ZeroDivisionError: division by zero",
            )
        ],
    )
    global_blackboard.post_test_report(failed_report)

    controller = FailureRecoveryController(max_recovery_cycles=2)
    recovery_res = controller.attempt_recovery(
        run_id=run_id,
        sandbox_path=sandbox_path,
        failed_report=failed_report,
    )

    assert recovery_res["recovered"] is True
    assert recovery_res["cycles"] == 1
    assert global_blackboard.state.failure_recovery_cycles == 1


def test_hitl_approval_and_rejection_safety(local_git_repo: Path):
    """Verify HITL gatekeeper blocks unapproved commits and preserves remote branch on commit."""
    global_blackboard.reset()
    clone_res = mcp_repo_client.clone_repository(repo_url=str(local_git_repo))
    run_id = clone_res["run_id"]
    sandbox_path = Path(clone_res["sandbox_path"])

    mcp_repo_client.create_branch(run_id=run_id, task_id="HITL-TEST")

    # Apply change
    mcp_repo_client.apply_patch(
        run_id=run_id,
        file_path="src/calculator.py",
        content="# Modified\n",
        justification="HITL verification",
    )

    # 1. Rejection test
    hitl_gatekeeper.reject("Did not satisfy acceptance criteria")
    assert global_blackboard.state.human_approval_status == "rejected"

    # Attempt unapproved commit
    unapproved_commit = mcp_repo_client.commit_to_main(
        run_id=run_id,
        target_repo=str(local_git_repo),
        human_approved=False,
    )
    assert unapproved_commit["success"] is False
    assert "HUMAN_APPROVAL_REQUIRED" in unapproved_commit["error"]

    # 2. Populate required blackboard artifacts for readiness evaluation
    from core.schemas import FilePatch, CodeChangeProposal, ChangeType, TestResultReport, SecurityAuditReport
    file_patch = FilePatch(
        file_path="src/calculator.py",
        change_type=ChangeType.MODIFY,
        modified_content="# Modified\n",
        unified_diff="--- a/src/calculator.py\n+++ b/src/calculator.py\n@@ -0,0 +1 @@\n+# Modified\n",
        justification="HITL verification",
    )
    proposal = CodeChangeProposal(task_id="HITL-TEST", author_agent="TestAgent", patches=[file_patch])
    global_blackboard.post_code_proposal(proposal)

    report = TestResultReport(total_tests=1, passed=1, failed=0, errors=0, skipped=0, all_passed=True)
    global_blackboard.post_test_report(report)

    audit = SecurityAuditReport(passed=True, recommendation="Approved")
    global_blackboard.post_security_audit(audit)

    global_blackboard.update_metadata("sandbox_run_id", run_id)
    global_blackboard.update_metadata("repository", {"run_id": run_id, "repo_url": str(local_git_repo)})

    # 3. Approval test
    approval_res = hitl_gatekeeper.approve_and_commit(
        run_id=run_id,
        approver="Lead Architect",
        notes="All checks verified",
        target_repo=str(local_git_repo),
    )
    assert approval_res["success"] is True
    assert approval_res["status"] == "COMMITTED_LOCALLY"
    assert "Remote default branch preserved untouched" in approval_res["message"]

    # Upstream main commit history must remain unaffected
    head_sha = git_manager.get_head_commit_sha(local_git_repo)
    assert approval_res.get("commit_sha") != head_sha


def test_hierarchical_orchestrator_end_to_end_with_git(local_git_repo: Path):
    """Verify AutonomousEngineeringOrchestrator runs end-to-end against local Git repo."""
    global_blackboard.reset()
    orchestrator = AutonomousEngineeringOrchestrator(
        pattern=AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A
    )

    repo_config = RepositoryConfig(
        repo_url=str(local_git_repo),
        base_branch="main",
        task_id="TASK-E2E-01",
    )

    metrics = orchestrator.execute_requirement(
        raw_prompt="Implement standard_deviation calculation in AdvancedCalculator",
        target_repo=repo_config,
        auto_commit_if_approved=True,
    )

    assert metrics.success is True
    assert metrics.test_pass_rate_percentage == 100.0
    assert metrics.total_tokens > 0

    # Verify Blackboard recorded repository metadata and RAG context
    repo_meta = global_blackboard.state.metadata.get("repository")
    assert repo_meta is not None
    assert repo_meta["agentic_branch"].startswith("agentic/TASK-E2E-01-")

    # Verify delivery package has unified diff
    delivery = global_blackboard.state.final_delivery
    assert delivery is not None
    assert len(delivery.unified_diff) > 0


def test_sequential_baseline_with_git(local_git_repo: Path):
    """Verify SequentialBaselineOrchestrator executes against local Git repo."""
    orchestrator = SequentialBaselineOrchestrator()
    repo_config = RepositoryConfig(
        repo_url=str(local_git_repo),
        base_branch="main",
        task_id="TASK-SEQ-01",
    )

    metrics = orchestrator.execute_requirement(
        raw_prompt="Add standard_deviation to AdvancedCalculator",
        target_repo=repo_config,
        auto_commit_if_approved=True,
    )

    assert metrics.success is True
    assert metrics.architecture_pattern == AgenticPatternType.SEQUENTIAL_BASELINE.value


def test_critic_reflection_with_git(local_git_repo: Path):
    """Verify CriticReflectionOrchestrator executes against local Git repo."""
    orchestrator = CriticReflectionOrchestrator(max_reflections=1)
    repo_config = RepositoryConfig(
        repo_url=str(local_git_repo),
        base_branch="main",
        task_id="TASK-CRITIC-01",
    )

    metrics = orchestrator.execute_requirement(
        raw_prompt="Add standard_deviation to AdvancedCalculator",
        target_repo=repo_config,
        auto_commit_if_approved=True,
    )

    assert metrics.success is True
    assert metrics.architecture_pattern == AgenticPatternType.CRITIC_REFLECTION_LOOP.value
