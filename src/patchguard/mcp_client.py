"""Model Context Protocol (MCP) Client for PatchGuard.

=============================================================================
WHY THIS MODULE EXISTS (MCP Client & stdio Transport Concept):
In MCP architecture, the Agent is the "Client" and the Tools live in the "Server".

How communication works over stdio:
1. Subprocess Spawning: The Client launches the Server as a subprocess (`python mcp_server.py`).
2. Stdio Streams: Instead of opening network sockets/HTTP ports, messages are sent
   via the subprocess's standard input (stdin) and received via its standard output (stdout).
3. JSON-RPC Protocol: Every message is a formatted JSON-RPC 2.0 object.
   - Initial handshake: `initialize`
   - Tool discovery: `tools/list`
   - Tool execution: `tools/call`
4. Lifecycle: `PatchGuardMCPClient` acts as an async context manager (`async with client:`),
   automatically starting the subprocess and gracefully cleaning it up on exit.
=============================================================================
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def extract_tool_text(call_result: Any) -> str:
    """Helper to extract clean plain text from an MCP CallToolResult object.

    In the MCP 2.x Python SDK, `call_tool()` returns a `CallToolResult` object
    where `content` is a list of content blocks (e.g. TextContent, ImageContent).
    This function parses that list and concatenates all text fragments.
    """
    if not hasattr(call_result, "content") or not call_result.content:
        return ""

    parts = []
    for item in call_result.content:
        if hasattr(item, "text"):
            parts.append(item.text)
        elif isinstance(item, dict) and "text" in item:
            parts.append(str(item["text"]))
        else:
            parts.append(str(item))
    return "\n".join(parts)


class PatchGuardMCPClient:
    """Asynchronous client interacting with the PatchGuard MCP server."""

    def __init__(
        self,
        server_script: str | Path | None = None,
        python_executable: str | None = None,
        repo_root: str | Path | None = None,
    ) -> None:
        """Initialize MCP Client connection parameters.

        Args:
            server_script: Path to mcp_server.py (defaults to internal package server).
            python_executable: Python interpreter binary to run the server with (uses current venv).
            repo_root: The target repository root directory being governed.
        """
        if server_script is None:
            # Default to mcp_server.py in the same folder as this module
            current_dir = Path(__file__).resolve().parent
            server_script = current_dir / "mcp_server.py"

        self.server_script = str(server_script)
        # Ensure we use sys.executable so the server runs inside the exact same virtual environment
        self.python_executable = python_executable or sys.executable
        self.repo_root = str(Path(repo_root or os.getcwd()).resolve())

        # Forward the governed repository root to the server via environment variable
        env = dict(os.environ)
        env["PATCHGUARD_REPO_ROOT"] = self.repo_root

        # StdioServerParameters configures how to start the MCP server process
        self.server_params = StdioServerParameters(
            command=self.python_executable,
            args=[self.server_script],
            env=env,
        )
        self._stdio_ctx: Any = None
        self._session_ctx: Any = None
        self.session: Optional[ClientSession] = None

    async def connect(self) -> None:
        """Start the stdio process and initialize the MCP protocol connection."""
        # 1. Spawn server subprocess with redirected stdio pipes
        self._stdio_ctx = stdio_client(self.server_params)
        read_stream, write_stream = await self._stdio_ctx.__aenter__()

        # 2. Bind the MCP ClientSession to those pipes
        self._session_ctx = ClientSession(read_stream, write_stream)
        self.session = await self._session_ctx.__aenter__()

        # 3. Perform MCP handshake
        await self.session.initialize()

    async def disconnect(self) -> None:
        """Gracefully close the MCP session and terminate the server process."""
        if self._session_ctx:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_ctx = None
            self.session = None

        if self._stdio_ctx:
            try:
                await self._stdio_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._stdio_ctx = None

    async def __aenter__(self) -> PatchGuardMCPClient:
        """Support for: async with PatchGuardMCPClient(...) as client:"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Ensure connection and subprocess are closed on context exit."""
        await self.disconnect()

    async def list_tools(self) -> list[dict[str, Any]]:
        """Fetch all available tools from the server with their JSON schemas.

        Returns:
            A list of tool dictionaries formatted for LLM consumption:
            [{ "name": "read_file", "description": "...", "input_schema": {...} }, ...]
        """
        if not self.session:
            raise RuntimeError("MCP client is not connected.")

        result = await self.session.list_tools()
        tools_list: list[dict[str, Any]] = []

        for tool in result.tools:
            tools_list.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                }
            )
        return tools_list

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Execute a tool on the MCP server and return the string output.

        Args:
            name: Name of the tool to execute (e.g. 'read_file').
            arguments: Dictionary of keyword arguments matching tool's input schema.
        """
        if not self.session:
            raise RuntimeError("MCP client is not connected.")

        call_result = await self.session.call_tool(name, arguments or {})
        return extract_tool_text(call_result)


async def main() -> None:
    """Self-test driver: connects to server, lists tools, and tests basic calls."""
    client = PatchGuardMCPClient()
    async with client:
        tools = await client.list_tools()
        print("Available tools:")
        for tool in tools:
            desc = tool['description'].splitlines()[0] if tool['description'] else ''
            print(f"- {tool['name']}: {desc}")

        # Test read_file
        print("\nTesting 'read_file' on 'sample.txt':")
        read_res = await client.call_tool("read_file", {"path": "sample.txt"})
        print(read_res)

        # Test search_code
        print("\nTesting 'search_code' for 'PatchGuard':")
        search_res = await client.call_tool("search_code", {"query": "PatchGuard"})
        print(search_res[:300] + ("..." if len(search_res) > 300 else ""))


if __name__ == "__main__":
    asyncio.run(main())