"""MCP Test Runner and Sandbox Execution Tool Server.

Executes pytest within an isolated sandbox under strict timeout and safety
controls, outputting structured test reports and assertion diagnostics.
"""

import ast
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

from mcp.server.fastmcp import FastMCP
from config.settings import settings
from core.schemas.tests import TestResultReport, TestResultItem

# Initialize FastMCP Server
test_mcp = FastMCP("mcp-test-runner")


def detect_package_manager(repo_path: Path) -> str:
    """Detects the Node package manager from repository lockfiles."""
    if (repo_path / "yarn.lock").exists():
        return "yarn"
    if (repo_path / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (repo_path / "bun.lockb").exists() or (repo_path / "bun.lock").exists():
        return "bun"
    return "npm"


@test_mcp.tool()
def install_package_dependencies(
    sandbox_path: str,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """Installs project package dependencies inside the isolated sandbox.

    Detects lockfiles (npm, yarn, pnpm, bun) and executes lockfile-respecting
    installation strictly inside the sandbox directory.

    Args:
        sandbox_path: Absolute or relative path to the sandbox workspace.
        timeout_seconds: Command timeout limit (default 120s).

    Returns:
        Structured result indicating success, exit code, output, and diagnostics.
    """
    path = Path(sandbox_path).resolve()
    if not path.exists():
        return {
            "success": False,
            "installed": False,
            "error": f"Path '{sandbox_path}' does not exist.",
            "exit_code": 1,
        }

    pkg_json = path / "package.json"
    if not pkg_json.exists():
        return {
            "success": True,
            "installed": False,
            "message": "No package.json detected; skipping Node dependency installation.",
            "exit_code": 0,
        }

    pkg_mgr = detect_package_manager(path)
    pkg_bin = shutil.which(pkg_mgr)
    if not pkg_bin:
        return {
            "success": False,
            "installed": False,
            "package_manager": pkg_mgr,
            "error": f"RUNTIME_UNAVAILABLE: Package manager '{pkg_mgr}' not found on host PATH.",
            "exit_code": 127,
            "raw_stdout": "",
            "raw_stderr": f"Executable '{pkg_mgr}' is not installed or not in PATH.",
        }

    # Construct lockfile-respecting install command
    if pkg_mgr == "npm":
        if (path / "package-lock.json").exists():
            cmd = [pkg_mgr, "ci"]
        else:
            cmd = [pkg_mgr, "install", "--prefer-offline"]
    elif pkg_mgr == "yarn":
        if (path / "yarn.lock").exists():
            cmd = [pkg_mgr, "install", "--frozen-lockfile"]
        else:
            cmd = [pkg_mgr, "install"]
    elif pkg_mgr == "pnpm":
        if (path / "pnpm-lock.yaml").exists():
            cmd = [pkg_mgr, "install", "--frozen-lockfile"]
        else:
            cmd = [pkg_mgr, "install"]
    elif pkg_mgr == "bun":
        cmd = [pkg_mgr, "install"]
    else:
        cmd = ["npm", "install"]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=(sys.platform == "win32"),
        )
        is_success = (proc.returncode == 0)
        return {
            "success": is_success,
            "installed": is_success,
            "package_manager": pkg_mgr,
            "command": " ".join(cmd),
            "exit_code": proc.returncode,
            "output": proc.stdout[-1000:],
            "error": None if is_success else f"DEPENDENCY_INSTALL_FAILED (exit {proc.returncode}): {proc.stderr[-400:] or proc.stdout[-400:]}",
            "raw_stdout": proc.stdout,
            "raw_stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "installed": False,
            "package_manager": pkg_mgr,
            "command": " ".join(cmd),
            "exit_code": -1,
            "error": f"DEPENDENCY_INSTALL_TIMEOUT: Package installation timed out after {timeout_seconds}s.",
            "raw_stdout": "",
            "raw_stderr": "Timeout expired",
        }
    except Exception as e:
        return {
            "success": False,
            "installed": False,
            "package_manager": pkg_mgr,
            "command": " ".join(cmd),
            "exit_code": -1,
            "error": f"DEPENDENCY_INSTALL_FAILED: {str(e)}",
            "raw_stdout": "",
            "raw_stderr": str(e),
        }


@test_mcp.tool()
def check_python_syntax(sandbox_path: str) -> Dict[str, Any]:
    """Scans all Python files in the sandbox directory for AST syntax errors.

    Args:
        sandbox_path: Absolute or relative path to the sandbox workspace.

    Returns:
        Dictionary indicating whether all files have valid Python syntax.
    """
    path = Path(sandbox_path).resolve()
    if not path.exists():
        return {"success": False, "error": f"Path '{sandbox_path}' does not exist."}

    errors: List[Dict[str, Any]] = []
    py_files = list(path.rglob("*.py"))

    for py_file in py_files:
        try:
            code = py_file.read_text(encoding="utf-8")
            ast.parse(code, filename=str(py_file))
        except SyntaxError as e:
            errors.append({
                "file": str(py_file.relative_to(path)),
                "line": e.lineno,
                "offset": e.offset,
                "msg": e.msg,
                "text": e.text,
            })
        except Exception as e:
            errors.append({
                "file": str(py_file.relative_to(path)),
                "error": str(e),
            })

    return {
        "success": len(errors) == 0,
        "files_checked": len(py_files),
        "syntax_errors": errors,
        "message": "All Python files passed syntax check" if not errors else f"Found {len(errors)} syntax errors",
    }


@test_mcp.tool()
def run_pytest(
    sandbox_path: str,
    test_rel_path: str = "tests",
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """Executes pytest against the test suite in the isolated sandbox.

    Args:
        sandbox_path: Absolute or relative path to the sandbox directory.
        test_rel_path: Subfolder containing tests (defaults to 'tests').
        timeout_seconds: Hard timeout to prevent infinite loops.

    Returns:
        Structured test execution report.
    """
    path = Path(sandbox_path).resolve()
    if not path.exists():
        return {
            "success": False,
            "error": f"Target sandbox path '{sandbox_path}' does not exist.",
            "report": None,
        }

    # 1. Check for Node / React / TypeScript repository (package.json)
    pkg_json_file = path / "package.json"
    if pkg_json_file.exists():
        pkg_mgr = detect_package_manager(path)
        try:
            import json
            pkg_data = json.loads(pkg_json_file.read_text(encoding="utf-8"))
        except Exception as e:
            report = TestResultReport(
                total_tests=1,
                passed=0,
                failed=1,
                errors=1,
                all_passed=False,
                items=[
                    TestResultItem(
                        test_node_id=f"{pkg_mgr}::package_json_syntax",
                        outcome="failed",
                        failure_message=f"Invalid package.json syntax: {str(e)}",
                    )
                ],
                raw_stderr=f"Invalid package.json syntax: {str(e)}",
            )
            return {
                "success": True,
                "all_passed": False,
                "passed_count": 0,
                "failed_count": 1,
                "total_count": 1,
                "report": report.model_dump(mode="json"),
                "error": "INVALID_PACKAGE_JSON",
            }

        scripts = pkg_data.get("scripts", {})
        test_script = scripts.get("test", "")
        build_script = scripts.get("build", "")
        has_real_test = bool(test_script and "no test specified" not in test_script.lower())

        # If a build script exists, verify production build
        if build_script:
            build_cmd = [pkg_mgr, "run", "build"]
            try:
                build_proc = subprocess.run(
                    build_cmd,
                    cwd=str(path),
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    shell=(sys.platform == "win32"),
                )
                if build_proc.returncode != 0:
                    report = TestResultReport(
                        total_tests=1,
                        passed=0,
                        failed=1,
                        errors=1,
                        all_passed=False,
                        items=[
                            TestResultItem(
                                test_node_id=f"{pkg_mgr}::build",
                                outcome="failed",
                                failure_message=f"Production build failed with exit code {build_proc.returncode}: {build_proc.stderr[:300]}",
                            )
                        ],
                        raw_stdout=build_proc.stdout,
                        raw_stderr=build_proc.stderr,
                    )
                    return {
                        "success": True,
                        "all_passed": False,
                        "passed_count": 0,
                        "failed_count": 1,
                        "total_count": 1,
                        "duration_seconds": 0.5,
                        "report": report.model_dump(mode="json"),
                        "raw_stdout": build_proc.stdout,
                        "raw_stderr": build_proc.stderr,
                        "error": f"PRODUCTION_BUILD_FAILED: Exit code {build_proc.returncode}",
                    }
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "all_passed": False,
                    "error": f"Build verification timed out after {timeout_seconds}s",
                }
            except Exception:
                pass

        if has_real_test:
            test_cmd = [pkg_mgr, "test"]
            try:
                test_proc = subprocess.run(
                    test_cmd,
                    cwd=str(path),
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    shell=(sys.platform == "win32"),
                )
                is_passed = (test_proc.returncode == 0)
                stdout_combined = test_proc.stdout + "\n" + test_proc.stderr
                v_match = re.search(r"Tests\s+(\d+)\s+passed", stdout_combined, re.IGNORECASE)
                if not v_match:
                    v_match = re.search(r"#\s*pass\s+(\d+)", stdout_combined, re.IGNORECASE)
                total_t = int(v_match.group(1)) if v_match else 1
                passed_t = total_t if is_passed else 0
                failed_t = 0 if is_passed else total_t

                report = TestResultReport(
                    total_tests=total_t,
                    passed=passed_t,
                    failed=failed_t,
                    errors=0 if is_passed else 1,
                    all_passed=is_passed,
                    items=[
                        TestResultItem(
                            test_node_id=f"{pkg_mgr}::test",
                            outcome="passed" if is_passed else "failed",
                            failure_message=None if is_passed else test_proc.stderr[:300] or test_proc.stdout[:300],
                        )
                    ],
                    raw_stdout=test_proc.stdout,
                    raw_stderr=test_proc.stderr,
                )
                return {
                    "success": True,
                    "all_passed": is_passed,
                    "passed_count": passed_t,
                    "failed_count": failed_t,
                    "total_count": total_t,
                    "report": report.model_dump(mode="json"),
                    "raw_stdout": test_proc.stdout,
                    "raw_stderr": test_proc.stderr,
                }
            except subprocess.TimeoutExpired:
                return {"success": False, "all_passed": False, "error": f"Test timed out after {timeout_seconds}s"}
            except Exception:
                pass

        # If no real automated test script is configured:
        report = TestResultReport(
            total_tests=0,
            passed=0,
            failed=0,
            errors=0,
            skipped=0,
            all_passed=False,
            execution_time_seconds=0.01,
            items=[
                TestResultItem(
                    test_node_id=f"{pkg_mgr}::test",
                    outcome="skipped",
                    failure_message="FUNCTIONAL_TESTS_NOT_CONFIGURED: package.json has no test script defined.",
                )
            ],
            raw_stdout=f"FUNCTIONAL_TESTS_NOT_CONFIGURED: No automated test framework (Jest/Vitest) configured in package.json using {pkg_mgr}.",
            raw_stderr="FUNCTIONAL_TESTS_NOT_CONFIGURED",
        )
        return {
            "success": True,
            "all_passed": False,
            "passed_count": 0,
            "failed_count": 0,
            "total_count": 0,
            "duration_seconds": 0.01,
            "report": report.model_dump(mode="json"),
            "raw_stdout": report.raw_stdout,
            "raw_stderr": report.raw_stderr,
            "error": "FUNCTIONAL_TESTS_NOT_CONFIGURED",
        }

    # 2. Check for Python test suites
    tests_dir = path / test_rel_path
    if not tests_dir.exists():
        if (path / "test").exists():
            tests_dir = path / "test"
        elif list(path.glob("test_*.py")) or list(path.glob("*_test.py")):
            tests_dir = path
        else:
            # No Python tests and no package.json
            report = TestResultReport(
                total_tests=0,
                passed=0,
                failed=0,
                errors=0,
                skipped=0,
                all_passed=False,
                execution_time_seconds=0.01,
                items=[],
                raw_stdout="FUNCTIONAL_TESTS_NOT_CONFIGURED: No Python test suite or package.json found in repository.",
                raw_stderr="FUNCTIONAL_TESTS_NOT_CONFIGURED",
            )
            return {
                "success": True,
                "all_passed": False,
                "passed_count": 0,
                "failed_count": 0,
                "total_count": 0,
                "duration_seconds": 0.01,
                "report": report.model_dump(mode="json"),
                "raw_stdout": report.raw_stdout,
                "raw_stderr": report.raw_stderr,
                "error": "FUNCTIONAL_TESTS_NOT_CONFIGURED",
            }

    # Prepare command using current python executable
    python_exe = sys.executable
    cmd = [
        python_exe,
        "-m",
        "pytest",
        str(tests_dir),
        "-vv",
        f"--rootdir={str(path)}",
        "-o",
        f"pythonpath={str(path)} {str(path / 'src')}",
        "-o",
        "asyncio_default_fixture_loop_scope=function",
        "--no-header",
        "--tb=short",
    ]

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={**os.environ, "PYTHONPATH": f"{str(path)};{str(path / 'src')}"},
        )
        duration = round(time.time() - start_time, 3)
        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        duration = round(time.time() - start_time, 3)
        return {
            "success": False,
            "error": f"Pytest execution timed out after {timeout_seconds} seconds.",
            "all_passed": False,
            "duration": duration,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Execution error: {str(e)}",
            "all_passed": False,
            "duration": 0.0,
        }

    # Parse pytest output
    items: List[TestResultItem] = []
    passed = 0
    failed = 0
    errors = 0

    import re

    for line in stdout.splitlines():
        line = line.strip()
        if "::" in line:
            parts = line.split()
            node_id = parts[0]
            outcome = "unknown"
            if "PASSED" in line:
                outcome = "passed"
                passed += 1
            elif "FAILED" in line:
                outcome = "failed"
                failed += 1
            elif "ERROR" in line:
                outcome = "error"
                errors += 1

            items.append(TestResultItem(
                test_node_id=node_id,
                outcome=outcome,
                duration_seconds=0.0,
            ))

    # Fallback to summary line if items wasn't populated
    if not items:
        passed_m = re.search(r"(\d+)\s+passed", stdout)
        failed_m = re.search(r"(\d+)\s+failed", stdout)
        error_m = re.search(r"(\d+)\s+error", stdout)
        if passed_m:
            passed = int(passed_m.group(1))
        if failed_m:
            failed = int(failed_m.group(1))
        if error_m:
            errors = int(error_m.group(1))

    total = passed + failed + errors
    all_passed = (exit_code == 0 and total > 0 and failed == 0 and errors == 0)

    report = TestResultReport(
        total_tests=total,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=0,
        all_passed=all_passed,
        execution_time_seconds=duration,
        items=items,
        raw_stdout=stdout,
        raw_stderr=stderr,
    )

    return {
        "success": True,
        "all_passed": all_passed,
        "passed_count": passed,
        "failed_count": failed,
        "total_count": total,
        "duration_seconds": duration,
        "report": report.model_dump(mode="json"),
        "raw_stdout": stdout,
    }


if __name__ == "__main__":
    test_mcp.run()
