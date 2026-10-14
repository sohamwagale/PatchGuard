"""Model Context Protocol (MCP) Server for PatchGuard.

=============================================================================
WHY THIS MODULE EXISTS (Model Context Protocol Concept):
Model Context Protocol (MCP) is an open standard created by Anthropic that
standardizes how AI agents discover and execute tools.

Instead of writing custom ad-hoc tool calling formats, MCP defines:
1. Tool Discovery: Server publishes available tools and JSON schemas (`list_tools`).
2. Tool Execution: Client calls tool with arguments over standard IO (`call_tool`).
3. Interoperability: Any MCP-compliant client or IDE (Claude, Antigravity, Cursor)
   can connect to this PatchGuard server and use its tools out of the box!

In this module:
- All file tools (`read_file`, `write_file`, `edit_file`, `list_dir`, `search_code`)
  are routed through `PathGuard` before touching disk.
- Test runs (`run_docker_tests`) are isolated inside `DockerSandboxRunner`.
=============================================================================
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from mcp.server.mcpserver import MCPServer

from patchguard.docker_runner import DockerSandboxRunner
from patchguard.guardrails import PathGuard, SafetyViolation

# Initialize MCP server with name "PatchGuard"
mcp = MCPServer("PatchGuard")

# Repository root to govern (configurable via PATCHGUARD_REPO_ROOT environment variable)
REPO_ROOT = Path(os.environ.get("PATCHGUARD_REPO_ROOT", os.getcwd())).resolve()

# Security gatekeeper instance protecting this repository
path_guard = PathGuard(REPO_ROOT)

# Docker sandbox instance for isolated test execution
docker_runner = DockerSandboxRunner(REPO_ROOT)


@mcp.tool()
def read_file(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """Read a file safely from the repository, optionally specifying line range [start_line, end_line].

    How it works:
    1. Validates that the path is within repository bounds using PathGuard (allow_write=False).
    2. Reads file lines with UTF-8 encoding.
    3. If start_line/end_line are given, slices the requested range with 1-based line numbers.
    """
    try:
        # Validate that path doesn't escape repo and isn't protected (.git, .env)
        safe_path = path_guard.validate(path, allow_write=False)
        if not safe_path.exists():
            return f"Error: File '{path}' does not exist."
        if not safe_path.is_file():
            return f"Error: Path '{path}' is not a regular file."

        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        # Slice specific line window if requested by the agent
        if start_line is not None or end_line is not None:
            s = max(1, start_line or 1) - 1
            e = end_line if end_line is not None else len(lines)
            selected = lines[s:e]
            numbered = [f"{s + idx + 1:4d} | {line}" for idx, line in enumerate(selected)]
            return "".join(numbered)
        return "".join(lines)
    except SafetyViolation as sv:
        return f"[SECURITY_VIOLATION] {sv.message}"
    except Exception as exc:
        return f"Error reading file '{path}': {exc}"


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write or overwrite a file in the repository under PathGuard protection.

    How it works:
    1. Validates that the path is permitted under PathGuard and matches the write allowlist.
    2. Automatically creates parent directories if needed.
    3. Writes the updated content.
    """
    try:
        # Validate with allow_write=True: checks against write allowlist (e.g. ['src', 'tests'])
        safe_path = path_guard.validate(path, allow_write=True)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} characters to {path}"
    except SafetyViolation as sv:
        return f"[SECURITY_VIOLATION] {sv.message}"
    except Exception as exc:
        return f"Error writing file '{path}': {exc}"


@mcp.tool()
def edit_file(path: str, target: str, replacement: str) -> str:
    """Replace a specific substring target with replacement in a repository file.

    Why this tool is preferred over write_file:
    AI agents often make subtle indentation or truncation mistakes when rewriting
    an entire 500-line file. `edit_file` performs a surgical find-and-replace,
    ensuring only the intended bug fix changes while preserving the rest of the file.
    """
    try:
        safe_path = path_guard.validate(path, allow_write=True)
        if not safe_path.exists():
            return f"Error: File '{path}' does not exist."

        with open(safe_path, "r", encoding="utf-8") as f:
            original = f.read()

        if target not in original:
            return f"Error: Target snippet not found in '{path}'"

        count = original.count(target)
        if count > 1:
            return f"Error: Target snippet appears {count} times in '{path}'. Please provide more surrounding context."

        modified = original.replace(target, replacement, 1)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(modified)

        return f"Successfully edited '{path}'. Replaced 1 occurrence."
    except SafetyViolation as sv:
        return f"[SECURITY_VIOLATION] {sv.message}"
    except Exception as exc:
        return f"Error editing file '{path}': {exc}"


@mcp.tool()
def list_dir(path: str = ".") -> str:
    """List directory contents within the allowed repository."""
    try:
        safe_path = path_guard.validate(path, allow_write=False)
        if not safe_path.exists():
            return f"Error: Directory '{path}' does not exist."
        if not safe_path.is_dir():
            return f"Error: Path '{path}' is not a directory."

        entries = []
        for item in sorted(safe_path.iterdir()):
            kind = "DIR " if item.is_dir() else "FILE"
            rel = item.relative_to(REPO_ROOT)
            entries.append(f"{kind:4s} {rel}")

        return "\n".join(entries) if entries else "(empty directory)"
    except SafetyViolation as sv:
        return f"[SECURITY_VIOLATION] {sv.message}"
    except Exception as exc:
        return f"Error listing directory '{path}': {exc}"


@mcp.tool()
def search_code(query: str, path: str = ".") -> str:
    """Search for a text string or pattern in the repository files."""
    try:
        safe_root = path_guard.validate(path, allow_write=False)
        matches = []
        for root, _, files in os.walk(safe_root):
            for filename in files:
                full_path = Path(root) / filename
                # Skip protected or hidden items
                try:
                    checked_path = path_guard.validate(full_path, allow_write=False)
                except SafetyViolation:
                    continue

                try:
                    with open(checked_path, "r", encoding="utf-8") as f:
                        for line_number, line in enumerate(f, start=1):
                            if query in line:
                                rel_path = checked_path.relative_to(REPO_ROOT)
                                matches.append(f"{rel_path}:{line_number}: {line.rstrip()}")
                                if len(matches) >= 100:
                                    matches.append("... [Search truncated at 100 results]")
                                    return "\n".join(matches)
                except (UnicodeDecodeError, PermissionError):
                    continue

        return "\n".join(matches) if matches else "No matches found."
    except SafetyViolation as sv:
        return f"[SECURITY_VIOLATION] {sv.message}"
    except Exception as exc:
        return f"Error searching code: {exc}"


@mcp.tool()
def git_diff() -> str:
    """Show uncommitted git changes in the repository so agent can review its own edits."""
    try:
        proc = subprocess.run(
            ["git", "diff"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return proc.stdout if proc.stdout else "(No uncommitted diff)"
    except Exception as exc:
        return f"Error running git diff: {exc}"


@mcp.tool()
def git_status() -> str:
    """Show git status (modified/untracked files) in the repository."""
    try:
        proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return proc.stdout if proc.stdout else "(Clean working tree)"
    except Exception as exc:
        return f"Error running git status: {exc}"


@mcp.tool()
def run_docker_tests(
    test_command: str = "pytest",
    image: str = "python:3.11-slim",
    timeout: int = 60,
) -> str:
    """Run tests inside an isolated Docker container with fallback to an isolated runner."""
    result = docker_runner.run_tests(test_command=test_command, image=image, timeout=timeout)
    runner_type = "Docker" if result.is_docker else "Isolated Local Sandbox"
    status_str = "PASSED" if result.passed else ("TIMED OUT" if result.timed_out else "FAILED")

    out = [
        f"--- Sandboxed Test Run ({runner_type}) ---",
        f"Command: {test_command}",
        f"Status: {status_str} (exit code: {result.exit_code})",
        f"Duration: {result.duration_seconds:.2f}s",
        "",
        "--- STDOUT ---",
        result.stdout if result.stdout else "(none)",
        "",
        "--- STDERR ---",
        result.stderr if result.stderr else "(none)",
    ]
    return "\n".join(out)


# When run directly (e.g. via patchguard server or mcp client subprocess), start stdio loop
if __name__ == "__main__":
    mcp.run(transport="stdio")