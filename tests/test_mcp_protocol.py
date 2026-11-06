"""Protocol-level integration tests for FastMCP Servers via stdio JSON-RPC."""

import sys
import json
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_mcp_repo_server_protocol_rpc():
    """Verify mcp-repository-tool server over real stdio JSON-RPC protocol."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.repo_tool.server"],
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Protocol Step 1: Initialize session
            init_res = await session.initialize()
            assert init_res is not None
            assert init_res.serverInfo.name == "mcp-repository-tool"

            # Protocol Step 2: List available tools
            tools_list = await session.list_tools()
            tool_names = [t.name for t in tools_list.tools]
            assert "create_isolated_sandbox" in tool_names
            assert "read_file_from_sandbox" in tool_names
            assert "apply_patch_to_sandbox" in tool_names
            assert "commit_sandbox_to_main" in tool_names

            # Protocol Step 3: Invoke tool via CallToolRequest
            call_res = await session.call_tool(
                "create_isolated_sandbox",
                arguments={"source_repo_rel_path": "sample_repo"},
            )
            assert call_res is not None
            payload = json.loads(call_res.content[0].text)
            assert payload.get("success") is True
            assert "run_id" in payload
            assert "sandbox_path" in payload


@pytest.mark.asyncio
async def test_mcp_test_runner_server_protocol_rpc():
    """Verify mcp-test-runner server over real stdio JSON-RPC protocol."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.test_runner.server"],
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Protocol Step 1: Initialize session
            init_res = await session.initialize()
            assert init_res is not None
            assert init_res.serverInfo.name == "mcp-test-runner"

            # Protocol Step 2: List available tools
            tools_list = await session.list_tools()
            tool_names = [t.name for t in tools_list.tools]
            assert "check_python_syntax" in tool_names
            assert "run_pytest" in tool_names

            # Protocol Step 3: Invoke syntax check tool
            call_res = await session.call_tool(
                "check_python_syntax",
                arguments={"sandbox_path": "sandbox_workspace/sample_repo"},
            )
            assert call_res is not None
            payload = json.loads(call_res.content[0].text)
            assert payload.get("success") is True
            assert payload.get("files_checked") >= 2

