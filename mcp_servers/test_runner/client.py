"""Python Client interface for MCP Test Runner Tool."""

from typing import Dict, Any
from mcp_servers.test_runner.server import check_python_syntax, run_pytest, install_package_dependencies
from core.schemas.tests import TestResultReport


class MCPTestRunnerClient:
    """Client wrapper for the MCP Test Execution Tool."""

    def __init__(self):
        self.name = "mcp-test-runner-client"

    def check_syntax(self, sandbox_path: str) -> Dict[str, Any]:
        return check_python_syntax(sandbox_path)

    def install_dependencies(self, sandbox_path: str, timeout_seconds: int = 120) -> Dict[str, Any]:
        """Installs package dependencies in the specified sandbox path."""
        return install_package_dependencies(sandbox_path=sandbox_path, timeout_seconds=timeout_seconds)

    def run_tests(
        self,
        sandbox_path: str,
        test_rel_path: str = "tests",
        timeout_seconds: int = 30,
    ) -> Dict[str, Any]:
        result = run_pytest(
            sandbox_path=sandbox_path,
            test_rel_path=test_rel_path,
            timeout_seconds=timeout_seconds,
        )
        # Parse into typed TestResultReport if available
        if result.get("success") and result.get("report"):
            try:
                result["typed_report"] = TestResultReport.model_validate(result["report"])
            except Exception:
                result["typed_report"] = None
        return result


# Global client instance
mcp_test_client = MCPTestRunnerClient()

