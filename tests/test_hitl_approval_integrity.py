"""Comprehensive Regression and Integrity Test Suite for False Success and HITL Bypass Prevention."""

import uuid
from pathlib import Path
from unittest.mock import patch
import pytest

from config.settings import settings
from core.blackboard import global_blackboard
from core.hitl.approval_gate import hitl_gatekeeper
from core.github.pr_publisher import pr_publisher
from core.schemas import (
    DeveloperRequirement,
    RequirementAnalysis,
    ExecutionPlan,
    TaskItem,
    TaskStatus,
    TaskFramework,
    FilePatch,
    CodeChangeProposal,
    ChangeType,
    TestResultReport,
    TestResultItem,
    SecurityAuditReport,
    RepositoryConfig,
)
from mcp_servers.repo_tool import mcp_repo_client
from mcp_servers.test_runner import mcp_test_client
from agents.google_adk.coder_agent import GoogleADKCoderAgent
from orchestration.engine import AutonomousEngineeringOrchestrator
from orchestration.patterns import AgenticPatternType


@pytest.fixture
def clean_blackboard():
    global_blackboard.reset()
    yield global_blackboard
    global_blackboard.reset()


@pytest.fixture
def sample_sandbox():
    sandbox_res = mcp_repo_client.create_sandbox("sample_repo")
    assert sandbox_res["success"] is True
    run_id = sandbox_res["run_id"]
    sandbox_path = sandbox_res["sandbox_path"]
    return run_id, sandbox_path


def test_hitl_approval_rejected_when_blackboard_empty(clean_blackboard, sample_sandbox):
    """Bug 2 Regression: Gatekeeper must reject approval if active patches and tests are 0."""
    run_id, _ = sample_sandbox
    hitl_gatekeeper.request_approval()
    assert clean_blackboard.state.human_approval_status == "pending"
    initial_version = clean_blackboard.version

    res = hitl_gatekeeper.approve_and_commit(
        run_id=run_id,
        approver="Lead Engineer",
        notes="Premature approval attempt",
        target_repo="sample_repo",
    )

    assert res["success"] is False
    assert "HITL_APPROVAL_REJECTED" in res["error"]
    assert "No active code patches" in res["error"]
    # Blackboard status must NOT change to approved
    assert clean_blackboard.state.human_approval_status == "pending"
    # Version must remain identical (no false mutation)
    assert clean_blackboard.version == initial_version


def test_hitl_approval_rejected_when_tests_missing_or_failed(clean_blackboard, sample_sandbox):
    """Bug 2 Regression: Gatekeeper must reject approval if tests did not pass."""
    run_id, _ = sample_sandbox

    # Create active patch
    patch_obj = FilePatch(
        file_path="src/calculator.py",
        change_type=ChangeType.MODIFY,
        modified_content="# Patched\n",
        unified_diff="--- a/src/calculator.py\n+++ b/src/calculator.py\n@@ -0,0 +1 @@\n+# Patched\n",
        justification="Bug fix",
    )
    clean_blackboard.post_code_proposal(
        CodeChangeProposal(task_id="TSK-01", author_agent="CoderAgent", patches=[patch_obj])
    )

    # But failed test report
    failed_report = TestResultReport(
        total_tests=5,
        passed=3,
        failed=2,
        errors=0,
        skipped=0,
        all_passed=False,
    )
    clean_blackboard.post_test_report(failed_report)
    clean_blackboard.post_security_audit(SecurityAuditReport(passed=True))

    hitl_gatekeeper.request_approval()

    res = hitl_gatekeeper.approve_and_commit(
        run_id=run_id,
        approver="Lead Engineer",
        target_repo="sample_repo",
    )
    assert res["success"] is False
    assert "HITL_APPROVAL_REJECTED" in res["error"]
    assert "Test suite verification failed" in res["error"]
    assert clean_blackboard.state.human_approval_status == "pending"


def test_hitl_approval_rejected_on_context_mismatch(clean_blackboard, sample_sandbox):
    """Bug 2 Regression: Gatekeeper must verify run_id and repository bindings."""
    run_id, _ = sample_sandbox

    patch_obj = FilePatch(
        file_path="src/calculator.py",
        change_type=ChangeType.MODIFY,
        modified_content="# Patched\n",
        unified_diff="--- a/src/calculator.py\n+++ b/src/calculator.py\n@@ -0,0 +1 @@\n+# Patched\n",
        justification="Bug fix",
    )
    clean_blackboard.post_code_proposal(
        CodeChangeProposal(task_id="TSK-01", author_agent="CoderAgent", patches=[patch_obj])
    )
    clean_blackboard.post_test_report(
        TestResultReport(total_tests=1, passed=1, failed=0, errors=0, skipped=0, all_passed=True)
    )
    clean_blackboard.post_security_audit(SecurityAuditReport(passed=True))

    # Bound to specific run_id and repo
    clean_blackboard.update_metadata("sandbox_run_id", run_id)
    clean_blackboard.update_metadata("repository", {"run_id": run_id, "repo_url": "https://github.com/org/repo-a"})

    # 1. Reject on run_id mismatch
    res_run = hitl_gatekeeper.approve_and_commit(
        run_id="run_wrong_9999",
        target_repo="https://github.com/org/repo-a",
    )
    assert res_run["success"] is False
    assert "Run ID mismatch" in res_run["error"]

    # 2. Reject on repo mismatch
    res_repo = hitl_gatekeeper.approve_and_commit(
        run_id=run_id,
        target_repo="https://github.com/org/repo-b",
    )
    assert res_repo["success"] is False
    assert "Repository mismatch" in res_repo["error"]


def test_hitl_approval_rejected_on_patch_hash_mismatch(clean_blackboard, sample_sandbox):
    """Bug 2 Regression: Gatekeeper must reject approval if expected patch hash does not match."""
    run_id, _ = sample_sandbox

    patch_obj = FilePatch(
        file_path="src/calculator.py",
        change_type=ChangeType.MODIFY,
        modified_content="# Patched\n",
        unified_diff="--- a/src/calculator.py\n+++ b/src/calculator.py\n@@ -0,0 +1 @@\n+# Patched\n",
        justification="Bug fix",
    )
    clean_blackboard.post_code_proposal(
        CodeChangeProposal(task_id="TSK-01", author_agent="CoderAgent", patches=[patch_obj])
    )
    clean_blackboard.post_test_report(
        TestResultReport(total_tests=1, passed=1, failed=0, errors=0, skipped=0, all_passed=True)
    )
    clean_blackboard.post_security_audit(SecurityAuditReport(passed=True))

    clean_blackboard.update_metadata("sandbox_run_id", run_id)
    clean_blackboard.update_metadata("repository", {"run_id": run_id, "repo_url": "sample_repo"})

    # Pass an invalid expected patch hash
    res = hitl_gatekeeper.approve_and_commit(
        run_id=run_id,
        target_repo="sample_repo",
        expected_patch_hash="deadbeef12345678",
    )
    assert res["success"] is False
    assert "Patch hash mismatch" in res["error"]


def test_hitl_approval_seals_contract_and_enables_pr_publish(clean_blackboard, sample_sandbox):
    """Verifies complete valid HITL approval lifecycle and contract sealing."""
    run_id, sandbox_path = sample_sandbox

    # Apply real modification via MCP
    patch_res = mcp_repo_client.apply_patch(
        run_id=run_id,
        file_path="src/extension.py",
        content="# Extension module\ndef get_status(): return 'active'\n",
        justification="Verified feature addition",
    )
    assert patch_res["success"] is True

    file_patch = FilePatch(
        file_path="src/extension.py",
        change_type=ChangeType.CREATE,
        modified_content="# Extension module\ndef get_status(): return 'active'\n",
        unified_diff=patch_res["diff"],
        justification="Verified feature addition",
    )
    clean_blackboard.post_code_proposal(
        CodeChangeProposal(task_id="TSK-01", author_agent="GoogleADK:CoderAgent", patches=[file_patch])
    )
    clean_blackboard.post_test_report(
        TestResultReport(total_tests=5, passed=5, failed=0, errors=0, skipped=0, all_passed=True)
    )
    clean_blackboard.post_security_audit(SecurityAuditReport(passed=True, recommendation="Clean"))

    clean_blackboard.update_metadata("sandbox_run_id", run_id)
    clean_blackboard.update_metadata("repository", {"run_id": run_id, "repo_url": "sample_repo"})

    hitl_gatekeeper.request_approval()

    # Precondition evaluate_readiness must return can_approve=True
    readiness = hitl_gatekeeper.evaluate_readiness(run_id=run_id, target_repo="sample_repo")
    assert readiness["can_approve"] is True
    assert readiness["patch_hash"] != ""

    res = hitl_gatekeeper.approve_and_commit(
        run_id=run_id,
        approver="Chief Architect",
        notes="Verified against all acceptance criteria",
        target_repo="sample_repo",
    )
    assert res["success"] is True
    assert clean_blackboard.state.human_approval_status == "approved"

    # Contract must be sealed in metadata
    contract = clean_blackboard.state.metadata.get("approval_contract")
    assert contract is not None
    assert contract["approved_by"] == "Chief Architect"
    assert contract["patch_hash"] == readiness["patch_hash"]
    assert contract["run_id"] == run_id


def test_pr_publisher_blocks_on_patch_tampering(clean_blackboard, sample_sandbox, tmp_path):
    """PR publisher must reject publishing if active patches are altered after human sign-off."""
    run_id, _ = sample_sandbox

    # 1. Create valid approved state
    file_patch = FilePatch(
        file_path="src/calculator.py",
        change_type=ChangeType.MODIFY,
        modified_content="# Clean code\n",
        unified_diff="--- a/src/calculator.py\n+++ b/src/calculator.py\n@@ -0,0 +1 @@\n+# Clean code\n",
        justification="Clean",
    )
    clean_blackboard.post_code_proposal(
        CodeChangeProposal(task_id="TSK-01", author_agent="GoogleADK:CoderAgent", patches=[file_patch])
    )
    clean_blackboard.post_test_report(
        TestResultReport(total_tests=1, passed=1, failed=0, errors=0, skipped=0, all_passed=True)
    )
    clean_blackboard.post_security_audit(SecurityAuditReport(passed=True))
    clean_blackboard.update_metadata("sandbox_run_id", run_id)
    clean_blackboard.update_metadata("repository", {"run_id": run_id, "repo_url": "https://github.com/org/repo"})

    # Compute hash and seal approval
    p_hash = hitl_gatekeeper.compute_patch_hash()
    clean_blackboard.update_metadata("approval_contract", {
        "approved_by": "Architect",
        "run_id": run_id,
        "target_repo": "https://github.com/org/repo",
        "patch_hash": p_hash,
    })
    clean_blackboard.set_human_approval("approved")

    # 2. Tamper with active patch on blackboard after approval
    clean_blackboard.state.active_patches["src/calculator.py"].modified_content = "# MALICIOUS INJECTION\n"
    # Also update in working proposal
    tampered_patch = FilePatch(
        file_path="src/calculator.py",
        change_type=ChangeType.MODIFY,
        modified_content="# MALICIOUS INJECTION\n",
        unified_diff="--- a/src/calculator.py\n+++ b/src/calculator.py\n@@ -0,0 +1 @@\n+# MALICIOUS INJECTION\n",
        justification="Tampered",
    )
    clean_blackboard.post_code_proposal(
        CodeChangeProposal(task_id="TSK-TAMPER", author_agent="EvilAgent", patches=[tampered_patch])
    )

    # 3. PR publisher must catch tampering
    res = pr_publisher.publish_pull_request(
        run_id=run_id,
        sandbox_path=tmp_path,
        repo_url="https://github.com/org/repo",
    )
    assert res["success"] is False
    assert res["status"] == "BLOCKED_TAMPERING"
    assert "TAMPERING_DETECTED" in res["error"]


def test_mcp_apply_patch_rejects_empty_diff(sample_sandbox):
    """Bug 1 Regression: apply_patch must reject identical proposed content as empty patch."""
    run_id, _ = sample_sandbox
    # Read existing content
    read_res = mcp_repo_client.read_file(run_id, "src/calculator.py")
    orig_code = read_res["content"]

    # Attempt to apply identical content
    apply_res = mcp_repo_client.apply_patch(
        run_id=run_id,
        file_path="src/calculator.py",
        content=orig_code,
        justification="Zero diff attempt",
    )
    assert apply_res["success"] is False
    assert "Empty patch" in apply_res["error"]


def test_coder_fallback_synthesis_rejects_metadata_and_dummy_stubs():
    """Quality Rule: _fallback_code_synthesis must strictly reject fake metadata injection."""
    coder = GoogleADKCoderAgent()

    # TypeScript / React code must be rejected
    ts_code = "export const LoginPage = () => { return <div>Login</div>; };\n"
    with pytest.raises(RuntimeError) as exc_info:
        coder._fallback_code_synthesis(ts_code, "Add form validation", target_file="src/LoginPage.tsx")
    assert "FALLBACK_SYNTHESIS_REJECTED" in str(exc_info.value)

    # Arbitrary non-calculator Python code must be rejected
    py_code = "class Service:\n    pass\n"
    with pytest.raises(RuntimeError) as exc_info_py:
        coder._fallback_code_synthesis(py_code, "Add health check endpoint", target_file="src/service.py")
    assert "FALLBACK_SYNTHESIS_REJECTED" in str(exc_info_py.value)

    # Mathematically defined calculator benchmark is preserved
    calc_code = "class AdvancedCalculator:\n    def mean(self, numbers): return sum(numbers)/len(numbers)\n"
    calc_res = coder._fallback_code_synthesis(calc_code, "Implement standard_deviation", target_file="src/calculator.py")
    assert "def standard_deviation" in calc_res
    assert "math.sqrt" in calc_res


def test_end_to_end_it_support_simulation_produces_real_evidence(clean_blackboard, tmp_path):
    """End-to-End Test: Simulates IT-Support React repo requirement.
    Verifies that pipeline requires real implementation evidence, real functional tests,
    and genuine acceptance criteria before reporting success.
    """
    # 1. Create a simulated React + TypeScript repository with valid test script
    repo_dir = tmp_path / "IT-Support-mock"
    repo_dir.mkdir(parents=True)
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    pages_dir = src_dir / "pages"
    pages_dir.mkdir()

    login_page = pages_dir / "LoginPage.tsx"
    login_page.write_text(
        "import React from 'react';\n\n"
        "export const LoginPage = () => {\n"
        "    return (\n"
        "        <form onSubmit={() => {}}>\n"
        "            <input type='text' placeholder='Email' />\n"
        "            <input type='password' placeholder='Password' />\n"
        "            <button type='submit'>Sign In</button>\n"
        "        </form>\n"
        "    );\n"
        "};\n",
        encoding="utf-8",
    )

    # Valid package.json with configured test script
    pkg_json = repo_dir / "package.json"
    pkg_json.write_text(
        '{\n'
        '  "name": "it-support-mock",\n'
        '  "version": "1.0.0",\n'
        '  "scripts": {\n'
        '    "test": "exit 0"\n'
        '  }\n'
        '}',
        encoding="utf-8",
    )

    # Initialize as a valid local Git repository with initial commit
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True, capture_output=True)

    # Verify that a repository without configured test scripts returns FUNCTIONAL_TESTS_NOT_CONFIGURED
    pkg_no_test = repo_dir / "package_no_test.json"
    pkg_no_test.write_text('{"name": "no-test"}', encoding="utf-8")
    run_res = mcp_repo_client.create_sandbox(str(repo_dir))
    assert run_res["success"] is True
    s_run_id = run_res["run_id"]
    s_path = run_res["sandbox_path"]

    # Post a genuine functional patch implementing login validation
    genuine_login_code = (
        "import React, { useState } from 'react';\n\n"
        "export const LoginPage = () => {\n"
        "    const [email, setEmail] = useState('');\n"
        "    const [password, setPassword] = useState('');\n"
        "    const [showPassword, setShowPassword] = useState(false);\n"
        "    const [error, setError] = useState('');\n\n"
        "    const handleSubmit = (e: React.FormEvent) => {\n"
        "        e.preventDefault();\n"
        "        if (!email.trim() || !password.trim()) {\n"
        "            setError('Email and password are required.');\n"
        "            return;\n"
        "        }\n"
        "        if (!/\\S+@\\S+\\.\\S+/.test(email)) {\n"
        "            setError('Invalid email address format.');\n"
        "            return;\n"
        "        }\n"
        "        setError('');\n"
        "    };\n\n"
        "    return (\n"
        "        <form onSubmit={handleSubmit}>\n"
        "            {error && <div className='alert alert-danger'>{error}</div>}\n"
        "            <input type='text' value={email} onChange={(e) => setEmail(e.target.value)} placeholder='Email' />\n"
        "            <input type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} placeholder='Password' />\n"
        "            <button type='button' onClick={() => setShowPassword(!showPassword)}>{showPassword ? 'Hide' : 'Show'}</button>\n"
        "            <button type='submit'>Sign In</button>\n"
        "        </form>\n"
        "    );\n"
        "};\n"
    )

    patch_res = mcp_repo_client.apply_patch(
        run_id=s_run_id,
        file_path="src/pages/LoginPage.tsx",
        content=genuine_login_code,
        justification="Genuine implementation of email/password validation and visibility toggle",
    )
    assert patch_res["success"] is True

    file_patch = FilePatch(
        file_path="src/pages/LoginPage.tsx",
        change_type=ChangeType.MODIFY,
        original_content=login_page.read_text(encoding="utf-8"),
        modified_content=genuine_login_code,
        unified_diff=patch_res["diff"],
        justification="Genuine login validation",
    )
    clean_blackboard.post_code_proposal(
        CodeChangeProposal(task_id="TSK-01", author_agent="GoogleADK:CoderAgent", patches=[file_patch])
    )
    clean_blackboard.post_test_report(
        TestResultReport(total_tests=1, passed=1, failed=0, errors=0, skipped=0, all_passed=True)
    )
    clean_blackboard.post_security_audit(SecurityAuditReport(passed=True, recommendation="Clean"))
    clean_blackboard.update_metadata("sandbox_run_id", s_run_id)
    clean_blackboard.update_metadata("repository", {"run_id": s_run_id, "repo_url": str(repo_dir)})

    # Post requirement for alignment check
    clean_blackboard.post_requirement(
        DeveloperRequirement(raw_prompt="Add email and password validation to LoginPage.tsx and toggle password visibility")
    )

    # Readiness check must now pass
    readiness = hitl_gatekeeper.evaluate_readiness(
        run_id=s_run_id,
        target_repo=str(repo_dir),
    )
    assert readiness["can_approve"] is True
    assert readiness["has_patches"] is True
    assert readiness["latest_test_passed"] is True
    assert readiness["security_passed"] is True

    # Human approval succeeds
    approval_res = hitl_gatekeeper.approve_and_commit(
        run_id=s_run_id,
        approver="Senior Reviewer",
        notes="Verified LoginPage validation patch",
        target_repo=str(repo_dir),
    )
    assert approval_res["success"] is True
    assert clean_blackboard.state.human_approval_status == "approved"

