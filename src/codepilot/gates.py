"""Human-in-the-loop approval gates.

The assignment names four situations that must pause for human approval:
  1. Opening a PR against the main branch
  2. A change touching more than 5 files
  3. A git push
  4. Retrying after 2 failures

Rather than scatter input() calls through the code, each gate is a small
declarative check that returns whether approval is required and why. The
driver asks the human only when a gate fires. Keeping the gates as data
makes them testable and makes it obvious, in one place, what CodePilot
will and won't do autonomously.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_AUTONOMOUS_FILES = 5
MAX_AUTONOMOUS_FAILURES = 2


@dataclass
class GateCheck:
    required: bool
    reason: str


def gate_pr_to_main(base_branch: str, default_branch: str) -> GateCheck:
    if base_branch == default_branch:
        return GateCheck(True, f"opening a PR against the protected branch '{base_branch}'")
    return GateCheck(False, "")


def gate_file_count(files_changed: int) -> GateCheck:
    if files_changed > MAX_AUTONOMOUS_FILES:
        return GateCheck(
            True,
            f"change touches {files_changed} files (limit for autonomous action "
            f"is {MAX_AUTONOMOUS_FILES})",
        )
    return GateCheck(False, "")


def gate_push() -> GateCheck:
    # A push to the remote is always human-gated: it's the point of no return
    # before a PR.
    return GateCheck(True, "pushing a branch to the remote repository")


def gate_retry_after_failures(failure_count: int) -> GateCheck:
    if failure_count >= MAX_AUTONOMOUS_FAILURES:
        return GateCheck(
            True,
            f"retrying after {failure_count} failed attempts "
            f"(autonomous limit is {MAX_AUTONOMOUS_FAILURES})",
        )
    return GateCheck(False, "")


def prompt_approval(check: GateCheck, ask=input) -> bool:
    """Ask the human to approve a gated action. Returns True if approved.

    `ask` is injectable so tests can drive it without real stdin.
    """
    if not check.required:
        return True
    answer = ask(f"[APPROVAL NEEDED] {check.reason}. Proceed? [y/N] ").strip().lower()
    return answer == "y"