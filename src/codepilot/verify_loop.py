"""The implement-and-verify loop.

Ties the Coder (Phase 4) and Test Agent (Phase 5) into the retry loop the
assignment specifies. Per the chosen design, retries apply automatically
inside the sandbox; only the final result is surfaced for approval. The
loop maps onto the state machine's TESTING <-> IMPLEMENTING cycle.

Flow per attempt:
  1. Coder proposes edits (given the task, plus prior failures if retrying)
  2. Edits apply into the sandbox
  3. Test Agent runs the suite
  4. Pass -> done. Fail -> feed failures back and retry, up to max_retries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from codepilot.coder import EditProposal, propose_edits
from codepilot.config import settings
from codepilot.diffing import apply_edits
from codepilot.test_agent import TestResult, run_tests


@dataclass
class AttemptRecord:
    attempt: int
    reasoning: str
    files_changed: list[str]
    test_passed: bool
    failure_summary: str


@dataclass
class LoopResult:
    success: bool
    attempts: list[AttemptRecord] = field(default_factory=list)
    final_proposal: EditProposal | None = None
    final_tests: TestResult | None = None


def implement_and_verify(
    task_text: str,
    target_paths: list[str],
    sandbox_root: Path,
    max_retries: int | None = None,
) -> LoopResult:
    """Run the propose -> apply -> test loop until tests pass or retries run out."""
    max_retries = max_retries if max_retries is not None else settings.max_coder_retries
    result = LoopResult(success=False)
    accumulated_task = task_text

    for attempt in range(1, max_retries + 1):
        proposal = propose_edits(accumulated_task, target_paths, sandbox_root)
        result.final_proposal = proposal

        if not proposal.edits:
            result.attempts.append(AttemptRecord(
                attempt=attempt,
                reasoning=proposal.reasoning,
                files_changed=[],
                test_passed=False,
                failure_summary="Coder proposed no applicable edits.",
            ))
            break  # no point retrying if the Coder can't propose anything

        written = apply_edits(proposal, sandbox_root)
        tests = run_tests(sandbox_root)
        result.final_tests = tests

        result.attempts.append(AttemptRecord(
            attempt=attempt,
            reasoning=proposal.reasoning,
            files_changed=written,
            test_passed=tests.ok,
            failure_summary=tests.failure_summary,
        ))

        if tests.ok:
            result.success = True
            break

        # Feed the failure back into the task for the next attempt.
        accumulated_task = (
            f"{task_text}\n\n"
            f"Your previous attempt did not pass the tests. Test output:\n"
            f"{tests.failure_summary}\n\n"
            f"Fix the code so all tests pass."
        )

    return result