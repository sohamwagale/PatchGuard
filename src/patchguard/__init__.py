"""PatchGuard: AI-Native Coding Agent with Structural Governance and MCP."""

from patchguard.agent import AgentRunResult, PatchGuardAgent
from patchguard.docker_runner import DockerSandboxRunner, SandboxResult
from patchguard.eval_harness import EvalHarness, EvalSuiteResult, EvalTask, EvalTaskResult
from patchguard.guardrails import (
    GovernanceConfig,
    PathGuard,
    SafetyMonitor,
    SafetyViolation,
    SafetyViolationType,
)
from patchguard.llm import (
    BaseLLMProvider,
    GeminiProvider,
    LLMMessage,
    LLMResponse,
    MockLLMProvider,
    OpenAICompatibleProvider,
    ToolCall,
)
from patchguard.mcp_client import PatchGuardMCPClient

__version__ = "0.1.0"
__all__ = [
    "AgentRunResult",
    "BaseLLMProvider",
    "DockerSandboxRunner",
    "EvalHarness",
    "EvalSuiteResult",
    "EvalTask",
    "EvalTaskResult",
    "GeminiProvider",
    "GovernanceConfig",
    "LLMMessage",
    "LLMResponse",
    "MockLLMProvider",
    "OpenAICompatibleProvider",
    "PatchGuardAgent",
    "PatchGuardMCPClient",
    "PathGuard",
    "SafetyMonitor",
    "SafetyViolation",
    "SafetyViolationType",
    "SandboxResult",
    "ToolCall",
]
