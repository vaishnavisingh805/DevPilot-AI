"""Regression and Quality Test Suite for Final Coding Agent Quality Fixes.

Covers all 12 mandatory quality and safety test scenarios:
1. Metadata-only TypeScript patch is rejected.
2. Comment-only patch is rejected.
3. Unrelated TypeScript file modification is rejected.
4. Simulation cannot report feature-level PASSED.
5. Live model failure returns a structured error.
6. Genuine login validation implementation passes relevant checks.
7. Password visibility toggle is validated.
8. Missing functional tests prevent full functional verification.
9. Failed production build prevents successful delivery.
10. HITL approval remains blocked for simulated or unverified patches.
11. Existing Python repository functionality remains intact.
12. Original C1-C4 configurations remain intact.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.settings import settings
from core.blackboard import global_blackboard
from core.guardrails.implementation_validator import implementation_validator
from core.hitl.approval_gate import hitl_gatekeeper
from core.schemas import (
    DeveloperRequirement,
    CodeChangeProposal,
    FilePatch,
    ChangeType,
    TestResultReport,
    TestResultItem,
    SecurityAuditReport,
)
from mcp_servers.test_runner.server import run_pytest, detect_package_manager
from agents.google_adk.coder_agent import GoogleADKCoderAgent
from orchestration.engine import AutonomousEngineeringOrchestrator
from orchestration.patterns import AgenticPatternType, PATTERN_DESCRIPTIONS
from evaluation.comparison import ArchitectureComparator


@pytest.fixture
def clean_bb():
    global_blackboard.reset()
    yield global_blackboard
    global_blackboard.reset()


# ---------------------------------------------------------------------------
# Test 1: Metadata-only TypeScript patch is rejected
# ---------------------------------------------------------------------------
def test_metadata_only_typescript_patch_rejected():
    orig_code = "export const LoginPage = () => { return <div>Login</div>; };\n"
    # Synthetic metadata constant injection
    metadata_patch = (
        orig_code
        + "\nexport const devpilotFeature_abc123 = {\n"
        + "    feature: 'Add email and password validation',\n"
        + "    status: 'implemented_and_verified'\n"
        + "};\n"
    )
    diff = "--- a/src/LoginPage.tsx\n+++ b/src/LoginPage.tsx\n@@ -1 +1,5 @@\n+export const devpilotFeature_abc123 = {\n"

    is_valid, msg = implementation_validator.validate_patch_quality(
        file_path="src/LoginPage.tsx",
        original_code=orig_code,
        modified_code=metadata_patch,
        unified_diff=diff,
    )
    assert is_valid is False
    assert "METADATA_ONLY_PATCH" in msg


# ---------------------------------------------------------------------------
# Test 2: Comment-only patch is rejected
# ---------------------------------------------------------------------------
def test_comment_only_patch_rejected():
    orig_code = "export const Button = () => <button>Click</button>;\n"
    comment_patch = (
        "// DevPilot AI: Implementing new button styles\n"
        + "/* Detailed requirements documentation */\n"
        + orig_code
    )
    diff = "--- a/src/Button.tsx\n+++ b/src/Button.tsx\n@@ -0,0 +1,2 @@\n+// DevPilot AI: Implementing new button styles\n"

    is_valid, msg = implementation_validator.validate_patch_quality(
        file_path="src/Button.tsx",
        original_code=orig_code,
        modified_code=comment_patch,
        unified_diff=diff,
    )
    assert is_valid is False
    assert "COMMENT_ONLY_PATCH" in msg


# ---------------------------------------------------------------------------
# Test 3: Unrelated TypeScript file modification is rejected
# ---------------------------------------------------------------------------
def test_unrelated_typescript_file_modification_rejected():
    requirement = "Add email and password validation to LoginPage.tsx and show error alert on empty submit"
    unrelated_patch = FilePatch(
        file_path="src/utils/mathHelper.ts",
        change_type=ChangeType.MODIFY,
        original_content="export const add = (a, b) => a + b;\n",
        modified_content="export const add = (a, b) => a + b;\nexport const multiply = (a, b) => a * b;\n",
        unified_diff="@@ -1 +1,2 @@\n+export const multiply = (a, b) => a * b;\n",
        justification="Math helper addition",
    )
    patches = {"src/utils/mathHelper.ts": unrelated_patch}

    is_aligned, report = implementation_validator.validate_requirement_alignment(
        requirement_prompt=requirement,
        patches=patches,
    )
    assert is_aligned is False
    assert any("UNRELATED_FILE_MODIFICATION" in v for v in report.get("violations", []))


# ---------------------------------------------------------------------------
# Test 4: Simulation cannot report feature-level PASSED
# ---------------------------------------------------------------------------
def test_simulation_cannot_report_feature_level_passed(clean_bb):
    with patch.object(settings, "EXECUTION_MODE", "deterministic_simulation"):
        orchestrator = AutonomousEngineeringOrchestrator(
            pattern=AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A
        )
        metrics = orchestrator.execute_requirement(
            raw_prompt="Implement standard_deviation calculation in AdvancedCalculator",
            target_repo="sample_repo",
        )
        assert metrics.success is False
        assert "SIMULATION_MODE_ACTIVE" in (metrics.error_details or "")


# ---------------------------------------------------------------------------
# Test 5: Live model failure returns a structured error
# ---------------------------------------------------------------------------
def test_live_model_failure_returns_structured_error():
    coder = GoogleADKCoderAgent()

    # Mock read_file and runner.run to simulate model API failure in live mode
    with patch("mcp_servers.repo_tool.mcp_repo_client.read_file", return_value={"success": True, "content": "export const App = () => null;"}):
        with patch.object(coder.runner, "run", side_effect=Exception("API connection refused by Google Gemini server")):
            with patch.object(settings, "EXECUTION_MODE", "live"):
                with pytest.raises(RuntimeError) as exc_info:
                    coder.implement_changes(
                        run_id="run_test",
                        task_id="TSK-02",
                        instruction="Add feature",
                        context={"target_file": "src/App.tsx", "original_code": "export const App = () => null;"},
                    )
                assert "MODEL_GENERATION_FAILED" in str(exc_info.value)
                assert "API connection refused" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 6: Genuine login validation implementation passes relevant checks
# ---------------------------------------------------------------------------
def test_genuine_login_validation_implementation_passes_checks():
    requirement = "Add email and password validation to LoginPage.tsx and show error alert on empty submit"
    genuine_code = (
        "import React, { useState } from 'react';\n\n"
        "export const LoginPage = () => {\n"
        "    const [email, setEmail] = useState('');\n"
        "    const [password, setPassword] = useState('');\n"
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
        "            {error && <div role='alert'>{error}</div>}\n"
        "            <input type='email' value={email} onChange={(e) => setEmail(e.target.value)} />\n"
        "            <input type='password' value={password} onChange={(e) => setPassword(e.target.value)} />\n"
        "            <button type='submit'>Sign In</button>\n"
        "        </form>\n"
        "    );\n"
        "};\n"
    )
    patch_obj = FilePatch(
        file_path="src/pages/LoginPage.tsx",
        change_type=ChangeType.MODIFY,
        original_content="export const LoginPage = () => <form></form>;\n",
        modified_content=genuine_code,
        unified_diff="@@ -1 +1,28 @@\n+import React...",
        justification="Implemented genuine email and required field validation",
    )
    patches = {"src/pages/LoginPage.tsx": patch_obj}

    is_aligned, report = implementation_validator.validate_requirement_alignment(
        requirement_prompt=requirement,
        patches=patches,
    )
    assert is_aligned is True
    assert report.get("details", {}).get("email_validation") is True
    assert report.get("details", {}).get("required_field_validation") is True
    assert report.get("details", {}).get("auth_preserved") is True


# ---------------------------------------------------------------------------
# Test 7: Password visibility toggle is validated
# ---------------------------------------------------------------------------
def test_password_visibility_toggle_is_validated():
    requirement = "Add password visibility toggle to LoginPage.tsx"
    code_with_toggle = (
        "import React, { useState } from 'react';\n"
        "export const LoginPage = () => {\n"
        "    const [password, setPassword] = useState('');\n"
        "    const [showPassword, setShowPassword] = useState(false);\n"
        "    return (\n"
        "        <form onSubmit={() => {}}>\n"
        "            <input type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} />\n"
        "            <button type='button' onClick={() => setShowPassword(!showPassword)}>Toggle</button>\n"
        "        </form>\n"
        "    );\n"
        "};\n"
    )
    patch_obj = FilePatch(
        file_path="src/pages/LoginPage.tsx",
        change_type=ChangeType.MODIFY,
        original_content="export const LoginPage = () => null;\n",
        modified_content=code_with_toggle,
        unified_diff="@@ -1 +1,11 @@\n+...",
        justification="Password toggle implemented",
    )
    is_aligned, report = implementation_validator.validate_requirement_alignment(
        requirement_prompt=requirement,
        patches={"src/pages/LoginPage.tsx": patch_obj},
    )
    assert is_aligned is True
    assert report.get("details", {}).get("password_visibility_state") is True
    assert report.get("details", {}).get("password_type_toggle") is True

    # Code without toggle must fail validation
    code_without_toggle = (
        "export const LoginPage = () => <form onSubmit={() => {}}><input type='password' /></form>;\n"
    )
    patch_bad = FilePatch(
        file_path="src/pages/LoginPage.tsx",
        change_type=ChangeType.MODIFY,
        original_content="export const LoginPage = () => null;\n",
        modified_content=code_without_toggle,
        unified_diff="@@ -1 +1 @@\n+...",
        justification="Missing toggle",
    )
    is_aligned_bad, report_bad = implementation_validator.validate_requirement_alignment(
        requirement_prompt=requirement,
        patches={"src/pages/LoginPage.tsx": patch_bad},
    )
    assert is_aligned_bad is False
    assert any("Password visibility state" in v for v in report_bad.get("violations", []))


# ---------------------------------------------------------------------------
# Test 8: Missing functional tests prevent full functional verification
# ---------------------------------------------------------------------------
def test_missing_functional_tests_prevent_full_functional_verification(tmp_path):
    repo_dir = tmp_path / "react-no-tests"
    repo_dir.mkdir()
    # package.json with no test script
    pkg_json = repo_dir / "package.json"
    pkg_json.write_text('{"name": "react-no-tests", "version": "1.0.0"}', encoding="utf-8")

    res = run_pytest(str(repo_dir))
    assert res["all_passed"] is False
    assert res["total_count"] == 0
    assert res["passed_count"] == 0
    assert "FUNCTIONAL_TESTS_NOT_CONFIGURED" in res.get("raw_stderr", "")
    assert res.get("error") == "FUNCTIONAL_TESTS_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# Test 9: Failed production build prevents successful delivery
# ---------------------------------------------------------------------------
def test_failed_production_build_prevents_successful_delivery(tmp_path):
    repo_dir = tmp_path / "react-build-fail"
    repo_dir.mkdir()
    # package.json with failing build script
    pkg_json = repo_dir / "package.json"
    pkg_json.write_text(
        '{\n'
        '  "name": "react-build-fail",\n'
        '  "scripts": {\n'
        '    "build": "exit 1"\n'
        '  }\n'
        '}',
        encoding="utf-8",
    )

    res = run_pytest(str(repo_dir))
    assert res["all_passed"] is False
    assert res["failed_count"] == 1
    assert "PRODUCTION_BUILD_FAILED" in res.get("error", "")


# ---------------------------------------------------------------------------
# Test 10: HITL approval remains blocked for simulated or unverified patches
# ---------------------------------------------------------------------------
def test_hitl_approval_remains_blocked_for_simulated_or_unverified_patches(clean_bb):
    # 1. Blocked on simulated run
    clean_bb.update_metadata("is_simulated", True)
    patch_obj = FilePatch(
        file_path="src/calculator.py",
        change_type=ChangeType.MODIFY,
        modified_content="class AdvancedCalculator:\n    pass\n",
        unified_diff="@@ -1 +1 @@\n+...",
        justification="Simulated change",
    )
    clean_bb.post_code_proposal(
        CodeChangeProposal(task_id="TSK-01", author_agent="GoogleADK:CoderAgent", patches=[patch_obj])
    )
    clean_bb.post_test_report(
        TestResultReport(total_tests=1, passed=1, failed=0, errors=0, skipped=0, all_passed=True)
    )
    clean_bb.post_security_audit(SecurityAuditReport(passed=True))

    readiness = hitl_gatekeeper.evaluate_readiness()
    assert readiness["can_approve"] is False
    assert any("SIMULATED" in r for r in readiness["rejection_reasons"])

    # 2. Blocked on metadata-only patch
    clean_bb.update_metadata("is_simulated", False)
    meta_patch = FilePatch(
        file_path="src/LoginPage.tsx",
        change_type=ChangeType.MODIFY,
        original_content="export const LoginPage = () => null;\n",
        modified_content="export const LoginPage = () => null;\nexport const devpilotFeature_test = { status: 'implemented_and_verified' };\n",
        unified_diff="@@ -1 +1,2 @@\n+export const devpilotFeature_test = { status: 'implemented_and_verified' };\n",
        justification="Metadata only",
    )
    clean_bb.reset()
    clean_bb.post_code_proposal(
        CodeChangeProposal(task_id="TSK-02", author_agent="GoogleADK:CoderAgent", patches=[meta_patch])
    )
    clean_bb.post_test_report(
        TestResultReport(total_tests=1, passed=1, failed=0, errors=0, skipped=0, all_passed=True)
    )
    clean_bb.post_security_audit(SecurityAuditReport(passed=True))

    readiness_meta = hitl_gatekeeper.evaluate_readiness()
    assert readiness_meta["can_approve"] is False
    assert any("METADATA_ONLY_PATCH" in r for r in readiness_meta["rejection_reasons"])


# ---------------------------------------------------------------------------
# Test 11: Existing Python repository functionality remains intact
# ---------------------------------------------------------------------------
def test_existing_python_repository_functionality_intact():
    # Verify sample_repo calculator tests execute cleanly via MCP test runner
    sample_repo_path = Path("sandbox_workspace/sample_repo").resolve()
    assert sample_repo_path.exists(), "sample_repo workspace missing"

    res = run_pytest(str(sample_repo_path))
    assert res["success"] is True
    assert res["all_passed"] is True
    assert res["passed_count"] >= 5
    assert res["failed_count"] == 0


# ---------------------------------------------------------------------------
# Test 12: Original C1-C4 configurations remain intact
# ---------------------------------------------------------------------------
def test_original_c1_c4_configurations_remain_intact():
    comparator = ArchitectureComparator()
    conditions = comparator.get_c1_c4_conditions_definitions()

    assert len(conditions) == 4
    cond_names = [c["condition"] for c in conditions]
    assert any("C1" in c for c in cond_names)
    assert any("C2" in c for c in cond_names)
    assert any("C3" in c for c in cond_names)
    assert any("C4" in c for c in cond_names)

    # Patterns enum must contain all 3 architectural types
    assert AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A.value in PATTERN_DESCRIPTIONS
    assert AgenticPatternType.SEQUENTIAL_BASELINE.value in PATTERN_DESCRIPTIONS
    assert AgenticPatternType.CRITIC_REFLECTION_LOOP.value in PATTERN_DESCRIPTIONS

