"""Unit and integration tests for GitHub Authentication, Git Push Guardrails, and Pull Request Publishing."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.git.git_manager import (
    git_manager,
    extract_github_owner_repo,
    sanitize_error_message,
)
from core.github.github_client import GitHubClient
from core.github.pr_publisher import PRPublisher
from core.blackboard import global_blackboard
from evaluation.experiment_db import ExperimentStorage


# =============================================================================
# 1. GIT MANAGER & URL / PUSH GUARDRAIL TESTS
# =============================================================================

def test_extract_github_owner_repo():
    res1 = extract_github_owner_repo("https://github.com/octocat/Hello-World.git")
    assert res1 == ("octocat", "Hello-World")

    res2 = extract_github_owner_repo("https://github.com/google/gemini-cli/")
    assert res2 == ("google", "gemini-cli")

    assert extract_github_owner_repo("https://gitlab.com/foo/bar") is None
    assert extract_github_owner_repo("invalid-string") is None
    assert extract_github_owner_repo("") is None


def test_push_branch_rejects_non_agentic_branches(tmp_path):
    # Attempting to push 'main', 'master', or 'feature/x' must be immediately blocked
    res = git_manager.push_branch(str(tmp_path), branch_name="main")
    assert res["success"] is False
    assert "Security Alert: Push blocked" in res["error"]

    res_feat = git_manager.push_branch(str(tmp_path), branch_name="feature-user-auth")
    assert res_feat["success"] is False
    assert "Security Alert: Push blocked" in res_feat["error"]


def test_push_branch_credential_sanitization():
    raw = "fatal: Authentication failed for 'https://ghp_secretToken12345@github.com/owner/repo.git'"
    sanitized = sanitize_error_message(raw)
    assert "ghp_secretToken12345" not in sanitized
    assert "***REDACTED***" in sanitized


def test_push_branch_success_mock(tmp_path):
    (tmp_path / ".git").mkdir()

    with patch.object(git_manager, "_run_git", return_value=(0, "Everything up-to-date", "")):
        res = git_manager.push_branch(
            repo_dir=tmp_path,
            branch_name="agentic/task-123-run-456",
            remote_name="origin",
            auth_token="ghp_mocktesttoken123456",
        )
        assert res["success"] is True
        assert res["branch"] == "agentic/task-123-run-456"
        assert res["remote"] == "origin"


# =============================================================================
# 2. GITHUB REST API CLIENT TESTS
# =============================================================================

def test_github_client_validate_token_missing():
    client = GitHubClient(token="")
    res = client.validate_token()
    assert res["valid"] is False
    assert "token" in res["error"].lower()


@patch("requests.get")
def test_github_client_validate_token_success(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"login": "testuser", "id": 12345, "name": "Test User"},
        headers={"X-OAuth-Scopes": "repo, read:org"},
    )

    client = GitHubClient(token="ghp_test123")
    res = client.validate_token()
    assert res["valid"] is True
    assert res["login"] == "testuser"
    assert "repo" in res["scopes"]


@patch("requests.get")
def test_github_client_validate_token_unauthorized(mock_get):
    mock_get.return_value = MagicMock(
        status_code=401,
        json=lambda: {"message": "Bad credentials"},
        text="Bad credentials",
    )

    client = GitHubClient(token="ghp_invalid")
    res = client.validate_token()
    assert res["valid"] is False
    assert res["status_code"] == 401
    assert "Bad credentials" in res["error"] or "Authentication failed" in res["error"]


@patch("requests.get")
def test_github_client_check_repo_permissions(mock_get):
    client = GitHubClient(token="ghp_test123")

    # Has push permission
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"name": "test-repo", "permissions": {"push": True, "pull": True}, "private": False},
    )
    perm_ok = client.check_repo_permissions("testowner", "test-repo")
    assert perm_ok["has_push_access"] is True
    assert perm_ok["is_private"] is False
    assert perm_ok["exists"] is True

    # Read-only permission
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"name": "test-repo", "permissions": {"push": False, "pull": True}, "private": False},
    )
    perm_no = client.check_repo_permissions("testowner", "test-repo")
    assert perm_no["has_push_access"] is False
    assert perm_no["exists"] is True

    # 404 Not Found
    mock_get.return_value = MagicMock(status_code=404, json=lambda: {"message": "Not Found"}, text="Not Found")
    perm_404 = client.check_repo_permissions("testowner", "missing-repo")
    assert perm_404["has_push_access"] is False
    assert perm_404["exists"] is False
    assert perm_404["status_code"] == 404


@patch("requests.post")
def test_github_client_create_pull_request(mock_post):
    mock_post.return_value = MagicMock(
        status_code=201,
        json=lambda: {
            "number": 42,
            "html_url": "https://github.com/testowner/test-repo/pull/42",
            "state": "open",
            "title": "Autonomous PR",
        },
    )

    client = GitHubClient(token="ghp_test123")
    res = client.create_pull_request(
        owner="testowner",
        repo="test-repo",
        title="Autonomous PR",
        head="agentic/task-1-run-1",
        base="main",
        body="PR Description",
    )
    assert res["success"] is True
    assert res["pr_number"] == 42
    assert res["pr_url"] == "https://github.com/testowner/test-repo/pull/42"


@patch("requests.post")
def test_github_client_create_pull_request_validation_failure(mock_post):
    mock_post.return_value = MagicMock(
        status_code=422,
        json=lambda: {"message": "Validation Failed", "errors": [{"message": "A pull request already exists."}]},
        text="A pull request already exists.",
    )

    client = GitHubClient(token="ghp_test123")
    res = client.create_pull_request(
        owner="testowner",
        repo="test-repo",
        title="Duplicate PR",
        head="agentic/task-1-run-1",
        base="main",
        body="PR Description",
    )
    assert res["success"] is False
    assert res["status_code"] == 422
    assert "already exists" in res["error"]


# =============================================================================
# 3. PR PUBLISHER & HITL GATEKEEPER TESTS
# =============================================================================

def test_pr_publisher_generates_markdown_body():
    publisher = PRPublisher()
    body = publisher.generate_pr_body(
        task_id="TASK-01",
        requirement_prompt="Implement standard deviation method",
        diff_summary={"diff": "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1,2 @@\n+# added", "changed_files_count": 1},
        approver="Staff Engineer",
        approval_notes="All tests pass cleanly",
    )

    assert "TASK-01" in body
    assert "Implement standard deviation method" in body
    assert "Human-In-The-Loop Sign-off" in body
    assert "Staff Engineer" in body
    assert "Automated Pull Request" in body


def test_pr_publisher_blocks_unapproved_pr(tmp_path):
    global_blackboard.set_human_approval("pending")  # NOT approved

    publisher = PRPublisher()
    res = publisher.publish_pull_request(
        run_id="run-test-01",
        sandbox_path=tmp_path,
        repo_url="https://github.com/testowner/test-repo",
        base_branch="main",
        task_id="TASK-01",
        requirement_prompt="Add feature",
    )

    assert res["status"] == "BLOCKED_HITL"
    assert res["success"] is False
    assert "HUMAN_APPROVAL_REQUIRED" in res["error"]


def test_pr_publisher_rejects_non_agentic_branch(tmp_path):
    global_blackboard.set_human_approval("approved")

    publisher = PRPublisher()
    with patch.object(git_manager, "get_current_branch", return_value="main"):
        res = publisher.publish_pull_request(
            run_id="run-test-02",
            sandbox_path=tmp_path,
            repo_url="https://github.com/testowner/test-repo",
            base_branch="main",
            task_id="TASK-01",
            requirement_prompt="Add feature",
        )

        assert res["status"] == "BLOCKED_SECURITY"
        assert res["success"] is False
        assert "Only dedicated 'agentic/*'" in res["error"]


def test_pr_publisher_rejects_empty_diff(tmp_path):
    global_blackboard.set_human_approval("approved")

    publisher = PRPublisher()
    with patch.object(git_manager, "get_current_branch", return_value="agentic/task-01-run-1"):
        with patch.object(git_manager, "get_git_diff", return_value={"has_diff": False, "diff": ""}):
            res = publisher.publish_pull_request(
                run_id="run-test-03",
                sandbox_path=tmp_path,
                repo_url="https://github.com/testowner/test-repo",
                base_branch="main",
                task_id="TASK-01",
                requirement_prompt="Add feature",
            )

            assert res["status"] == "EMPTY_DIFF"
            assert res["success"] is False
            assert "Diff Verification Failed" in res["error"]


def test_pr_publisher_success_flow(tmp_path):
    global_blackboard.set_human_approval("approved")

    mock_client = MagicMock(spec=GitHubClient)
    mock_client.check_repo_permissions.return_value = {"exists": True, "has_push_access": True, "is_private": False}
    mock_client.create_pull_request.return_value = {
        "success": True,
        "pr_number": 105,
        "pr_url": "https://github.com/testowner/test-repo/pull/105",
    }

    publisher = PRPublisher(client=mock_client)

    with patch.object(git_manager, "get_current_branch", return_value="agentic/task-01-run-1"):
        with patch.object(git_manager, "get_git_diff", return_value={"has_diff": True, "diff": "+ def calc(): pass", "changed_files_count": 1}):
            with patch.object(git_manager, "push_branch", return_value={"success": True, "branch": "agentic/task-01-run-1"}):
                res = publisher.publish_pull_request(
                    run_id="run-test-success",
                    sandbox_path=tmp_path,
                    repo_url="https://github.com/testowner/test-repo",
                    base_branch="main",
                    task_id="TASK-01",
                    requirement_prompt="Add feature",
                    auth_token="ghp_mockvalidtoken123",
                )

                assert res["status"] == "PUBLISHED"
                assert res["success"] is True
                assert res["pr_number"] == 105
                assert res["pr_url"] == "https://github.com/testowner/test-repo/pull/105"

                # Check Blackboard metadata updated
                pr_meta = global_blackboard.state.metadata.get("github_pr")
                assert pr_meta is not None
                assert pr_meta["pr_number"] == 105
                assert pr_meta["repo_url"] == "https://github.com/testowner/test-repo"


# =============================================================================
# 4. SQLITE PULL REQUEST STORAGE TESTS
# =============================================================================

def test_experiment_storage_pull_requests(tmp_path):
    db_file = tmp_path / "experiments_test.db"
    storage = ExperimentStorage(db_path=str(db_file))

    # Verify initially empty
    initial_prs = storage.get_pull_requests()
    assert len(initial_prs) == 0

    # Record a pull request
    storage.record_pull_request(
        run_id="run-sq-01",
        pr_number=77,
        pr_url="https://github.com/testowner/test-repo/pull/77",
        repo_url="https://github.com/testowner/test-repo",
        base_branch="main",
        head_branch="agentic/task-01-run-sq-01",
        title="feat(TASK-01): Test PR Storage",
        metadata={"approver": "Lead QA"},
    )

    prs = storage.get_pull_requests()
    assert len(prs) == 1
    assert prs[0]["pr_number"] == 77
    assert prs[0]["run_id"] == "run-sq-01"
    assert prs[0]["repo_url"] == "https://github.com/testowner/test-repo"
    assert prs[0]["head_branch"] == "agentic/task-01-run-sq-01"

    # Filter by run_id
    filtered = storage.get_pull_requests(run_id="run-sq-01")
    assert len(filtered) == 1

    none_filtered = storage.get_pull_requests(run_id="non-existent")
    assert len(none_filtered) == 0
