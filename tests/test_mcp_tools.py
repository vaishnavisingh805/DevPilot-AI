"""Unit tests for Phase 4 MCP Tools (Repo Tool & Test Runner)."""

import pytest
from pathlib import Path
from mcp_servers.repo_tool import mcp_repo_client
from mcp_servers.test_runner import mcp_test_client


def test_mcp_create_isolated_sandbox_and_read():
    res = mcp_repo_client.create_sandbox("sample_repo")
    assert res["success"] is True
    assert "run_id" in res
    run_id = res["run_id"]
    sandbox_path = res["sandbox_path"]
    assert Path(sandbox_path).exists()

    # Read existing file from sandbox
    read_res = mcp_repo_client.read_file(run_id, "src/calculator.py")
    assert read_res["success"] is True
    assert "class AdvancedCalculator" in read_res["content"]


def test_mcp_apply_patch_and_diff():
    res = mcp_repo_client.create_sandbox("sample_repo")
    run_id = res["run_id"]

    new_code = (
        '"""Modified calculator."""\n'
        'class AdvancedCalculator:\n'
        '    def add(self, a, b):\n'
        '        return a + b\n'
        '    def power(self, base, exp):\n'
        '        return base ** exp\n'
    )
    patch_res = mcp_repo_client.apply_patch(
        run_id=run_id,
        file_path="src/calculator.py",
        content=new_code,
        justification="Added power method"
    )
    assert patch_res["success"] is True
    assert "diff" in patch_res
    assert len(patch_res["diff"]) > 0


def test_mcp_human_approval_gate_blocks_unauthorized_commit():
    res = mcp_repo_client.create_sandbox("sample_repo")
    run_id = res["run_id"]

    # Attempt commit without human approval
    commit_res = mcp_repo_client.commit_to_main(
        run_id=run_id,
        target_repo="sample_repo",
        human_approved=False
    )
    assert commit_res["success"] is False
    assert "HUMAN_APPROVAL_REQUIRED" in commit_res["error"]


def test_mcp_syntax_and_pytest_execution():
    res = mcp_repo_client.create_sandbox("sample_repo")
    sandbox_path = res["sandbox_path"]

    # Syntax check
    syntax_res = mcp_test_client.check_syntax(sandbox_path)
    assert syntax_res["success"] is True
    assert syntax_res["files_checked"] >= 2

    # Pytest execution
    test_res = mcp_test_client.run_tests(sandbox_path)
    assert test_res["success"] is True
    assert test_res["all_passed"] is True
    assert test_res["passed_count"] == 5

