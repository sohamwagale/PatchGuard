"""Unit tests for PathGuard and structural governance."""

import tempfile
from pathlib import Path
import pytest

from patchguard.guardrails import (
    GovernanceConfig,
    PathGuard,
    SafetyMonitor,
    SafetyViolation,
    SafetyViolationType,
)


def test_pathguard_allows_safe_relative_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "src").mkdir()
        test_file = repo / "src" / "main.py"
        test_file.write_text("print('hello')", encoding="utf-8")

        guard = PathGuard(repo_root=repo)
        safe_path = guard.validate("src/main.py")
        assert safe_path == test_file.resolve()


def test_pathguard_blocks_directory_traversal():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        guard = PathGuard(repo_root=repo)

        with pytest.raises(SafetyViolation) as exc_info:
            guard.validate("../outside_repo.txt")

        assert exc_info.value.violation_type == SafetyViolationType.PATH_TRAVERSAL


def test_pathguard_blocks_protected_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        guard = PathGuard(repo_root=repo)

        # Block .git
        with pytest.raises(SafetyViolation) as exc_1:
            guard.validate(".git/config")
        assert exc_1.value.violation_type == SafetyViolationType.PROTECTED_RESOURCE

        # Block .env
        with pytest.raises(SafetyViolation) as exc_2:
            guard.validate(".env")
        assert exc_2.value.violation_type == SafetyViolationType.PROTECTED_RESOURCE


def test_pathguard_enforces_write_allowlist():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "src").mkdir()
        (repo / "build").mkdir()

        guard = PathGuard(repo_root=repo, path_allowlist=["src"])

        # Writing to src is allowed
        allowed = guard.validate("src/code.py", allow_write=True)
        assert allowed == (repo / "src" / "code.py").resolve()

        # Writing outside allowlist is blocked
        with pytest.raises(SafetyViolation) as exc_info:
            guard.validate("build/output.txt", allow_write=True)
        assert exc_info.value.violation_type == SafetyViolationType.DISALLOWED_PATH


def test_safetymonitor_enforces_step_cap():
    config = GovernanceConfig(max_steps=3)
    monitor = SafetyMonitor(config)

    monitor.record_step()
    monitor.record_step()
    monitor.record_step()

    with pytest.raises(SafetyViolation) as exc_info:
        monitor.record_step()

    assert exc_info.value.violation_type == SafetyViolationType.STEP_CAP_EXCEEDED
    assert len(monitor.violations) == 1


def test_safetymonitor_enforces_token_and_cost_budgets():
    config = GovernanceConfig(max_tokens=1000, cost_limit_usd=0.01)
    monitor = SafetyMonitor(config)

    monitor.record_usage(prompt_tokens=400, completion_tokens=400, estimated_cost=0.005)
    assert monitor.total_tokens == 800

    # Exceed tokens
    with pytest.raises(SafetyViolation) as exc_info:
        monitor.record_usage(prompt_tokens=200, completion_tokens=100, estimated_cost=0.001)
    assert exc_info.value.violation_type == SafetyViolationType.TOKEN_BUDGET_EXCEEDED
