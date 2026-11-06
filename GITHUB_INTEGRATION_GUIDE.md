# GitHub Integration Guide: Git Tooling & Sandboxed Operations

**Project:** Multi-Agent AI System for Autonomous Software Engineering  
**Workspace:** `D:\MultiAgent-Software-Engineering`  
**Phase:** Phase 2.1 — Git Tooling & Repository Intelligence  
**Component:** `core/git/` and `mcp_servers/repo_tool/`

---

## 1. Overview and Architecture

The Git Tooling subsystem provides safe, sandboxed, and non-destructive Git operations for the multi-agent software engineering platform. Rather than interacting with live production branches directly or executing insecure shell strings, all repository actions are mediated by `core/git/git_manager.py` and exposed via the MCP Repository Tool (`mcp-repository-tool`).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          GIT SANDBOX ISOLATION FLOW                         │
└─────────────────────────────────────────────────────────────────────────────┘
  GitHub HTTPS URL (e.g. https://github.com/owner/repo)
         │
         ▼
  [validate_github_url] ──► Validates regex, blocks command injection & HTTP
         │
         ▼
  [git clone --depth 1] ──► Clones to sandbox_workspace/runs/<run_id>/
         │
         ▼
  [create_isolated_branch] ──► git checkout -b agentic/{task_id}-{run_id}
         │
         ├──► Agent Code Modifications (isolated strictly to sandbox)
         ├──► Test Suite Execution (pytest in sandbox)
         │
         ▼
  [get_git_status / get_git_diff] ──► Structured inspection (porcelain & diff)
         │
         ▼
  [HITL Gatekeeper] ──► Changes remain quarantined until human approval
```

---

## 2. Security & Guardrails

1. **No Command Injection:**
   All Git operations execute using `subprocess.run(["git", ...], shell=False)` with strictly tokenized arguments. Semicolons, pipes, backticks, dollar signs, and redirect operators are rejected at the validation layer.
2. **Credential Sanitization:**
   Error strings and logs automatically mask GitHub Personal Access Tokens (`ghp_...`, `github_pat_...`) and URL credentials (`https://***:***@github.com`).
3. **Sandbox Path Traversal Bounds:**
   Target run paths are resolved using `Path.resolve()` and validated against `settings.SANDBOX_ROOT / "runs"`. Any path referencing `..` outside designated directories triggers a `PermissionError`.
4. **Non-Destructive Guarantee:**
   Original upstream repositories and default base branches (`main` / `master`) are never modified directly.

---

## 3. Core API Reference (`core/git/git_manager.py`)

### `validate_github_url(url: str) -> Tuple[bool, str]`
Validates that a string is a well-formed GitHub HTTPS URL matching:
`^https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?/?$`
- Rejects non-HTTPS schemes.
- Rejects shell metacharacters (`;`, `&`, `|`, `` ` ``, `$`, `>`, `<`).
- Returns `(True, normalized_url)` or `(False, error_reason)`.

### `clone_repository(repo_url: str, target_dir: Path, base_branch: Optional[str] = None, depth: int = 1) -> Dict[str, Any]`
Performs a fast, shallow clone (`git clone --depth <depth>`) of the repository into an isolated directory.
- Captures commit SHA and active branch.
- Rolls back and purges `target_dir` if cloning fails.

### `create_isolated_branch(repo_dir: Path, task_id: str, run_id: str) -> Dict[str, Any]`
Generates a deterministic branch name `agentic/{clean_task_id}-{clean_run_id}` and runs:
`git checkout -b agentic/{task_id}-{run_id}`

### `get_git_status(repo_dir: Path) -> Dict[str, Any]`
Executes `git status --porcelain=v1` and returns a structured dictionary:
- `is_clean`: boolean flag
- `added`: list of newly added files
- `modified`: list of edited files
- `deleted`: list of removed files
- `renamed`: list of renamed files
- `untracked`: list of newly created, untracked files

### `get_git_diff(repo_dir: Path, staged: bool = False, base_branch: Optional[str] = None) -> Dict[str, Any]`
Generates real Git diffs:
- `staged=False`: working tree diff (`git diff HEAD`)
- `staged=True`: staged index diff (`git diff --cached`)
- `base_branch`: comparison against upstream branch (`git diff origin/main...HEAD`)

---

## 4. MCP Tools Reference (`mcp-repository-tool`)

The FastMCP server exposes Git capabilities to both in-process agents and stdio JSON-RPC clients:

| Tool Name | Parameters | Description |
|---|---|---|
| `clone_github_repository` | `repo_url`, `base_branch`, `run_id` | Clones remote GitHub repo into run sandbox. |
| `create_git_branch` | `run_id`, `task_id` | Creates and checks out isolated `agentic/` branch. |
| `get_git_status` | `run_id` | Returns structured porcelain status of sandbox. |
| `get_git_diff` | `run_id`, `staged`, `base_branch` | Returns unified diff text and modified files. |
| `apply_patch_to_sandbox` | `run_id`, `file_rel_path`, `new_content` | Writes file modifications into sandbox. |
| `read_file_from_sandbox` | `run_id`, `file_rel_path` | Reads file content with traversal bounds. |
| `commit_sandbox_to_main` | `run_id`, `human_approved`, `approval_notes` | Commits changes with compulsory human sign-off. |

---

## 5. Usage Example

```python
from mcp_servers.repo_tool.client import mcp_repo_client

# 1. Clone public repository
clone_res = mcp_repo_client.clone_repository(
    repo_url="https://github.com/pallets/flask",
    run_id="run_flask_demo",
)
assert clone_res["success"] is True

# 2. Create isolated feature branch
branch_res = mcp_repo_client.create_branch(
    run_id="run_flask_demo",
    task_id="TSK-01-FEATURE",
)
print("Active branch:", branch_res["branch_name"])

# 3. Check status
status = mcp_repo_client.get_status(run_id="run_flask_demo")
print("Working tree clean:", status["is_clean"])
```

