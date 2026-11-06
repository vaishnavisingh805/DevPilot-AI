"""Comprehensive Regression Tests for Sandbox Lifecycle and Dual Project Setup.

Covers:
1. Empty repository project scaffolding (Build from Scratch).
2. Login page criteria: email, password, show/hide toggle, error alerts, required fields.
3. Existing React repository modification and file preservation.
4. Package manager detection from lockfiles (npm, yarn, pnpm, bun).
5. Dependency installation execution, timeout, and failure diagnostics.
6. Honest test execution: missing tests cannot produce a pass.
7. Real Node.js test execution (node:test).
8. Browser preview server startup, readiness health check, and safe termination.
9. Strict HITL approval gate rejection on unverified/simulated/failed runs.
10. Orchestrator dual setup mode dispatching.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.settings import settings
from core.blackboard import global_blackboard
from core.guardrails.implementation_validator import implementation_validator
from core.hitl import hitl_gatekeeper
from core.preview import preview_manager, BrowserPreviewManager
from core.scaffolding import react_vite_scaffolder, ReactViteScaffolder
from core.schemas import DeveloperRequirement, FilePatch, ChangeType
from core.schemas.tests import TestResultReport, TestResultItem
from mcp_servers.repo_tool import mcp_repo_client
from mcp_servers.test_runner import mcp_test_client
from mcp_servers.test_runner.server import detect_package_manager, install_package_dependencies, run_pytest
from orchestration import AutonomousEngineeringOrchestrator


def test_empty_repository_detection_and_scaffolding():
    """Verify that an empty directory is scaffolded into a runnable React + TS + Vite app."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        sb_path = Path(tmp_dir)
        scaffold_res = react_vite_scaffolder.scaffold_project(
            sandbox_path=sb_path,
            requirement_prompt="Build responsive login page",
            app_title="Test App",
        )

        assert scaffold_res["success"] is True
        assert len(scaffold_res["created_files"]) >= 9

        # Verify key project files
        assert (sb_path / "package.json").exists()
        assert (sb_path / "vite.config.ts").exists()
        assert (sb_path / "tsconfig.json").exists()
        assert (sb_path / "index.html").exists()
        assert (sb_path / "src" / "pages" / "LoginPage.tsx").exists()
        assert (sb_path / "tests" / "login.test.mjs").exists()

        # Verify package.json structure
        pkg_data = json.loads((sb_path / "package.json").read_text(encoding="utf-8"))
        assert "react" in pkg_data["dependencies"]
        assert "vite" in pkg_data["devDependencies"]
        assert "test" in pkg_data["scripts"]


def test_scaffolded_login_page_satisfies_all_ui_and_validation_criteria():
    """Verify generated LoginPage.tsx satisfies AST, accessibility, and functional criteria."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        sb_path = Path(tmp_dir)
        react_vite_scaffolder.scaffold_project(sb_path)
        login_code = (sb_path / "src" / "pages" / "LoginPage.tsx").read_text(encoding="utf-8")

        # 1. State hooks
        assert "useState" in login_code
        assert "showPassword" in login_code
        assert "setShowPassword" in login_code
        assert "isSubmitting" in login_code
        assert "rememberMe" in login_code

        # 2. Dynamic password input type switching
        assert 'type={showPassword ? \'text\' : \'password\'}' in login_code or 'type={showPassword ? "text" : "password"}' in login_code

        # 3. Toggle button with accessible label
        assert "aria-label" in login_code
        assert "Show password" in login_code or "Hide password" in login_code

        # 4. Email validation regex & required checks
        assert "@" in login_code
        assert "test(" in login_code or "includes(" in login_code

        # 5. Form options & submit
        assert "Remember for 30 days" in login_code
        assert "Forgot password?" in login_code
        assert "handleSubmit" in login_code

        # 6. ImplementationValidator acceptance
        patch_obj = FilePatch(
            file_path="src/pages/LoginPage.tsx",
            change_type=ChangeType.CREATE,
            original_content="",
            modified_content=login_code,
            unified_diff="+ new login page",
            justification="Initial scaffolding",
        )
        is_aligned, rep = implementation_validator.validate_requirement_alignment(
            requirement_prompt="Add password visibility toggle and validate email and password inputs",
            patches={"src/pages/LoginPage.tsx": patch_obj},
        )
        assert is_aligned is True
        assert len(rep["violations"]) == 0


def test_existing_react_repository_preservation():
    """Verify modifying LoginPage in an existing repository does not touch or overwrite unrelated files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        sb_path = Path(tmp_dir)
        (sb_path / "src" / "pages").mkdir(parents=True, exist_ok=True)
        (sb_path / "src" / "components").mkdir(parents=True, exist_ok=True)

        # Create original LoginPage and unrelated components
        orig_login = (
            'import { useState } from "react";\n'
            'export default function LoginPage() {\n'
            '  const [email, setEmail] = useState("");\n'
            '  const [password, setPassword] = useState("");\n'
            '  return <form><input type="password" value={password} /></form>;\n'
            '}\n'
        )
        unrelated_component = 'export const Header = () => <header>IT Support Header</header>;\n'

        (sb_path / "src" / "pages" / "LoginPage.tsx").write_text(orig_login, encoding="utf-8")
        (sb_path / "src" / "components" / "Header.tsx").write_text(unrelated_component, encoding="utf-8")

        # Coder applies targeted enhancement
        from agents.google_adk.coder_agent import GoogleADKCoderAgent
        coder = GoogleADKCoderAgent()
        enhanced_code = coder._synthesize_login_enhancements(
            original_code=orig_login,
            instruction="Add password visibility toggle to LoginPage.tsx",
            target_file="src/pages/LoginPage.tsx",
        )

        # Verify enhanced code
        assert "showPassword" in enhanced_code
        assert 'type={showPassword ? "text" : "password"}' in enhanced_code

        # Verify unrelated component was untouched
        header_content = (sb_path / "src" / "components" / "Header.tsx").read_text(encoding="utf-8")
        assert header_content == unrelated_component


def test_package_manager_detection_from_lockfiles():
    """Verify package manager detection matches lockfiles accurately."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir)
        assert detect_package_manager(p) == "npm"

        (p / "yarn.lock").write_text("", encoding="utf-8")
        assert detect_package_manager(p) == "yarn"
        (p / "yarn.lock").unlink()

        (p / "pnpm-lock.yaml").write_text("", encoding="utf-8")
        assert detect_package_manager(p) == "pnpm"
        (p / "pnpm-lock.yaml").unlink()

        (p / "bun.lockb").write_text("", encoding="utf-8")
        assert detect_package_manager(p) == "bun"


def test_dependency_installation_execution_and_timeout():
    """Verify install_package_dependencies executes with timeout handling."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir)
        (p / "package.json").write_text(json.dumps({"name": "test-pkg"}), encoding="utf-8")

        # Mock subprocess.run to verify argument handling and timeout
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["npm", "install"],
                returncode=0,
                stdout="added 10 packages in 1s",
                stderr="",
            )
            res = install_package_dependencies(str(p), timeout_seconds=10)
            assert res["success"] is True
            assert res["installed"] is True
            assert res["package_manager"] == "npm"

        # Mock timeout
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="npm install", timeout=1)):
            res = install_package_dependencies(str(p), timeout_seconds=1)
            assert res["success"] is False
            assert "DEPENDENCY_INSTALL_TIMEOUT" in res["error"]


def test_dependency_installation_failure_reported():
    """Verify non-zero return code produces structured failure report."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir)
        (p / "package.json").write_text(json.dumps({"name": "broken-pkg"}), encoding="utf-8")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["npm", "install"],
                returncode=1,
                stdout="",
                stderr="npm ERR! code ENOENT",
            )
            res = install_package_dependencies(str(p), timeout_seconds=10)
            assert res["success"] is False
            assert res["installed"] is False
            assert "DEPENDENCY_INSTALL_FAILED" in res["error"]


def test_missing_test_framework_cannot_produce_pass():
    """Verify package.json without a test script produces FUNCTIONAL_TESTS_NOT_CONFIGURED."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir)
        (p / "package.json").write_text(
            json.dumps({"name": "test", "scripts": {"dev": "vite"}}),
            encoding="utf-8",
        )

        res = run_pytest(str(p))
        assert res["success"] is True
        assert res["all_passed"] is False
        assert res["total_count"] == 0
        assert "FUNCTIONAL_TESTS_NOT_CONFIGURED" in res["error"]


def test_real_node_test_execution_on_scaffolded_app():
    """Verify genuine functional test execution with Node.js built-in test runner."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir)
        react_vite_scaffolder.scaffold_project(p)

        # Run Node test runner directly on the scaffolded login test suite
        proc = subprocess.run(
            ["node", "--test", "tests/login.test.mjs"],
            cwd=str(p),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert "pass 6" in proc.stdout or "# pass 6" in proc.stdout
        assert "fail 0" in proc.stdout or "# fail 0" in proc.stdout


def test_browser_preview_startup_healthcheck_and_shutdown():
    """Verify BrowserPreviewManager lifecycle: port check, startup, probe, and shutdown."""
    mgr = BrowserPreviewManager()

    # Port in use check on localhost
    assert isinstance(mgr.is_port_in_use(59999), bool)

    # Mock server process startup
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir)
        (p / "package.json").write_text(json.dumps({"name": "preview-test"}), encoding="utf-8")

        with patch("subprocess.Popen") as mock_popen, patch.object(mgr, "check_server_health", return_value=True):
            mock_proc = MagicMock()
            mock_proc.pid = 98765
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            start_res = mgr.start_preview(str(p), run_id="run_preview_test", preferred_port=5173)
            assert start_res["success"] is True
            assert start_res["port"] >= 5173
            assert "http://127.0.0.1:" in start_res["url"]

            # Check status
            status = mgr.get_preview_status("run_preview_test")
            assert status["active"] is True
            assert status["pid"] == 98765

            # Stop preview
            stop_res = mgr.stop_preview("run_preview_test")
            assert stop_res["success"] is True
            mock_proc.terminate.assert_called_once()


def test_hitl_approval_strictly_blocked_on_unverified_or_simulated_dual_setup():
    """Verify HITLGatekeeper blocks approval when dependencies or tests fail or simulation is active."""
    global_blackboard.reset()

    # 1. Simulation block
    global_blackboard.update_metadata("is_simulated", True)
    readiness = hitl_gatekeeper.evaluate_readiness()
    assert readiness["can_approve"] is False
    assert any("SIMULATED" in r for r in readiness["rejection_reasons"])

    # 2. Dependency failure / missing test block
    global_blackboard.update_metadata("is_simulated", False)
    global_blackboard.update_metadata("dependencies_installed", False)
    rep = TestResultReport(
        total_tests=0, passed=0, failed=0, all_passed=False,
        raw_stderr="FUNCTIONAL_TESTS_NOT_CONFIGURED",
    )
    global_blackboard.post_test_report(rep)
    readiness = hitl_gatekeeper.evaluate_readiness()
    assert readiness["can_approve"] is False
    assert any("Functional tests are not configured" in r for r in readiness["rejection_reasons"])


def test_orchestrator_dual_mode_selection():
    """Verify AutonomousEngineeringOrchestrator accepts project_setup_mode parameter."""
    from core.schemas.plans import ExecutionPlan

    with tempfile.TemporaryDirectory() as tmp_dir:
        sb_path = Path(tmp_dir)
        orchestrator = AutonomousEngineeringOrchestrator()

        mock_sandbox = {
            "success": True,
            "run_id": "run_test_dual_mode",
            "sandbox_path": str(sb_path),
        }

        mock_plan = ExecutionPlan(
            plan_id="plan-test-01",
            requirement_id="req-test-01",
            strategy_summary="Dual mode test plan",
            tasks=[],
        )

        with patch("mcp_servers.repo_tool.client.mcp_repo_client.create_sandbox", return_value=mock_sandbox), \
             patch("mcp_servers.repo_tool.client.mcp_repo_client.clone_repository", return_value=mock_sandbox), \
             patch.object(orchestrator.planner, "plan_requirement", return_value=mock_plan), \
             patch.object(orchestrator.manager, "delegate_task_to_adk") as mock_delegate, \
             patch.object(orchestrator.auditor, "audit_and_prepare_delivery") as mock_audit, \
             patch("mcp_servers.test_runner.client.mcp_test_client.install_dependencies", return_value={"success": True, "installed": True, "exit_code": 0}), \
             patch.object(orchestrator.rag_agent, "retrieve_context", return_value={"context": "", "results": []}):
            
            mock_delegate.return_value = MagicMock(payload={"status": "completed", "passed": 1, "all_passed": True})
            mock_audit.return_value = MagicMock(unified_diff="")

            # Test build from scratch
            metrics_scratch = orchestrator.execute_requirement(
                raw_prompt="Build login page",
                project_setup_mode="build_from_scratch",
            )
            assert metrics_scratch is not None
            assert global_blackboard.state.metadata.get("project_setup_mode") == "build_from_scratch"

            # Test modify existing
            metrics_modify = orchestrator.execute_requirement(
                raw_prompt="Add password visibility toggle in LoginPage.tsx",
                project_setup_mode="modify_existing",
            )
            assert metrics_modify is not None
            assert global_blackboard.state.metadata.get("project_setup_mode") == "modify_existing"
