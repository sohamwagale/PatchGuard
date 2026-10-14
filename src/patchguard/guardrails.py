"""Structural governance and safety guardrails for PatchGuard.

=============================================================================
WHY THIS MODULE EXISTS (Structural Governance Concept):
Autonomous AI coding agents have the ability to read, edit, and run code.
Without hard boundaries, an agent can:
1. Escape the repository (e.g. read /etc/passwd or steal parent-folder secrets).
2. Tamper with sensitive files like .git repository history or .env credentials.
3. Get stuck in infinite reasoning/execution loops (costing huge API bills).
4. Exceed the user's allocated token or dollar budget.

PatchGuard implements four strict layers of defense:
- PathGuard: Resolves paths canonicalizing symlinks & ".." to enforce repository boundaries.
- Allowlist: Restricts write operations to permitted subdirectories (e.g., ['src', 'tests']).
- Step Cap: Sets a hard maximum on the number of tool iterations per task.
- Token Budget & Cost Limit: Monitors real-time LLM token spend and terminates upon breach.
=============================================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class SafetyViolationType(str, Enum):
    """Enumeration of every recognized security/governance violation.

    Categorizing violations allows the evaluation harness and security monitors
    to measure the exact type and frequency of prevented attacks or misbehaviors.
    """
    PATH_TRAVERSAL = "PATH_TRAVERSAL"            # Attempted to escape repo with '..' or external path
    DISALLOWED_PATH = "DISALLOWED_PATH"          # Target path is outside the allowed write subpaths
    PROTECTED_RESOURCE = "PROTECTED_RESOURCE"    # Attempted to touch .git, .env, private keys, etc.
    STEP_CAP_EXCEEDED = "STEP_CAP_EXCEEDED"      # Exceeded maximum reasoning/tool iterations
    TOKEN_BUDGET_EXCEEDED = "TOKEN_BUDGET_EXCEEDED"  # Exceeded total token consumption limit
    COST_LIMIT_EXCEEDED = "COST_LIMIT_EXCEEDED"  # Exceeded maximum dollar spend limit
    UNAUTHORIZED_TOOL = "UNAUTHORIZED_TOOL"      # Tool called is not on the allowed tools list
    APPROVAL_REJECTED = "APPROVAL_REJECTED"      # Human operator rejected tool execution


class SafetyViolation(Exception):
    """Custom exception raised whenever a structural governance policy is breached.

    Inherits from Python's built-in Exception so it can halt execution immediately,
    while also carrying structured telemetry (violation type, tool name, details).
    """

    def __init__(
        self,
        violation_type: SafetyViolationType,
        message: str,
        tool_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.violation_type = violation_type
        self.message = message
        self.tool_name = tool_name
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize violation information for logging and eval reporting."""
        return {
            "type": self.violation_type.value,
            "message": self.message,
            "tool_name": self.tool_name,
            "details": self.details,
        }


@dataclass
class GovernanceConfig:
    """Configuration dataclass holding all safety and resource thresholds.

    Attributes:
        max_steps: Hard limit on how many tool calling cycles the agent can take.
        max_tokens: Total token ceiling (prompt + completion) across the entire session.
        cost_limit_usd: Financial budget ceiling in USD.
        path_allowlist: Specific directories allowed for modifications (e.g. ['src', 'tests']).
                        None means any path inside the repository root is allowed.
        protected_patterns: File and directory names that must NEVER be touched (e.g. .git, .env).
        require_human_approval: If True, mutating actions pause for interactive user approval.
        allowed_tools: Optional whitelist of tool names permitted for this run.
    """

    max_steps: int = 15
    max_tokens: int = 80_000
    cost_limit_usd: float = 0.50
    path_allowlist: list[str] | None = None
    protected_patterns: list[str] = field(
        default_factory=lambda: [
            ".git",
            ".venv",
            "venv",
            ".env",
            "id_rsa",
            "id_ed25519",
            ".pem",
            ".key",
            ".secrets",
        ]
    )
    require_human_approval: bool = True
    allowed_tools: list[str] | None = None


class PathGuard:
    """Security sentinel that inspects and validates file paths before file operations.

    How it defends against attacks:
    1. Canonicalization: Uses `Path.resolve()` to eliminate '..' relative path escapes
       and follow symbolic links to their true physical disk location.
    2. Containment Check: Uses `resolved.is_relative_to(repo_root)` to ensure the target
       is physically located inside the intended repository folder.
    3. Protected Resource Filtering: Scans path components to block access to secrets (.env, keys).
    4. Write Allowlist: Restricts write operations to explicit allowed subdirectories.
    """

    def __init__(
        self,
        repo_root: str | Path,
        path_allowlist: Iterable[str] | None = None,
        protected_patterns: Iterable[str] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()

        # Convert relative allowlist paths into absolute canonical paths
        self.path_allowlist = [
            (self.repo_root / p).resolve() for p in (path_allowlist or [])
        ]

        # Use provided protected patterns or default sensitive files list
        self.protected_patterns = list(
            protected_patterns
            if protected_patterns is not None
            else [
                ".git",
                ".venv",
                "venv",
                ".env",
                "id_rsa",
                "id_ed25519",
                ".pem",
                ".key",
            ]
        )

    def validate(self, path: str | Path, allow_write: bool = False) -> Path:
        """Resolve and validate that a path is safe to access within governance bounds.

        Args:
            path: The candidate file or directory path (relative or absolute).
            allow_write: Whether this operation intends to mutate (create/edit/write) the file.

        Returns:
            The safe, fully resolved absolute Path.

        Raises:
            SafetyViolation: If the path attempts to escape the repository root,
                             touches a protected file, or violates the write allowlist.
        """
        raw_str = str(path).strip()
        if not raw_str:
            raise SafetyViolation(
                violation_type=SafetyViolationType.DISALLOWED_PATH,
                message="File path cannot be empty",
            )

        candidate = Path(path)
        # Relative paths are anchored against the repository root
        if not candidate.is_absolute():
            candidate = self.repo_root / candidate

        # Canonicalize path: resolves symlinks and eliminates '..' traversal segments
        try:
            resolved = candidate.resolve()
        except Exception as exc:
            raise SafetyViolation(
                violation_type=SafetyViolationType.PATH_TRAVERSAL,
                message=f"Failed to resolve path '{path}': {exc}",
                details={"input_path": str(path)},
            ) from exc

        # DEFENSE 1: Path Traversal Check (Must be inside repo_root)
        if not resolved.is_relative_to(self.repo_root):
            raise SafetyViolation(
                violation_type=SafetyViolationType.PATH_TRAVERSAL,
                message=f"Access denied: Path '{path}' escapes repository root '{self.repo_root}'",
                details={"resolved": str(resolved), "repo_root": str(self.repo_root)},
            )

        # DEFENSE 2: Protected Resource Check (Cannot touch .git, .env, private keys)
        parts = resolved.relative_to(self.repo_root).parts
        for part in parts:
            for pattern in self.protected_patterns:
                if part == pattern or part.startswith(pattern):
                    raise SafetyViolation(
                        violation_type=SafetyViolationType.PROTECTED_RESOURCE,
                        message=f"Access denied: Path '{path}' accesses protected resource '{part}'",
                        details={"path": str(resolved), "protected_match": part},
                    )

        # DEFENSE 3: Write Allowlist Check (e.g. only allow writes inside 'src' or 'tests')
        if allow_write and self.path_allowlist:
            matches_allowlist = any(
                resolved == allowed or resolved.is_relative_to(allowed)
                for allowed in self.path_allowlist
            )
            if not matches_allowlist:
                allowed_rel = [
                    str(a.relative_to(self.repo_root)) for a in self.path_allowlist
                ]
                raise SafetyViolation(
                    violation_type=SafetyViolationType.DISALLOWED_PATH,
                    message=f"Access denied: Write target '{resolved.relative_to(self.repo_root)}' is not in path allowlist {allowed_rel}",
                    details={
                        "path": str(resolved),
                        "allowed_subpaths": allowed_rel,
                    },
                )

        return resolved


class SafetyMonitor:
    """Tracks runtime resource consumption and halts the agent if limits are reached.

    Tracks:
    - Step count (how many tool iterations taken so far)
    - Prompt & completion tokens used
    - Total dollar cost accumulated
    - List of all safety violations intercepted
    """

    def __init__(self, config: GovernanceConfig) -> None:
        self.config = config
        self.current_step: int = 0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.cost_usd: float = 0.0
        self.violations: list[SafetyViolation] = []

    def record_step(self, tool_name: str | None = None) -> None:
        """Increment the step counter and raise a violation if step cap is exceeded."""
        self.current_step += 1
        if self.current_step > self.config.max_steps:
            violation = SafetyViolation(
                violation_type=SafetyViolationType.STEP_CAP_EXCEEDED,
                message=f"Agent exceeded maximum allowed step cap ({self.config.max_steps})",
                tool_name=tool_name,
                details={"step": self.current_step, "max_steps": self.config.max_steps},
            )
            self.violations.append(violation)
            raise violation

    def record_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        estimated_cost: float = 0.0,
    ) -> None:
        """Update token counts and cost, enforcing budget ceilings."""
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += prompt_tokens + completion_tokens
        self.cost_usd += estimated_cost

        # Enforce maximum token budget limit
        if self.total_tokens > self.config.max_tokens:
            violation = SafetyViolation(
                violation_type=SafetyViolationType.TOKEN_BUDGET_EXCEEDED,
                message=f"Token budget exceeded ({self.total_tokens} > {self.config.max_tokens})",
                details={
                    "total_tokens": self.total_tokens,
                    "max_tokens": self.config.max_tokens,
                },
            )
            self.violations.append(violation)
            raise violation

        # Enforce maximum financial dollar spend ceiling
        if self.cost_usd > self.config.cost_limit_usd:
            violation = SafetyViolation(
                violation_type=SafetyViolationType.COST_LIMIT_EXCEEDED,
                message=f"Cost limit exceeded (${self.cost_usd:.4f} > ${self.config.cost_limit_usd:.4f})",
                details={
                    "cost_usd": self.cost_usd,
                    "cost_limit_usd": self.config.cost_limit_usd,
                },
            )
            self.violations.append(violation)
            raise violation

    def record_violation(self, violation: SafetyViolation) -> None:
        """Manually record a caught safety violation without crashing the monitor."""
        self.violations.append(violation)

    def get_metrics(self) -> dict[str, Any]:
        """Export comprehensive metrics dictionary for the evaluation harness."""
        return {
            "current_step": self.current_step,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
        }
