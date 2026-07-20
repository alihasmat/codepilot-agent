"""Diagnostic: run the Test Agent against the current sandbox and show
exactly what pytest did. Use this when tests report 0 passed / 0 failed
to see the raw collection output.

Usage:
    uv run python scripts/diagnose_tests.py
"""

from __future__ import annotations

from codepilot.agents.test_agent import run_tests
from codepilot.explorer.workspace import RepoWorkspace


def main() -> int:
    ws = RepoWorkspace()
    ws.ensure_cloned()
    print(f"Sandbox: {ws.path}")
    result = run_tests(ws.path)
    print(f"\nok={result.ok}  passed={result.passed}  failed={result.failed}  errors={result.errors}")
    print("\n===== RAW PYTEST OUTPUT =====")
    print(result.raw_output)
    print("===== END =====")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())