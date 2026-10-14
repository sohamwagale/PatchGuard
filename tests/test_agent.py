"""Integration tests for PatchGuardAgent autonomous loop and governance."""

import asyncio
import tempfile
from pathlib import Path

from patchguard.agent import PatchGuardAgent
from patchguard.guardrails import GovernanceConfig
from patchguard.llm import LLMResponse, MockLLMProvider, ToolCall


def test_agent_human_in_the_loop_approval_rejection():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir).resolve()
            (repo / "test.txt").write_text("initial", encoding="utf-8")

            # Mock LLM calls write_file then finishes
            scripted = [
                LLMResponse(
                    content="I want to edit test.txt",
                    tool_calls=[ToolCall("call_1", "write_file", {"path": "test.txt", "content": "tampered"})],
                    prompt_tokens=50,
                    completion_tokens=20,
                ),
                LLMResponse(
                    content="Action was rejected, so I will halt.",
                    tool_calls=[],
                    prompt_tokens=60,
                    completion_tokens=15,
                ),
            ]
            llm = MockLLMProvider(scripted_responses=scripted)

            # Disapprove all mutating actions
            def deny_all(tool_name: str, args: dict) -> bool:
                return False

            agent = PatchGuardAgent(
                llm=llm,
                repo_root=repo,
                governance=GovernanceConfig(require_human_approval=True),
                approval_hook=deny_all,
            )

            result = await agent.run("Modify test.txt")
            # File should remain unedited
            assert (repo / "test.txt").read_text(encoding="utf-8") == "initial"
            assert len(result.violations) == 1
            assert result.violations[0]["type"] == "APPROVAL_REJECTED"

    asyncio.run(run())


def test_agent_aborts_on_step_cap():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir).resolve()

            # Infinite tool calling loop
            def infinite_tools(messages, tools):
                return LLMResponse(
                    content="Looping...",
                    tool_calls=[ToolCall("c_loop", "list_dir", {"path": "."})],
                    prompt_tokens=50,
                    completion_tokens=10,
                )

            llm = MockLLMProvider(generator=infinite_tools)
            agent = PatchGuardAgent(
                llm=llm,
                repo_root=repo,
                governance=GovernanceConfig(max_steps=3, require_human_approval=False),
            )

            result = await agent.run("Infinite loop test")
            assert result.status == "STEP_CAP_EXCEEDED"
            assert result.steps_taken == 4
            assert any(v["type"] == "STEP_CAP_EXCEEDED" for v in result.violations)

    asyncio.run(run())
