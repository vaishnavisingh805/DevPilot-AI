"""Unit and integration tests for Git Tooling and MCP Repository Server."""

import subprocess
from pathlib import Path
import pytest

from core.git.git_manager import (
    git_manager,
    validate_github_url,
    sanitize_branch_name,
    sanitize_error_message,
)
from mcp_servers.repo_tool.server import _resolve_sandbox_path
from mcp_servers.repo_tool.client import mcp_repo_client


def test_validate_github_url_valid_cases():
    valid_urls = [
        "https://github.com/torvalds/linux",
        "https://github.com/pallets/flask.git",
        "https://github.com/psf/requests/",
        "https://github.com/google/gemini-cli.git/",
    ]
    for url in valid_urls:
        is_valid, norm = validate_github_url(url)
        assert is_valid is True, f"Failed for valid url: {url}"
        assert norm.startswith("https://github.com/")


def test_validate_github_url_rejections_and_injections():
    invalid_cases = [
        "",
        "http://github.com/user/repo",  # HTTP rejected
        "https://gitlab.com/user/repo",  # non-github
        "https://github.com/user/repo; rm -rf /",  # command injection
        "https://github.com/user/repo && echo pwned",
        "https://github.com/user/repo`whoami`",
        "https://github.com/user/repo$(id)",
        "https://github.com/user/repo\ncat /etc/passwd",
        "ftp://github.com/user/repo",
        "git@github.com:user/repo.git",
    ]
    for url in invalid_cases:
        is_valid, err = validate_github_url(url)
        assert is_valid is False, f"Should reject invalid url: {url}"
        assert len(err) > 0


def test_sanitize_branch_name():
    branch = sanitize_branch_name("TASK-01: Add Feature!", "RUN-861653bb/part1")
    assert branch.startswith("agentic/")
    assert "!" not in branch
    assert ":" not in branch
    assert "/" not in branch[len("agentic/"):]
    assert branch == "agentic/TASK-01-Add-Feature-RUN-861653bb-part1"


def test_credential_sanitization():
    raw_error = "Authentication failed for https://ghp_123456789012345678901234567890123456@github.com/org/repo"
    sanitized = sanitize_error_message(raw_error)
    assert "ghp_1234567890" not in sanitized
    assert "***REDACTED***" in sanitized


def test_path_traversal_prevention():
    with pytest.raises(PermissionError):
        _resolve_sandbox_path("../../etc/passwd")

    with pytest.raises(PermissionError):
        _resolve_sandbox_path("run_test/../../../windows/system32")


@pytest.fixture
def temp_git_repo(tmp_path: Path):
    """Creates a deterministic local Git repository for offline tests."""
    repo_dir = tmp_path / "upstream_repo"
    repo_dir.mkdir(parents=True)

    # Initialize Git
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=str(repo_dir), check=True)

    # Add initial file
    calc_file = repo_dir / "calculator.py"
    calc_file.write_text("class Calc:\n    def add(self, a, b):\n        return a + b\n", encoding="utf-8")
    subprocess.run(["git", "add", "calculator.py"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True)

    return repo_dir


def test_git_operations_in_sandbox(temp_git_repo: Path, tmp_path: Path):
    """Verifies clone, branch creation, status, and diff on local repo."""
    sandbox_dir = tmp_path / "sandbox_run_1"

    # 1. Clone local repo using git_manager
    # We bypass validate_github_url for local file:// clone in test
    code, stdout, stderr = git_manager._run_git(["clone", str(temp_git_repo), str(sandbox_dir)])
    assert code == 0, f"Clone failed: {stderr}"
    assert (sandbox_dir / ".git").exists()
    assert (sandbox_dir / "calculator.py").exists()

    # 2. Verify clean initial status
    status = git_manager.get_git_status(sandbox_dir)
    assert status["success"] is True
    assert status["is_clean"] is True
    assert status["total_changes"] == 0

    # 3. Create isolated branch
    branch_res = git_manager.create_isolated_branch(
        repo_dir=sandbox_dir,
        task_id="TSK-01-MATH",
        run_id="RUN-TEST-001",
    )
    assert branch_res["success"] is True
    assert branch_res["branch_name"] == "agentic/TSK-01-MATH-RUN-TEST-001"
    assert git_manager.get_current_branch(sandbox_dir) == "agentic/TSK-01-MATH-RUN-TEST-001"

    # 4. Modify existing file
    calc_file = sandbox_dir / "calculator.py"
    calc_file.write_text(
        "class Calc:\n    def add(self, a, b):\n        return a + b\n\n    def multiply(self, a, b):\n        return a * b\n",
        encoding="utf-8",
    )

    # 5. Add new file
    test_file = sandbox_dir / "test_calc.py"
    test_file.write_text("def test_add(): assert Calc().add(1, 2) == 3\n", encoding="utf-8")

    # 6. Check updated git status
    status = git_manager.get_git_status(sandbox_dir)
    assert status["success"] is True
    assert status["is_clean"] is False
    assert "calculator.py" in status["modified"]
    assert "test_calc.py" in status["untracked"]

    # 7. Check git diff
    diff_res = git_manager.get_git_diff(sandbox_dir)
    assert diff_res["success"] is True
    assert diff_res["has_diff"] is True
    assert "+    def multiply(self, a, b):" in diff_res["diff"]

    # 8. Stage files and verify staged diff
    git_manager.stage_file(sandbox_dir, "calculator.py")
    staged_diff = git_manager.get_git_diff(sandbox_dir, staged=True)
    assert staged_diff["success"] is True
    assert "+    def multiply(self, a, b):" in staged_diff["diff"]

    # 9. Commit changes in sandbox
    commit_res = git_manager.commit_changes(
        sandbox_dir,
        commit_message="Add multiplication method",
    )
    assert commit_res["success"] is True
    assert len(commit_res["commit_sha"]) == 40

    # Verify parent upstream repo was NOT affected
    upstream_calc = (temp_git_repo / "calculator.py").read_text(encoding="utf-8")
    assert "multiply" not in upstream_calc

