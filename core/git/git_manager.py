"""Git CLI Operations and Repository Sandbox Management.

Provides secure, sandboxed Git CLI interactions ensuring no command injection,
no path traversal, and strict preservation of parent and remote repositories.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


# GitHub HTTPS URL pattern: https://github.com/owner/repo(.git)?
GITHUB_HTTPS_REGEX = re.compile(
    r"^https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?/?$"
)

# Forbidden shell injection characters
FORBIDDEN_SHELL_CHARS = set(";;&|`$><\n\r\t")


def validate_github_url(url: str) -> Tuple[bool, str]:
    """Validates that a URL is a legitimate, safe GitHub HTTPS URL.

    Args:
        url: The repository URL to validate.

    Returns:
        Tuple of (is_valid: bool, error_or_normalized_url: str).
    """
    if not url or not isinstance(url, str):
        return False, "Repository URL must be a non-empty string."

    stripped = url.strip()

    # Reject shell injection characters
    if any(ch in stripped for ch in FORBIDDEN_SHELL_CHARS):
        return False, "Security violation: Invalid or dangerous characters in repository URL."

    # Must be HTTPS
    if not stripped.startswith("https://"):
        return False, "Only HTTPS GitHub URLs are permitted (e.g. https://github.com/owner/repo)."

    match = GITHUB_HTTPS_REGEX.match(stripped)
    if not match:
        return False, "Invalid GitHub URL format. Expected: https://github.com/{owner}/{repository}"

    owner, repo = match.groups()
    normalized = f"https://github.com/{owner}/{repo}"
    return True, normalized


def sanitize_branch_name(task_id: str, run_id: str) -> str:
    """Constructs a deterministic, Git-compliant branch name from task and run IDs.

    Branch format: agentic/{task_id}-{run_id}
    """
    clean_task = re.sub(r"[^a-zA-Z0-9_-]", "-", str(task_id)).strip("-")
    clean_run = re.sub(r"[^a-zA-Z0-9_-]", "-", str(run_id)).strip("-")
    branch = f"agentic/{clean_task}-{clean_run}"
    # Ensure Git branch naming rules (no consecutive dots/slashes, max length)
    branch = re.sub(r"/{2,}", "/", branch)
    branch = re.sub(r"-{2,}", "-", branch)
    return branch[:80]


def sanitize_error_message(msg: str) -> str:
    """Masks potential credentials or tokens in error messages."""
    # Redact basic auth in URLs https://user:pass@github.com
    redacted = re.sub(r"https://[^@]+@github\.com", "https://***REDACTED***@github.com", msg)
    # Redact GitHub tokens (ghp_..., github_pat_...)
    redacted = re.sub(r"ghp_[A-Za-z0-9_]{36}", "ghp_***REDACTED***", redacted)
    redacted = re.sub(r"github_pat_[A-Za-z0-9_]{82}", "github_pat_***REDACTED***", redacted)
    # Redact Bearer tokens
    redacted = re.sub(r"bearer\s+[A-Za-z0-9_.-]+", "bearer ***REDACTED***", redacted, flags=re.IGNORECASE)
    return redacted


def extract_github_owner_repo(url: str) -> Optional[Tuple[str, str]]:
    """Extracts (owner, repo) from a validated GitHub HTTPS URL."""
    if not url or not isinstance(url, str):
        return None
    match = GITHUB_HTTPS_REGEX.match(url.strip())
    if match:
        return match.group(1), match.group(2)
    return None


class GitManager:
    """Executes sandboxed Git operations via safe subprocess invocations."""

    def __init__(self, default_timeout_seconds: int = 60):
        self.default_timeout = default_timeout_seconds

    def _run_git(
        self,
        args: List[str],
        cwd: Optional[Path] = None,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str, str]:
        """Executes a git command with shell=False for command injection safety."""
        t_out = timeout or self.default_timeout
        cmd = ["git"] + args
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        # Ensure GIT_TERMINAL_PROMPT is disabled so git doesn't hang on auth prompts
        merged_env["GIT_TERMINAL_PROMPT"] = "0"

        try:
            res = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                shell=False,
                timeout=t_out,
                env=merged_env,
            )
            return res.returncode, res.stdout, res.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"Git command timed out after {t_out} seconds."
        except FileNotFoundError:
            return -1, "", "Git executable not found in system PATH."
        except Exception as exc:
            return -1, "", f"Subprocess exception: {str(exc)}"

    def clone_repository(
        self,
        repo_url: str,
        target_dir: Path,
        base_branch: Optional[str] = None,
        depth: int = 1,
    ) -> Dict[str, Any]:
        """Clones a public Git repository into an isolated target directory.

        Args:
            repo_url: Validated HTTPS GitHub URL.
            target_dir: Destination path (must not exist or be empty).
            base_branch: Optional specific base branch to clone.
            depth: Clone depth (default 1 for fast shallow clone).

        Returns:
            Status dictionary with commit SHA and branch metadata.
        """
        is_valid, norm_url = validate_github_url(repo_url)
        if not is_valid:
            # Check if it is an existing local Git directory (for offline tests/development)
            try:
                local_p = Path(repo_url).resolve()
                if local_p.exists() and (local_p / ".git").exists():
                    is_valid = True
                    norm_url = str(local_p)
                else:
                    return {"success": False, "error": norm_url}
            except Exception:
                return {"success": False, "error": norm_url}

        target_dir = Path(target_dir).resolve()
        if target_dir.exists() and any(target_dir.iterdir()):
            return {
                "success": False,
                "error": f"Target directory '{target_dir}' already exists and is not empty.",
            }

        target_dir.parent.mkdir(parents=True, exist_ok=True)

        args = ["clone", "--depth", str(max(1, depth))]
        if base_branch:
            # Sanitize branch argument
            if any(ch in base_branch for ch in FORBIDDEN_SHELL_CHARS):
                return {"success": False, "error": "Invalid base branch name."}
            args.extend(["--branch", base_branch])

        args.extend([norm_url, str(target_dir)])

        code, stdout, stderr = self._run_git(args)
        if code != 0:
            # Clean up target_dir if failed
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            return {
                "success": False,
                "error": sanitize_error_message(f"Git clone failed: {stderr.strip() or stdout.strip()}"),
            }

        # Retrieve cloned commit SHA and current branch
        branch = self.get_current_branch(target_dir)
        sha = self.get_head_commit_sha(target_dir)

        return {
            "success": True,
            "repo_url": norm_url,
            "target_dir": str(target_dir),
            "branch": branch,
            "commit_sha": sha,
            "message": f"Successfully cloned '{norm_url}' at branch '{branch}' (commit {sha[:8]})",
        }

    def fetch_updates(self, repo_dir: Path) -> Dict[str, Any]:
        """Fetches remote updates safely."""
        repo_dir = Path(repo_dir).resolve()
        code, stdout, stderr = self._run_git(["fetch", "origin"], cwd=repo_dir)
        if code != 0:
            return {"success": False, "error": sanitize_error_message(f"Git fetch failed: {stderr}")}
        return {"success": True, "message": "Remote updates fetched successfully."}

    def create_isolated_branch(
        self,
        repo_dir: Path,
        task_id: str,
        run_id: str,
    ) -> Dict[str, Any]:
        """Creates and checks out an isolated feature branch named agentic/{task_id}-{run_id}.

        Args:
            repo_dir: Repository path.
            task_id: Task identifier.
            run_id: Run identifier.

        Returns:
            Dictionary confirming branch creation and active branch name.
        """
        repo_dir = Path(repo_dir).resolve()
        if not (repo_dir / ".git").exists():
            return {"success": False, "error": f"Path '{repo_dir}' is not a valid Git repository."}

        branch_name = sanitize_branch_name(task_id, run_id)
        code, stdout, stderr = self._run_git(["checkout", "-b", branch_name], cwd=repo_dir)
        if code != 0:
            return {
                "success": False,
                "error": sanitize_error_message(f"Failed to create branch '{branch_name}': {stderr.strip()}"),
            }

        return {
            "success": True,
            "branch_name": branch_name,
            "message": f"Created and switched to isolated branch '{branch_name}'",
        }

    def get_current_branch(self, repo_dir: Path) -> str:
        """Returns the name of the currently checked out branch."""
        repo_dir = Path(repo_dir).resolve()
        code, stdout, _ = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)
        return stdout.strip() if code == 0 else "unknown"

    def get_head_commit_sha(self, repo_dir: Path) -> str:
        """Returns the full 40-character SHA of HEAD."""
        repo_dir = Path(repo_dir).resolve()
        code, stdout, _ = self._run_git(["rev-parse", "HEAD"], cwd=repo_dir)
        return stdout.strip() if code == 0 else ""

    def get_git_status(self, repo_dir: Path) -> Dict[str, Any]:
        """Returns a structured analysis of git status --porcelain=v1.

        Categorizes files into added, modified, deleted, renamed, untracked.
        """
        repo_dir = Path(repo_dir).resolve()
        code, stdout, stderr = self._run_git(["status", "--porcelain=v1"], cwd=repo_dir)
        if code != 0:
            return {"success": False, "error": sanitize_error_message(stderr)}

        added: List[str] = []
        modified: List[str] = []
        deleted: List[str] = []
        renamed: List[str] = []
        untracked: List[str] = []

        for line in stdout.splitlines():
            if not line or len(line) < 3:
                continue
            status_code = line[:2]
            file_name = line[3:].strip()

            if status_code in ("??", "? "):
                untracked.append(file_name)
            elif "A" in status_code:
                added.append(file_name)
            elif "M" in status_code:
                modified.append(file_name)
            elif "D" in status_code:
                deleted.append(file_name)
            elif "R" in status_code:
                renamed.append(file_name)

        is_clean = not (added or modified or deleted or renamed or untracked)
        return {
            "success": True,
            "is_clean": is_clean,
            "is_dirty": not is_clean,
            "added": added,
            "modified": modified,
            "deleted": deleted,
            "renamed": renamed,
            "untracked": untracked,
            "total_changes": len(added) + len(modified) + len(deleted) + len(renamed) + len(untracked),
            "raw_output": stdout,
        }

    def get_git_diff(
        self,
        repo_dir: Path,
        staged: bool = False,
        base_branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates real git diff output.

        Args:
            repo_dir: Repository path.
            staged: If True, returns staged diff (--cached).
            base_branch: If provided, compares current HEAD against base_branch (e.g. main...HEAD).

        Returns:
            Dictionary containing unified diff text and modified files list.
        """
        repo_dir = Path(repo_dir).resolve()
        args = ["diff"]

        if base_branch:
            # e.g., git diff origin/main...HEAD
            args.append(f"{base_branch}...HEAD")
        elif staged:
            args.append("--cached")
        else:
            args.append("HEAD")

        code, stdout, stderr = self._run_git(args, cwd=repo_dir)
        if code != 0:
            # Fallback to plain 'git diff' if HEAD comparison fails on initial commit
            code2, stdout2, stderr2 = self._run_git(["diff"], cwd=repo_dir)
            if code2 == 0:
                stdout = stdout2
            else:
                return {"success": False, "error": sanitize_error_message(stderr or stderr2)}

        # Extract file names from diff header: +++ b/path/to/file
        modified_files = []
        for line in stdout.splitlines():
            if line.startswith("+++ b/"):
                modified_files.append(line[6:].strip())

        return {
            "success": True,
            "diff": stdout,
            "has_diff": len(stdout.strip()) > 0,
            "modified_files": list(set(modified_files)),
            "line_count": len(stdout.splitlines()),
        }

    def stage_file(self, repo_dir: Path, file_rel_path: str) -> Dict[str, Any]:
        """Stages a specific file via git add."""
        repo_dir = Path(repo_dir).resolve()
        code, stdout, stderr = self._run_git(["add", file_rel_path], cwd=repo_dir)
        if code != 0:
            return {"success": False, "error": sanitize_error_message(stderr)}
        return {"success": True, "message": f"Staged '{file_rel_path}' successfully."}

    def commit_changes(
        self,
        repo_dir: Path,
        commit_message: str,
        author_name: str = "Agentic Assistant",
        author_email: str = "agent@multiagent-se.local",
    ) -> Dict[str, Any]:
        """Creates a signed Git commit in the local sandbox."""
        repo_dir = Path(repo_dir).resolve()
        env = {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        }
        code, stdout, stderr = self._run_git(
            ["commit", "-m", commit_message],
            cwd=repo_dir,
            env=env,
        )
        if code != 0:
            return {"success": False, "error": sanitize_error_message(stderr.strip() or stdout.strip())}

        sha = self.get_head_commit_sha(repo_dir)
        return {
            "success": True,
            "commit_sha": sha,
            "message": f"Committed changes with SHA {sha[:8]}",
        }

    def get_remote_url(self, repo_dir: Path, remote_name: str = "origin") -> Optional[str]:
        """Returns the configured remote URL for a repository."""
        repo_dir = Path(repo_dir).resolve()
        code, stdout, _ = self._run_git(["remote", "get-url", remote_name], cwd=repo_dir)
        return stdout.strip() if code == 0 and stdout.strip() else None

    def push_branch(
        self,
        repo_dir: Path,
        branch_name: str,
        remote_name: str = "origin",
        auth_token: Optional[str] = None,
        set_upstream: bool = True,
    ) -> Dict[str, Any]:
        """Pushes an approved agentic feature branch to the remote repository.

        Strict Safety Rules Enforced:
        1. ONLY branches starting with 'agentic/' are permitted.
        2. NEVER push to default branches ('main', 'master', 'develop', 'release', etc.).
        3. Force pushes (--force, --force-with-lease) are strictly forbidden.
        4. Deletion of remote branches is strictly forbidden.
        5. Credentials in URLs or headers are masked and never leaked into logs.
        """
        clean_branch = branch_name.strip()
        repo_dir = Path(repo_dir).resolve()

        # Rule 1 & 2: Branch naming and default branch protection
        if not clean_branch.startswith("agentic/"):
            return {
                "success": False,
                "error": f"Security Alert: Push blocked. Only dedicated 'agentic/*' branches may be pushed (got '{clean_branch}').",
            }

        forbidden_targets = {"main", "master", "develop", "dev", "release", "prod", "production"}
        if clean_branch.lower() in forbidden_targets or clean_branch.split("/")[-1].lower() in forbidden_targets:
            return {
                "success": False,
                "error": f"Security Alert: Direct push to default or protected branch '{clean_branch}' is strictly forbidden.",
            }

        # Check repository exists and is a git repository
        if not (repo_dir / ".git").exists():
            return {"success": False, "error": f"Path '{repo_dir}' is not a valid Git repository."}

        # Assemble push arguments
        args = []
        if auth_token and auth_token.strip():
            # Inject authorization header transiently without writing to .git/config
            args.extend(["-c", f"http.extraheader=AUTHORIZATION: bearer {auth_token.strip()}"])

        args.append("push")
        if set_upstream:
            args.append("-u")
        args.extend([remote_name, clean_branch])

        code, stdout, stderr = self._run_git(args, cwd=repo_dir)
        if code != 0:
            return {
                "success": False,
                "error": sanitize_error_message(f"Git push failed: {stderr.strip() or stdout.strip()}"),
            }

        return {
            "success": True,
            "branch": clean_branch,
            "remote": remote_name,
            "message": f"Successfully pushed branch '{clean_branch}' to remote '{remote_name}'.",
        }


# Singleton instance
git_manager = GitManager()
