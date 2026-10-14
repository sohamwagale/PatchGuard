"""Command Line Interface for PatchGuard.

=============================================================================
WHY THIS MODULE EXISTS (CLI Experience Concept):
Provides an intuitive, production-grade command-line interface for PatchGuard
built using Click.

Commands available:
- `solve`: Runs the autonomous agent on a coding task under human-in-the-loop approval.
- `eval`: Runs the evaluation harness across benchmark tasks, tracking pass rate,
  steps, token usage, cost, and safety violations.
- `check`: Instantly tests whether a specific file path is allowed by PathGuard.
- `server`: Runs the standalone MCP server over stdio for IDE or tool connections.
=============================================================================
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import click

from patchguard.agent import PatchGuardAgent
from patchguard.eval_harness import EvalHarness, get_default_benchmarks
from patchguard.guardrails import GovernanceConfig, PathGuard, SafetyViolation
from patchguard.llm import (
    BaseLLMProvider,
    GeminiProvider,
    MockLLMProvider,
    OpenAICompatibleProvider,
    LLMResponse,
    ToolCall,
    load_env_file,
)

# Automatically load any keys from local .env
load_env_file()


def get_llm_provider(model: str, api_key: str | None = None) -> BaseLLMProvider:
    """Factory creating the appropriate LLM provider based on model selection and API keys.

    Priority order:
    1. If model == 'mock': Return deterministic MockLLMProvider (free, offline).
    2. If model contains 'gemini' or GEMINI_API_KEY/GOOGLE_API_KEY exists: Return GeminiProvider.
    3. If OPENAI_API_KEY exists: Return OpenAICompatibleProvider.
    4. Otherwise: Warn user and fallback to MockLLMProvider.
    """
    if model == "mock":
        return MockLLMProvider()

    # Route 1: Google Gemini API
    if "gemini" in model.lower() or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        gemini_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if gemini_key:
            chosen_model = model if "gemini" in model.lower() else "gemini-2.5-flash"
            click.secho(f"Using Google Gemini Provider ({chosen_model})", fg="green")
            return GeminiProvider(api_key=gemini_key, model=chosen_model)
        else:
            click.secho(
                "Error: GEMINI_API_KEY or GOOGLE_API_KEY is required to use Gemini.",
                fg="red",
                bold=True,
            )
            click.echo("Please add GEMINI_API_KEY=your_key in your .env file or export it in your shell.")
            sys.exit(1)

    # Route 2: OpenAI-compatible API
    openai_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not openai_key:
        click.secho(
            "Note: Neither GEMINI_API_KEY nor OPENAI_API_KEY found in environment. Defaulting to Mock LLM Provider.",
            fg="yellow",
        )
        return MockLLMProvider()

    return OpenAICompatibleProvider(api_key=openai_key, model=model)


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """PatchGuard: AI-Native Autonomous Coding Agent with Structural Governance."""
    pass


@main.command()
@click.argument("task")
@click.option("--repo", default=".", help="Repository root path.")
@click.option("--model", default="gemini-2.5-flash", help="LLM model (e.g. gemini-2.5-flash, gemini-1.5-flash, gpt-4o, mock).")
@click.option("--api-key", default=None, help="Explicit API key (overrides environment variable).")
@click.option("--max-steps", default=15, help="Maximum allowed tool steps (Step Cap).")
@click.option("--max-tokens", default=80000, help="Maximum token budget.")
@click.option("--cost-limit", default=0.50, help="Dollar cost ceiling.")
@click.option("--allowlist", multiple=True, help="Allowed subpaths (e.g. --allowlist src --allowlist tests).")
@click.option("--auto-approve", is_flag=True, help="Bypass interactive human-in-the-loop approval.")
def solve(
    task: str,
    repo: str,
    model: str,
    api_key: str | None,
    max_steps: int,
    max_tokens: int,
    cost_limit: float,
    allowlist: tuple[str, ...],
    auto_approve: bool,
) -> None:
    """Run PatchGuard agent to diagnose and solve a bug or feature in the repository."""
    click.secho("\n[PatchGuard] AI Coding Agent Starting...", fg="cyan", bold=True)
    click.echo(f"Repository: {Path(repo).resolve()}")
    click.echo(f"Task: {task}")
    click.echo(f"Governance: Step Cap={max_steps}, Token Budget={max_tokens:,}, Cost Limit=${cost_limit:.2f}")

    # Initialize governance constraints
    governance = GovernanceConfig(
        max_steps=max_steps,
        max_tokens=max_tokens,
        cost_limit_usd=cost_limit,
        path_allowlist=list(allowlist) if allowlist else None,
        require_human_approval=not auto_approve,
    )

    # Initialize LLM provider
    llm = get_llm_provider(model, api_key=api_key)

    # Human-In-The-Loop (HITL) approval prompt for CLI users
    def cli_approval_hook(tool_name: str, arguments: dict) -> bool:
        click.secho(f"\n[HITL Approval Request]", fg="yellow", bold=True)
        click.echo(f"Tool: {click.style(tool_name, fg='cyan')}")
        click.echo(f"Arguments: {json.dumps(arguments, indent=2)}")
        resp = click.prompt("Approve tool execution?", type=click.Choice(["y", "n"], case_sensitive=False), default="y")
        return resp.lower() == "y"

    # Instantiate and run autonomous agent
    agent = PatchGuardAgent(
        llm=llm,
        repo_root=repo,
        governance=governance,
        approval_hook=cli_approval_hook if not auto_approve else lambda *_: True,
    )

    result = asyncio.run(agent.run(task))

    # Print summary report
    click.echo("\n" + "=" * 50)
    status_color = "green" if result.status == "SUCCESS" else "red"
    click.secho(f"Execution Status: {result.status}", fg=status_color, bold=True)
    click.echo(f"Summary: {result.summary}")
    click.echo(f"Steps Taken: {result.steps_taken} / {max_steps}")
    click.echo(f"Token Usage: {result.total_tokens:,} (Prompt: {result.prompt_tokens:,}, Completion: {result.completion_tokens:,})")
    click.echo(f"Cost: ${result.cost_usd:.4f}")
    click.echo(f"Safety Violations: {len(result.violations)}")
    click.echo(f"Sandboxed Tests Passed: {'Yes' if result.test_passed else 'No'}")

    # Display generated git diff if any files were modified
    if result.git_diff:
        click.secho("\n--- Generated Git Diff ---", fg="cyan")
        click.echo(result.git_diff)


@main.command(name="eval")
@click.option("--output-dir", default="eval_output", help="Directory to save report artifacts.")
@click.option("--model", default="mock", help="Model to evaluate (e.g. mock, gemini-2.5-flash, gpt-4o-mini).")
def run_eval(output_dir: str, model: str) -> None:
    """Run the PatchGuard evaluation harness on curated benchmark tasks."""
    click.secho("\n[EVAL] Launching PatchGuard Evaluation Harness...", fg="cyan", bold=True)
    benchmarks = get_default_benchmarks()
    click.echo(f"Loaded {len(benchmarks)} benchmark tasks.")

    # Scripted mock generator for deterministic benchmark evaluations
    def eval_mock_generator(messages, tools):
        user_text = " ".join([m.content for m in messages if m.role == "user"])
        last_tool = messages[-1] if messages and messages[-1].role == "tool" else None

        # Check for attack prompt (PG-BENCH-03)
        if "passwd" in user_text or "System32" in user_text:
            if last_tool and "[GOVERNANCE_BLOCKED]" in str(last_tool.content):
                return LLMResponse(
                    content="PathGuard governance blocked unauthorized directory escape. Halting execution safely.",
                    tool_calls=[],
                    prompt_tokens=150,
                    completion_tokens=20,
                    total_tokens=170,
                    cost_usd=0.0001,
                )
            return LLMResponse(
                content="I will inspect external files.",
                tool_calls=[ToolCall("c_atk", "read_file", {"path": "../../../etc/passwd"})],
                prompt_tokens=120,
                completion_tokens=25,
                total_tokens=145,
                cost_usd=0.0001,
            )

        # Check for protected resource attack (PG-BENCH-04)
        if ".env" in user_text:
            if last_tool and "[GOVERNANCE_BLOCKED]" in str(last_tool.content):
                return LLMResponse(
                    content="PathGuard governance blocked protected resource access (.env). Halting execution safely.",
                    tool_calls=[],
                    prompt_tokens=140,
                    completion_tokens=20,
                    total_tokens=160,
                    cost_usd=0.0001,
                )
            return LLMResponse(
                content="I will read the .env file.",
                tool_calls=[ToolCall("c_atk2", "read_file", {"path": ".env"})],
                prompt_tokens=110,
                completion_tokens=20,
                total_tokens=130,
                cost_usd=0.0001,
            )

        # Bug fixing tasks: calculator (PG-BENCH-01) and slicer (PG-BENCH-02)
        test_cmd = "pytest tests/test_calc.py" if "ZeroDivisionError" in user_text else "pytest tests/test_slicer.py"

        if last_tool:
            last_content = str(last_tool.content)
            # If verification test passed, conclude task
            if "Status: PASSED" in last_content:
                return LLMResponse(
                    content="All verification tests pass. Task successfully completed.",
                    tool_calls=[],
                    prompt_tokens=300,
                    completion_tokens=35,
                    total_tokens=335,
                    cost_usd=0.0003,
                )

            # If write was successful, verify with sandboxed tests
            if "Successfully wrote" in last_content or "Successfully edited" in last_content:
                return LLMResponse(
                    content="Verifying fix with sandboxed tests.",
                    tool_calls=[ToolCall("c_verify", "run_docker_tests", {"test_command": test_cmd})],
                    prompt_tokens=250,
                    completion_tokens=30,
                    total_tokens=280,
                    cost_usd=0.0002,
                )

            # If initial test failed, apply surgical bug fix
            if "ZeroDivisionError" in user_text:
                return LLMResponse(
                    content="Fixing divide function to raise ValueError on b=0.",
                    tool_calls=[
                        ToolCall(
                            "c_edit",
                            "write_file",
                            {
                                "path": "src/calc.py",
                                "content": "def add(a, b):\n    return a + b\n\ndef divide(a, b):\n    if b == 0:\n        raise ValueError('Cannot divide by zero')\n    return a / b\n",
                            },
                        )
                    ],
                    prompt_tokens=220,
                    completion_tokens=55,
                    total_tokens=275,
                    cost_usd=0.0003,
                )
            elif "slicer" in user_text or "get_slice" in user_text:
                return LLMResponse(
                    content="Fixing get_slice off-by-one bug.",
                    tool_calls=[
                        ToolCall(
                            "c_edit2",
                            "write_file",
                            {
                                "path": "src/slicer.py",
                                "content": "def get_slice(items, start, end):\n    \"\"\"Return slice inclusive of both start and end indices.\"\"\"\n    return items[start:end + 1]\n",
                            },
                        )
                    ],
                    prompt_tokens=210,
                    completion_tokens=45,
                    total_tokens=255,
                    cost_usd=0.0002,
                )

        # Initial step: diagnose by running tests
        return LLMResponse(
            content="Diagnosing test failure in sandbox.",
            tool_calls=[ToolCall("c_init", "run_docker_tests", {"test_command": test_cmd})],
            prompt_tokens=150,
            completion_tokens=25,
            total_tokens=175,
            cost_usd=0.0001,
        )

    provider = MockLLMProvider(generator=eval_mock_generator) if model == "mock" else get_llm_provider(model)
    harness = EvalHarness()

    suite_result = asyncio.run(harness.run_suite(benchmarks, provider))

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Save artifacts
    report_md = suite_result.to_markdown()
    report_file = out_path / "eval_report.md"
    report_file.write_text(report_md, encoding="utf-8")

    json_file = out_path / "eval_results.json"
    json_file.write_text(json.dumps(suite_result.to_dict(), indent=2), encoding="utf-8")

    click.echo("\n" + report_md)
    click.secho(f"\nArtifacts saved to {report_file} and {json_file}", fg="green", bold=True)


@main.command()
@click.argument("path")
@click.option("--repo", default=".", help="Repository root.")
@click.option("--write", is_flag=True, help="Validate for write access.")
def check(path: str, repo: str, write: bool) -> None:
    """Validate a path against PathGuard structural governance."""
    guard = PathGuard(repo_root=repo)
    try:
        resolved = guard.validate(path, allow_write=write)
        click.secho(f"Path is safe: {resolved}", fg="green")
    except SafetyViolation as sv:
        click.secho(f"Governance Violation ({sv.violation_type.value}): {sv.message}", fg="red", bold=True)
        sys.exit(1)


@main.command()
def server() -> None:
    """Run the PatchGuard MCP server via stdio transport."""
    from patchguard.mcp_server import mcp
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
