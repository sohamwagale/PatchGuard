"""Unit tests for Docker and sandboxed test execution."""

import sys
import tempfile
from pathlib import Path
import pytest

from patchguard.docker_runner import DockerSandboxRunner


def test_isolated_sandbox_runner_executes_command():
    with tempfile.TemporaryDirectory() as tmpdir:
        runner = DockerSandboxRunner(repo_root=tmpdir)
        # Run standard python one-liner in isolated runner
        result = runner.run_tests(
            test_command=f'"{sys.executable}" -c "print(\'SANDBOX_OK\')"',
            force_fallback=True,
        )
        assert result.exit_code == 0
        assert "SANDBOX_OK" in result.stdout
        assert result.passed


def test_isolated_sandbox_runner_handles_failure():
    with tempfile.TemporaryDirectory() as tmpdir:
        runner = DockerSandboxRunner(repo_root=tmpdir)
        result = runner.run_tests(
            test_command=f'"{sys.executable}" -c "import sys; sys.exit(2)"',
            force_fallback=True,
        )
        assert result.exit_code == 2
        assert not result.passed


def test_isolated_sandbox_runner_handles_timeout():
    with tempfile.TemporaryDirectory() as tmpdir:
        runner = DockerSandboxRunner(repo_root=tmpdir)
        result = runner.run_tests(
            test_command=f'"{sys.executable}" -c "import time; time.sleep(5)"',
            timeout=1,
            force_fallback=True,
        )
        assert result.timed_out
        assert not result.passed
