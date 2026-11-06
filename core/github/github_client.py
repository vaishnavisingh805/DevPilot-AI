"""GitHub REST API Client for Repository Permissions & Pull Request Management.

Provides safe, authenticated interactions with the GitHub REST API (v3) using
standard HTTPS requests, structured error handling, and token redaction.
"""

import os
from typing import Dict, Any, Optional, Tuple
import requests

from config.settings import settings
from core.git.git_manager import sanitize_error_message, extract_github_owner_repo


class GitHubAPIError(Exception):
    """Exception raised for failed GitHub API operations."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(sanitize_error_message(message))
        self.status_code = status_code
        self.response_body = sanitize_error_message(response_body or "")


class GitHubClient:
    """Interacts with the GitHub REST API for permissions, branch verification, and PR creation."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        default_token: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.base_url = (base_url or settings.GITHUB_API_BASE_URL).rstrip("/")
        self._default_token = token or default_token

    def _resolve_token(self, token: Optional[str] = None) -> Optional[str]:
        """Resolves GitHub token from argument, environment, or settings."""
        tok = token or self._default_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or settings.GITHUB_TOKEN
        return tok.strip() if tok and tok.strip() else None

    def _get_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        """Constructs safe GitHub API headers."""
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "DevPilot-AI-Autonomous-SE",
        }
        resolved = self._resolve_token(token)
        if resolved:
            headers["Authorization"] = f"Bearer {resolved}"
        return headers

    def validate_token(self, token: Optional[str] = None) -> Dict[str, Any]:
        """Validates that a GitHub personal access token is valid and active."""
        tok = self._resolve_token(token)
        if not tok:
            return {"valid": False, "error": "No GitHub token provided or configured."}

        url = f"{self.base_url}/user"
        try:
            resp = requests.get(url, headers=self._get_headers(tok), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                raw_scopes = resp.headers.get("X-OAuth-Scopes") or resp.headers.get("x-oauth-scopes") or ""
                return {
                    "valid": True,
                    "login": data.get("login"),
                    "name": data.get("name"),
                    "scopes": [s.strip() for s in raw_scopes.split(",") if s.strip()],
                    "rate_limit_remaining": int(resp.headers.get("X-RateLimit-Remaining", resp.headers.get("x-ratelimit-remaining", -1))),
                }
            elif resp.status_code == 401:
                return {"valid": False, "status_code": 401, "error": "Authentication failed: Invalid or expired GitHub token."}
            elif resp.status_code == 403:
                return {"valid": False, "status_code": 403, "error": "Rate limit exceeded or token lacks required permissions."}
            else:
                return {"valid": False, "status_code": resp.status_code, "error": sanitize_error_message(f"HTTP {resp.status_code}: {resp.text}")}
        except requests.RequestException as exc:
            return {"valid": False, "error": sanitize_error_message(f"Network error connecting to GitHub: {str(exc)}")}

    def check_repo_permissions(
        self,
        owner: str,
        repo: str,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verifies repository existence, visibility, default branch, and push permissions."""
        url = f"{self.base_url}/repos/{owner}/{repo}"
        headers = self._get_headers(token)

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                perms = data.get("permissions", {})
                can_push = perms.get("push", False)
                is_priv = data.get("private", False)
                return {
                    "exists": True,
                    "owner": owner,
                    "repo": repo,
                    "full_name": data.get("full_name", f"{owner}/{repo}"),
                    "private": is_priv,
                    "is_private": is_priv,
                    "default_branch": data.get("default_branch", "main"),
                    "permissions": perms,
                    "can_push": can_push,
                    "has_push_access": can_push,
                    "status_code": 200,
                }
            elif resp.status_code == 401:
                return {
                    "exists": False,
                    "can_push": False,
                    "has_push_access": False,
                    "error": "Authentication failed: Invalid or expired token.",
                    "status_code": 401,
                }
            elif resp.status_code == 404:
                return {
                    "exists": False,
                    "can_push": False,
                    "has_push_access": False,
                    "error": f"Repository '{owner}/{repo}' not found (or private and token lacks read access).",
                    "status_code": 404,
                }
            elif resp.status_code == 403:
                return {
                    "exists": False,
                    "can_push": False,
                    "has_push_access": False,
                    "error": f"Access forbidden or rate limit hit on '{owner}/{repo}'.",
                    "status_code": 403,
                }
            else:
                return {
                    "exists": False,
                    "can_push": False,
                    "has_push_access": False,
                    "error": sanitize_error_message(f"HTTP {resp.status_code}: {resp.text}"),
                    "status_code": resp.status_code,
                }
        except requests.RequestException as exc:
            return {
                "exists": False,
                "can_push": False,
                "error": sanitize_error_message(f"Network error connecting to GitHub API: {str(exc)}"),
                "status_code": 500,
            }

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str,
        token: Optional[str] = None,
        draft: bool = False,
    ) -> Dict[str, Any]:
        """Creates a Pull Request via GitHub REST API."""
        tok = self._resolve_token(token)
        if not tok:
            return {
                "success": False,
                "error": "Authentication required: A valid GitHub token is needed to open a Pull Request.",
            }

        url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
        headers = self._get_headers(tok)
        payload = {
            "title": title.strip(),
            "head": head.strip(),
            "base": base.strip(),
            "body": body,
            "draft": draft,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    "success": True,
                    "pr_number": data.get("number"),
                    "pr_url": data.get("html_url"),
                    "api_url": data.get("url"),
                    "state": data.get("state"),
                    "head_branch": head,
                    "base_branch": base,
                    "title": data.get("title"),
                    "message": f"Successfully created Pull Request #{data.get('number')}: {data.get('html_url')}",
                }
            elif resp.status_code == 422:
                # Validation error, e.g. PR already exists or no commits between branches
                err_text = resp.text
                return {
                    "success": False,
                    "error": sanitize_error_message(f"GitHub PR validation error (422): {err_text}"),
                    "status_code": 422,
                }
            elif resp.status_code == 403:
                return {
                    "success": False,
                    "error": "Permission denied or secondary rate limit exceeded while creating PR.",
                    "status_code": 403,
                }
            else:
                return {
                    "success": False,
                    "error": sanitize_error_message(f"Failed to create PR (HTTP {resp.status_code}): {resp.text}"),
                    "status_code": resp.status_code,
                }
        except requests.RequestException as exc:
            return {
                "success": False,
                "error": sanitize_error_message(f"Network error creating GitHub PR: {str(exc)}"),
            }

    def get_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieves details of an existing Pull Request."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pull_number}"
        headers = self._get_headers(token)

        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "success": True,
                    "pr_number": data.get("number"),
                    "pr_url": data.get("html_url"),
                    "state": data.get("state"),
                    "title": data.get("title"),
                    "merged": data.get("merged", False),
                    "mergeable": data.get("mergeable"),
                }
            return {
                "success": False,
                "error": sanitize_error_message(f"HTTP {resp.status_code}: {resp.text}"),
            }
        except requests.RequestException as exc:
            return {"success": False, "error": sanitize_error_message(str(exc))}


# Global singleton instance
github_client = GitHubClient()
