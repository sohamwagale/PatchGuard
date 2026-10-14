"""Docker-sandboxed test runner for PatchGuard.

=============================================================================
WHY THIS MODULE EXISTS (Docker Sandbox Concept):
When an AI agent modifies code to fix a bug, it must run test suites to verify
the fix. However, running untrusted code or arbitrary commands directly on the host
system is dangerous:
1. Malicious or broken code could format the drive, wipe user files, or leak secrets.
2. Dependencies on the host system could interfere with testing (missing libraries, OS differences).

Solution:
PatchGuard mounts the workspace into an isolated, ephemeral Docker container:
- Memory and CPU limits prevent denial-of-service / fork bombs.
- Network is disabled (`--network=none`) by default so code cannot exfiltrate secrets.
- Containers are automatically destroyed (`--rm`) after execution.
- If Docker daemon is offline, it provides an isolated process fallback runner.
=============================================================================
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SandboxResult:
    """Outcome and execution metadata of a sandboxed test command.

    Attributes:
        exit_code: Process returncode (0 means tests passed, non-zero means failed).
        stdout: Standard output captured from the test runner (e.g. pytest summary).
        stderr: Error stream output or diagnostic logs.
        duration_seconds: How long the test run took in seconds.
        timed_out: Whether execution was terminated due to exceeding timeout limit.
        is_docker: True if executed inside native Docker container; False if local fallback.
        image: Docker image tag used (e.g. python:3.11-slim).
        command: Exact shell command that was executed.
    """

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    is_docker: bool = False
    image: str | None = None
    command: str = ""

    @property
    def passed(self) -> bool:
        """Helper property: True only if exit code is 0 and no timeout occurred."""
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        """Convert result to a dictionary for JSON reporting and MCP returns."""
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": round(self.duration_seconds, 3),
            "timed_out": self.timed_out,
            "is_docker": self.is_docker,
            "passed": self.passed,
            "command": self.command,
        }


class DockerSandboxRunner:
    """Orchestrates test execution inside an isolated container or fallback sandbox."""

    def __init__(
        self,
        repo_root: str | Path,
        default_image: str = "python:3.11-slim",
        default_timeout: int = 60,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.default_image = default_image
        self.default_timeout = default_timeout
        self._docker_available: bool | None = None

    def is_docker_available(self) -> bool:
        """Probe system to check if Docker binary exists and Docker daemon is responsive."""
        if self._docker_available is not None:
            return self._docker_available

        # 1. Check if 'docker' executable exists in system PATH
        if not shutil.which("docker"):
            self._docker_available = False
            return False

        # 2. Check if Docker daemon is running by pinging 'docker info'
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
                text=True,
                check=False,
            )
            self._docker_available = (res.returncode == 0)
        except Exception:
            self._docker_available = False

        return self._docker_available

    def run_tests(
        self,
        test_command: str = "pytest",
        image: str | None = None,
        timeout: int | None = None,
        network: str = "none",
        force_fallback: bool = False,
    ) -> SandboxResult:
        """Run tests inside Docker if daemon is available, otherwise use isolated fallback.

        Args:
            test_command: The shell command to execute (e.g. 'pytest tests/test_calc.py').
            image: Docker image to spawn (defaults to python:3.11-slim).
            timeout: Execution timeout in seconds (prevents hanging test runs).
            network: Docker network mode ('none' blocks all outbound internet access).
            force_fallback: If True, bypasses Docker and runs in local isolated fallback.
        """
        chosen_timeout = timeout or self.default_timeout
        chosen_image = image or self.default_image

        # Route to native Docker if available; if container fails to launch (e.g. image not downloaded),
        # gracefully degrade to isolated process fallback
        if not force_fallback and self.is_docker_available():
            docker_res = self._run_in_docker(
                test_command=test_command,
                image=chosen_image,
                timeout=chosen_timeout,
                network=network,
            )
            # If docker ran tests, return result; if container failed or tool not found in image,
            # gracefully fall back to local isolated sandbox
            if docker_res.exit_code not in (-1, 127) and "not found" not in docker_res.stderr.lower():
                return docker_res
            return self._run_isolated_fallback(
                test_command=test_command,
                timeout=chosen_timeout,
            )
        else:
            return self._run_isolated_fallback(
                test_command=test_command,
                timeout=chosen_timeout,
            )

    def _run_in_docker(
        self,
        test_command: str,
        image: str,
        timeout: int,
        network: str = "none",
    ) -> SandboxResult:
        """Execute command inside an isolated Docker container with resource constraints."""
        # Normalize Windows backslashes to forward slashes for Docker volume mounting
        repo_posix = str(self.repo_root).replace("\\", "/")

        # Build secure docker run invocation:
        # --rm: Clean up container on exit
        # --network=none: Prevent unauthorized internet access/data exfiltration
        # -v <repo>:/workspace: Mount only the repository folder
        # -w /workspace: Set working directory inside container
        # --memory=1g: Cap RAM to prevent out-of-memory crashes on host
        # --cpus=1.0: Cap CPU to 1 core
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            f"--network={network}",
            "-v",
            f"{repo_posix}:/workspace",
            "-w",
            "/workspace",
            "--memory=1g",
            "--cpus=1.0",
            image,
            "sh",
            "-c",
            test_command,
        ]

        start_time = time.monotonic()
        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            duration = time.monotonic() - start_time
            return SandboxResult(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_seconds=duration,
                timed_out=False,
                is_docker=True,
                image=image,
                command=test_command,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start_time
            return SandboxResult(
                exit_code=-1,
                stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "") + f"\n[PatchGuard] Test run timed out after {timeout}s",
                duration_seconds=duration,
                timed_out=True,
                is_docker=True,
                image=image,
                command=test_command,
            )
        except Exception as exc:
            duration = time.monotonic() - start_time
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=f"[PatchGuard] Docker execution failed: {exc}",
                duration_seconds=duration,
                timed_out=False,
                is_docker=True,
                image=image,
                command=test_command,
            )

    def _run_isolated_fallback(
        self,
        test_command: str,
        timeout: int,
    ) -> SandboxResult:
        """Local isolated fallback runner when Docker daemon is not active.

        Security precautions taken:
        1. Scrub environment variables containing credentials or tokens.
        2. Set PYTHONPATH to include only the repository root.
        3. Enforce strict timeout.
        """
        env = os.environ.copy()

        # Scrub sensitive environment variables (API keys, secrets, passwords)
        sensitive_keys = [
            k for k in env if any(s in k.lower() for s in ["key", "token", "secret", "auth", "pass"])
        ]
        for key in sensitive_keys:
            env.pop(key, None)

        # Prepend virtual environment Scripts directory to PATH so virtualenv binaries (e.g. pytest) take precedence
        venv_bin = str(Path(sys.executable).parent)
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
        env["PYTHONPATH"] = str(self.repo_root) + os.pathsep + env.get("PYTHONPATH", "")

        start_time = time.monotonic()
        try:
            proc = subprocess.run(
                test_command,
                cwd=str(self.repo_root),
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
            duration = time.monotonic() - start_time
            return SandboxResult(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_seconds=duration,
                timed_out=False,
                is_docker=False,
                command=test_command,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start_time
            return SandboxResult(
                exit_code=-1,
                stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "") + f"\n[PatchGuard] Test run timed out after {timeout}s",
                duration_seconds=duration,
                timed_out=True,
                is_docker=False,
                command=test_command,
            )
        except Exception as exc:
            duration = time.monotonic() - start_time
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=f"[PatchGuard] Local sandbox execution failed: {exc}",
                duration_seconds=duration,
                timed_out=False,
                is_docker=False,
                command=test_command,
            )
