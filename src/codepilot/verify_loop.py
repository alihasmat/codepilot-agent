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
    baseline_failures: frozenset[str] = frozenset()


def implement_and_verify(
    task_text: str,
    target_paths: list[str],
    sandbox_root: Path,
    max_retries: int | None = None,
    skill_block: str | None = None,
) -> LoopResult:
    """Run the propose -> apply -> test loop until the task introduces no new
    failures, or retries run out.

    A task is judged on the tests IT affects, not the whole suite in absolute
    terms. We record which tests already fail on the pristine checkout (the
    baseline); a task succeeds when it introduces no *new* failures beyond
    that baseline. This prevents an unrelated pre-existing bug (e.g. a
    still-open bug in another file) from failing, say, a documentation task.
    """
    max_retries = max_retries if max_retries is not None else settings.max_coder_retries
    result = LoopResult(success=False)
    accumulated_task = task_text

    # Baseline: what's already broken before we touch anything.
    baseline = run_tests(sandbox_root)
    result.baseline_failures = baseline.failed_names

    for attempt in range(1, max_retries + 1):
        proposal = propose_edits(accumulated_task, target_paths, sandbox_root,
                                 skill_block=skill_block)
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

        # New failures = tests failing now that were NOT failing at baseline.
        new_failures = tests.failed_names - baseline.failed_names
        # A task passes if it introduced no new failures AND the suite could
        # actually run (no collection error, tests present).
        task_ok = (not new_failures) and (tests.errors == 0) and (tests.total > 0)

        failure_desc = ""
        if not task_ok:
            if new_failures:
                failure_desc = (
                    f"Introduced {len(new_failures)} new failure(s): "
                    f"{sorted(new_failures)}"
                )
            elif tests.total == 0:
                failure_desc = "No tests could be collected."
            else:
                failure_desc = tests.failure_summary

        result.attempts.append(AttemptRecord(
            attempt=attempt,
            reasoning=proposal.reasoning,
            files_changed=written,
            test_passed=task_ok,
            failure_summary=failure_desc,
        ))

        if task_ok:
            result.success = True
            break

        # Feed only the NEW failures back; the Coder shouldn't chase
        # pre-existing bugs outside its task.
        accumulated_task = (
            f"{task_text}\n\n"
            f"Your change introduced these NEW test failures (pre-existing "
            f"failures are not your concern):\n{sorted(new_failures)}\n\n"
            f"Full output:\n{tests.failure_summary}\n\n"
            f"Fix your change so it introduces no new failures."
        )

    return result