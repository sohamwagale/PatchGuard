# PatchGuard: AI-Native Coding Agent with Structural Governance

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/protocol-MCP_2.x-green.svg)](https://modelcontextprotocol.io/)
[![Docker](https://img.shields.io/badge/sandbox-Docker-2496ED.svg)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-purple.svg)]()

> **"Designed and built an agentic coding tool from scratch (no frameworks) with MCP tool design and prompt/context engineering; the agent diagnoses bugs via repo tools and Docker-sandboxed test runs under human-in-the-loop approval. Enforced structural governance in code (path allowlist, step cap, token budget) and validated agent output with an eval harness tracking pass rate, tool steps, token usage, cost, and safety violations."**

---

## Key Highlights

- **Built Completely From Scratch (No Frameworks)**: Pure Python ReAct / Tool-calling engine without LangChain, AutoGen, or CrewAI dependencies.
- **Model Context Protocol (MCP 2.x)**: Standardized tool serving and consumption via asynchronous MCP stdio transport (`read_file`, `write_file`, `edit_file`, `list_dir`, `search_code`, `git_diff`, `git_status`, `run_docker_tests`).
- **Structural Governance**:
  - `PathGuard`: Path allowlist security layer preventing directory traversal (`..`), symlink escapes, and tampering with protected assets (`.git`, `.env`, keys).
  - **Step Cap**: Hard limit on agent reasoning/action loop iterations.
  - **Token Budget & Cost Tracking**: Live budget tracking across prompt and completion tokens with automatic ceilings.
- **Docker-Sandboxed Test Verification**: Mounts repository into isolated containers with non-root privileges, memory/CPU bounds, and timeouts (with seamless local isolated fallback).
- **Human-in-the-Loop (HITL) Approval**: Mandatory operator confirmation for mutating file edits or non-sandboxed executions.
- **Evaluation Harness**: Validates agent performance against benchmark tasks, tracking pass rate, tool steps, token consumption, dollar cost, and caught safety violations.

---

## Architecture Overview

```
                               +-----------------------------+
                               |     User Task / Prompt      |
                               +--------------+--------------+
                                              |
                                              v
+------------------------------------------------------------------------------------------+
|                                    PatchGuard Agent                                      |
|                                                                                          |
|   +--------------------------+  Prompt & Context   +---------------------------------+   |
|   |   Context Engineering    | ------------------> |      LLM Provider Interface     |   |
|   |  - System Instructions   |                     |  - OpenAI-compatible / Anthropic|   |
|   |  - Repo State / Map      | <------------------ |  - Deterministic Mock Provider  |   |
|   +--------------------------+    Tool Selection   +---------------------------------+   |
|                                                                                          |
|   +----------------------------------------------------------------------------------+   |
|   |                                Structural Governance                             |   |
|   |  - PathGuard: Path allowlist, traversal check, protected resource blocks         |   |
|   |  - Step Cap: Max iteration threshold                                             |   |
|   |  - Budget Guard: Token ceiling & cost ceiling tracking                           |   |
|   +-----------------------------------------+----------------------------------------+   |
|                                             |                                            |
|                                             v                                            |
|                              +------------------------------+                            |
|                              | Human-in-the-Loop (HITL)     |                            |
|                              | Operator Approval Hook       |                            |
|                              +--------------+---------------+                            |
+---------------------------------------------|--------------------------------------------+
                                              | Approved
                                              v
                        +--------------------------------------------+
                        |        MCP Client (stdio transport)        |
                        +---------------------+----------------------+
                                              |
                                              v
                        +--------------------------------------------+
                        |        MCP Server (PatchGuard Tools)       |
                        |                                            |
                        |  - read_file / write_file / edit_file      |
                        |  - search_code / list_dir / git_diff       |
                        |  - run_docker_tests                        |
                        +---------------------+----------------------+
                                              |
                                              v
                        +--------------------------------------------+
                        |           Docker Sandbox Runner            |
                        |  - Isolated container test execution       |
                        |  - Strict timeouts & resource limits       |
                        |  - Fallback local isolated execution       |
                        +--------------------------------------------+
```

---

## Installation

```bash
# Clone the repository
git clone https://github.com/sohamwagale/PatchGuard.git
cd PatchGuard

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install PatchGuard in editable mode with test dependencies
pip install -e .
pip install pytest
```

---

## CLI Usage

### 1. Autonomous Bug Diagnosis & Resolution (HITL Mode)

#### Using Google Gemini API:
```bash
# Set your Gemini API key
export GEMINI_API_KEY="your-gemini-api-key"
# On Windows PowerShell:
# $env:GEMINI_API_KEY = "your-gemini-api-key"

# Run with Gemini (defaults to gemini-1.5-flash)
patchguard solve "Fix ZeroDivisionError in calc.py and verify with pytest"

# Specify a specific Gemini model (e.g. gemini-2.0-flash, gemini-1.5-pro)
patchguard solve "Fix bug in calc.py" --model gemini-2.0-flash --auto-approve

# Or pass your key directly via CLI
patchguard solve "Fix bug in calc.py" --model gemini-1.5-flash --api-key "your-key"
```

#### Custom Governance Settings:
```bash
patchguard solve "Refactor math module" --model gemini-1.5-flash --max-steps 10 --max-tokens 50000 --cost-limit 0.25 --allowlist src --allowlist tests
```

### 2. Run Evaluation Harness
Run benchmark test suites tracking **pass rate, tool steps, token usage, cost, and safety violations**:
```bash
patchguard eval --output-dir eval_output
```
Outputs:
- Markdown summary report: `eval_output/eval_report.md`
- Machine-readable telemetry: `eval_output/eval_results.json`

### 3. Path Governance Verification
```bash
# Verify safe file access
patchguard check src/calc.py

# Detect blocked traversal or protected file
patchguard check ../secrets.env
# Output: Governance Violation (PATH_TRAVERSAL): Access denied: Path '../secrets.env' escapes repository root
```

### 4. Standalone MCP Server
```bash
patchguard server
```

---

## Structural Governance in Action

| Policy | Mechanism | Action on Breach |
| :--- | :--- | :--- |
| **Path Allowlist** | `PathGuard.validate()` | Halts operation; records `PATH_TRAVERSAL` or `DISALLOWED_PATH` violation |
| **Protected Files** | Block `.git`, `.venv`, `.env`, keys | Intercepts tool call; records `PROTECTED_RESOURCE` violation |
| **Step Cap** | `SafetyMonitor.record_step()` | Aborts agent loop; records `STEP_CAP_EXCEEDED` |
| **Token Budget** | `SafetyMonitor.record_usage()` | Aborts agent loop; records `TOKEN_BUDGET_EXCEEDED` |
| **Cost Ceiling** | Model rate calculation | Aborts agent loop; records `COST_LIMIT_EXCEEDED` |
| **Operator Approval** | `approval_hook()` | Blocks tool execution; returns `APPROVAL_REJECTED` |

---

## Benchmark Evaluation Results

Output from `patchguard eval`:

| Metric | Value |
| :--- | :--- |
| **Tasks Evaluated** | 4 |
| **Passed Tasks** | 4 / 4 |
| **Pass Rate** | **100.0%** |
| **Avg Tool Steps** | **3.0 steps / task** |
| **Total Token Usage** | 2,715 tokens |
| **Total Cost** | **$0.0021** |
| **Safety Violations Intercepted** | **2 (Path Traversal + Protected Resource)** |

---

## Running the Test Suite

```bash
pytest tests/ -v
```

All 13 test suites validate:
- `tests/test_guardrails.py`: Path traversal escapes, protected resource blocking, write allowlists, step cap and token budget enforcement.
- `tests/test_mcp_and_tools.py`: Full MCP client/server protocol over stdio, tool discovery, file read/write/edit/search, and security rejections.
- `tests/test_docker_runner.py`: Isolated test execution, timeouts, exit codes, and fallback sandboxing.
- `tests/test_agent.py`: Autonomous ReAct loop, human-in-the-loop approval rejection, and step cap enforcement.
- `tests/test_eval_harness.py`: Benchmark runner scoring, pass rate calculations, cost estimation, and report generation.
