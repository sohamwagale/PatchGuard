"""Unit tests for EvalHarness benchmark scoring and metric calculation."""

import asyncio
import tempfile

from patchguard.eval_harness import EvalHarness, EvalTask
from patchguard.llm import LLMResponse, MockLLMProvider, ToolCall


def test_eval_harness_tracks_metrics_and_markdown():
    async def run():
        tasks = [
            EvalTask(
                task_id="TEST-01",
                name="Pass Task",
                description="Fix calculation bug",
                files={
                    "math_mod.py": "def add(a, b): return a + b\n",
                    "test_math.py": "from math_mod import add\ndef test_add(): assert add(1, 2) == 3\n",
                },
                test_command="pytest test_math.py",
            )
        ]

        # Script LLM to run docker tests and succeed
        scripted = [
            LLMResponse(
                content="Running tests.",
                tool_calls=[ToolCall("c1", "run_docker_tests", {"test_command": "pytest test_math.py"})],
                prompt_tokens=100,
                completion_tokens=25,
                cost_usd=0.0002,
            ),
            LLMResponse(
                content="Tests passed.",
                tool_calls=[],
                prompt_tokens=120,
                completion_tokens=10,
                cost_usd=0.0001,
            ),
        ]

        llm = MockLLMProvider(scripted_responses=scripted)
        harness = EvalHarness()
        suite = await harness.run_suite(tasks, llm)

        assert suite.total_tasks == 1
        assert suite.passed_tasks == 1
        assert suite.pass_rate == 1.0
        assert suite.total_steps >= 1
        assert suite.total_tokens > 0
        assert suite.total_cost_usd > 0

        md = suite.to_markdown()
        assert "PatchGuard Evaluation Harness Report" in md
        assert "100.0%" in md
        assert "TEST-01" in md

    asyncio.run(run())
