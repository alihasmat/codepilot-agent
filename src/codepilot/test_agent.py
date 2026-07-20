"""The Test Agent.

Runs the project's test suite inside the sandbox and reports a clean
verdict. The Coder uses this to verify a fix actually works before it can
become a PR, rather than trusting its own claim that the tests will pass.

The test command runs through the Phase 4 guardrails, so even the
verification step can't execute something dangerous. Results are parsed
into a small structured object: passed/failed counts, and on failure the
short summary lines that get fed back to the Coder for a retry.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from codepilot.guardrails import assert_command_allowed

# Run pytest through the SAME interpreter running CodePilot, not a bare
# "python" that may resolve to a different environment where the project's
# package and pytest aren't importable (a common macOS/uv gotcha that makes
# pytest collect zero tests). We keep a display string for logging/guardrails
# and build the real argv from sys.executable.
TEST_DISPLAY_COMMAND = "python -m pytest -q"
TEST_ARGV = [sys.executable, "-m", "pytest", "-q"]

_SUMMARY_RE = re.compile(r"(?:(\d+) failed)?[,\s]*(?:(\d+) passed)?(?:[,\s]*(\d+) error)?")


@dataclass
class TestResult:
    passed: int
    failed: int
    errors: int
    ok: bool
    raw_output: str
    failure_summary: str  # the FAILED ... lines, for feeding back to the Coder
    failed_names: frozenset[str] = frozenset()  # e.g. {"tests/test_x.py::test_y"}

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors


def _parse(output: str) -> tuple[int, int, int]:
    """Pull passed/failed/error counts from pytest's last summary line."""
    passed = failed = errors = 0
    for line in output.splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            m = re.search(r"(\d+)\s+passed", line)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+)\s+failed", line)
            if m:
                failed = int(m.group(1))
            m = re.search(r"(\d+)\s+error", line)
            if m:
                errors = int(m.group(1))
    return passed, failed, errors


def _failure_lines(output: str) -> str:
    """Extract the concise failure info the Coder needs to fix the problem."""
    lines = output.splitlines()
    failed = [l for l in lines if l.startswith("FAILED") or l.startswith("ERROR")]
    # Also grab the FAILURES detail block if present, trimmed.
    detail = []
    capture = False
    for l in lines:
        if l.startswith("=") and "FAILURES" in l:
            capture = True
        elif l.startswith("=") and "short test summary" in l:
            capture = False
        elif capture:
            detail.append(l)
    combined = "\n".join(failed)
    if detail:
        combined += "\n\nDetail:\n" + "\n".join(detail[:40])
    return combined.strip()


def _failed_test_names(output: str) -> frozenset[str]:
    """Extract failing test node ids like 'tests/test_x.py::test_y'."""
    names = set()
    for line in output.splitlines():
        m = re.match(r"(?:FAILED|ERROR)\s+(\S+::\S+)", line.strip())
        if m:
            names.add(m.group(1))
    return frozenset(names)


def run_tests(sandbox_root: Path) -> TestResult:
    """Run the test suite in the sandbox and return a structured verdict."""
    assert_command_allowed(TEST_DISPLAY_COMMAND)  # guardrail-checked

    sandbox_root = Path(sandbox_root).resolve()

    # Force pytest to treat the sandbox as the project root and put the sandbox
    # on the import path, so `from app...` resolves regardless of any outer
    # pyproject.toml/conftest above the clone. -p no:cacheprovider avoids
    # writing .pytest_cache into the repo.
    argv = [
        sys.executable, "-m", "pytest", "-q",
        "--rootdir", str(sandbox_root),
        "-p", "no:cacheprovider",
        str(sandbox_root),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(sandbox_root) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        argv,
        cwd=sandbox_root,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    passed, failed, errors = _parse(output)

    # pytest exit codes: 0=all passed, 1=some failed, 2=usage error,
    # 5=no tests collected. "No tests ran" must NOT count as success: you
    # cannot verify a fix against an empty suite.
    no_tests = proc.returncode == 5 or "no tests ran" in output.lower()
    ok = proc.returncode == 0 and failed == 0 and errors == 0 and not no_tests

    failure_summary = ""
    if no_tests:
        failure_summary = (
            "No tests were collected. pytest found no tests to run "
            f"(exit code {proc.returncode}). Raw output:\n{output[-800:]}"
        )
    elif not ok:
        failure_summary = _failure_lines(output)

    return TestResult(
        passed=passed,
        failed=failed,
        errors=errors,
        ok=ok,
        raw_output=output,
        failure_summary=failure_summary,
        failed_names=_failed_test_names(output),
    )