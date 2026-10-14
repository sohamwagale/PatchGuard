"""Integration tests for MCP Server and Client."""

import asyncio
import tempfile
from pathlib import Path

from patchguard.mcp_client import PatchGuardMCPClient


def test_mcp_client_tools_and_operations():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir).resolve()
            (repo / "sample.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")

            client = PatchGuardMCPClient(repo_root=repo)
            async with client:
                tools = await client.list_tools()
                tool_names = [t["name"] for t in tools]
                assert "read_file" in tool_names
                assert "write_file" in tool_names
                assert "edit_file" in tool_names
                assert "search_code" in tool_names
                assert "run_docker_tests" in tool_names

                # 1. Test read_file
                content = await client.call_tool("read_file", {"path": "sample.py"})
                assert "def hello():" in content

                # 2. Test edit_file
                edit_res = await client.call_tool(
                    "edit_file",
                    {"path": "sample.py", "target": "'world'", "replacement": "'patchguard'"},
                )
                assert "Successfully edited" in edit_res

                # Verify edit
                new_content = await client.call_tool("read_file", {"path": "sample.py"})
                assert "return 'patchguard'" in new_content

                # 3. Test search_code
                search_res = await client.call_tool("search_code", {"query": "patchguard"})
                assert "sample.py" in search_res

                # 4. Test security rejection via MCP tool
                blocked_res = await client.call_tool("read_file", {"path": "../secret.txt"})
                assert "[SECURITY_VIOLATION]" in blocked_res

    asyncio.run(run())
